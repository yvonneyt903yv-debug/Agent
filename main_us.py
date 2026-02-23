# 启动入口
import sys
import os
import time
import json
import asyncio
import re
import hashlib
import platform
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def prepare_vps_runtime():
    """
    VPS 兼容:
    1) Linux 默认禁用本地代理环境变量，避免 127.0.0.1:7890 导致 Selenium 访问失败。
    2) 检查 prompts/system_prompt.md 是否存在（不自动创建）。
    """
    if platform.system() == "Linux":
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(key, None)
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"

    prompt_file = os.path.join(BASE_DIR, "prompts", "system_prompt.md")
    if not os.path.exists(prompt_file):
        print(f"⚠️ 提示: Prompt 文件不存在: {prompt_file}")


prepare_vps_runtime()

# 确保能找到 src 目录下的模块
sys.path.append(BASE_DIR)

from src.agent import run_agent
from src.crawler import fetch_latest_articles
from src import translator
from src.reviewer import review_article
from src.gemini_brain import analyze_single_article_content, decide_best_articles, generate_attractive_title
from src.tools import _save_md_and_docx, OUTPUT_ROOT
from src.checkpoint import PipelineCheckpoint

# 邮件通知
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gps"))
try:
    from email_notifier import send_publish_notification
    EMAIL_NOTIFY_AVAILABLE = True
except ImportError:
    EMAIL_NOTIFY_AVAILABLE = False

CHECK_INTERVAL = 7200  # 检查间隔（秒），7200=2小时
CHECKPOINT_FILE = os.path.join(OUTPUT_ROOT, "pipeline_checkpoint.json")
LOCK_FILE = os.path.join(OUTPUT_ROOT, "monitor.lock")
TRACKED_FILE = os.path.join(OUTPUT_ROOT, "tracked_articles.json")


def is_locked():
    """检查是否有其他实例正在运行（增强版，自动清理僵尸锁）"""
    if not os.path.exists(LOCK_FILE):
        return False
    try:
        with open(LOCK_FILE, 'r') as f:
            content = f.read().strip()
            if not content:
                # 空锁文件，直接删除
                print(f"⚠️ 发现空锁文件，自动清理...")
                os.remove(LOCK_FILE)
                return False
            pid = int(content)
        
        # 检查进程是否存在
        try:
            os.kill(pid, 0)
            # 进程存在，检查是否是Python进程
            import subprocess
            result = subprocess.run(['ps', '-p', str(pid), '-o', 'comm='], 
                                  capture_output=True, text=True)
            process_name = result.stdout.strip()
            if 'python' in process_name.lower():
                return True
            else:
                # PID存在但不是Python进程，清理锁
                print(f"⚠️ 锁文件PID {pid} 对应进程不是Python ({process_name})，清理锁文件...")
                os.remove(LOCK_FILE)
                return False
        except OSError:
            # 进程不存在，清理旧锁
            print(f"⚠️ 发现僵尸锁文件 (PID {pid} 不存在)，自动清理...")
            try:
                os.remove(LOCK_FILE)
            except Exception as e:
                print(f"  清理锁文件失败: {e}")
            return False
    except ValueError:
        # 锁文件内容不是有效PID
        print(f"⚠️ 锁文件内容无效，自动清理...")
        try:
            os.remove(LOCK_FILE)
        except:
            pass
        return False
    except Exception as e:
        print(f"⚠️ 检查锁文件时出错: {e}，假设无锁")
        return False


def acquire_lock():
    """获取锁"""
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))


def release_lock():
    """释放锁"""
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except:
            pass


def is_daytime():
    """检查是否在运行时段内 - 无限制，全天运行"""
    return True


def wait_until_daytime():
    """等待直到运行时段 - 无限制，直接返回"""
    return


def load_tracked_articles():
    """加载已处理文章记录"""
    if os.path.exists(TRACKED_FILE):
        try:
            with open(TRACKED_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return []


def save_tracked_articles(articles):
    """保存已处理文章记录"""
    with open(TRACKED_FILE, 'w', encoding='utf-8') as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)


def run_full_pipeline(articles):
    """
    运行完整流水线

    流程步骤：
    1. tool_fetch_news - 抓取文章（如果 articles 为空）
    2. tool_translate_all - 翻译所有文章
    3. tool_notebooklm_summary_all - NotebookLM 生成摘要和播客
    4. tool_analyze_individual - Gemini 分析并存档
    5. tool_filter_decision - 筛选决策
    6. tool_generate_final - 生成最终成品
    7. tool_merge_summaries - 合并所有摘要为汇总文档
    8. tool_publish_to_wechat - 发布到微信（可选）

    参数:
        articles: 预先抓取的文章列表，如果为空则调用 tool_fetch_news
    """
    from src.tools import (
        tool_fetch_news, tool_translate_all, tool_notebooklm_summary_all,
        tool_analyze_individual, tool_filter_decision, tool_generate_final,
        tool_merge_summaries, tool_publish_to_wechat, GLOBAL_DB
    )

    print("\n" + "="*60)
    print("🚀 开始运行完整流水线")
    print("="*60)

    # Step 1: 抓取文章
    if articles:
        # 使用传入的文章，手动填充 GLOBAL_DB
        print(f"\n📥 使用预抓取的 {len(articles)} 篇文章...")
        from src.tools import GLOBAL_DB
        GLOBAL_DB.clear()
        for idx, text in enumerate(articles):
            GLOBAL_DB.append({
                "id": idx,
                "raw_text": text,
                "cn_text": "",
                "notebooklm_summary": "",
                "notebooklm_podcast_path": "",
                "analysis": {},
                "status": "pending"
            })
        print(f"✅ 已加载 {len(GLOBAL_DB)} 篇文章到处理队列")
    else:
        print("\n📥 Step 1: 抓取文章...")
        result = tool_fetch_news()
        print(f"  {result}")
        if "错误" in result or "失败" in result:
            print("❌ 抓取失败，流水线终止")
            return

    # Step 2: 翻译
    print("\n📝 Step 2: 翻译文章...")
    result = tool_translate_all()
    print(f"  {result}")

    # Step 3: NotebookLM 摘要和播客
    print("\n🎙️ Step 3: NotebookLM 生成摘要和播客...")
    result = tool_notebooklm_summary_all()
    print(f"  {result}")

    # Step 4: Gemini 分析
    print("\n🔍 Step 4: Gemini 分析并存档...")
    result = tool_analyze_individual()
    print(f"  {result}")

    # Step 5: 筛选决策
    print("\n🎯 Step 5: 筛选决策...")
    result = tool_filter_decision()
    print(f"  {result}")

    # 检查是否有通过筛选的文章
    if "FILTERED_OUT" in result:
        print("⚠️ 没有文章通过筛选，跳过后续步骤")
        # 仍然生成摘要汇总
        print("\n📋 Step 7: 生成摘要汇总...")
        result = tool_merge_summaries()
        print(f"  {result}")
        return

    # Step 6: 生成最终成品
    print("\n✨ Step 6: 生成最终成品...")
    result = tool_generate_final()
    print(f"  {result}")

    # 发送邮件通知
    if EMAIL_NOTIFY_AVAILABLE:
        try:
            send_publish_notification(
                article_title="Agent 流水线完成",
                source="Agent Main",
                saved_path=None,
                wechat_published=False
            )
        except Exception as e:
            print(f"  ⚠️ 邮件通知失败: {e}")

    # Step 7: 合并摘要
    print("\n📋 Step 7: 生成摘要汇总...")
    result = tool_merge_summaries()
    print(f"  {result}")

    # Step 8: 发布到微信（可选，需要人工确认）
    # 注意：自动发布可能需要扫码，建议手动执行
    # print("\n📤 Step 8: 发布到微信...")
    # result = tool_publish_to_wechat()
    # print(f"  {result}")

    print("\n" + "="*60)
    print("✅ 流水线执行完成！")
    print("="*60)
    print("\n💡 提示：如需发布到微信，请手动运行：")
    print("   python -c \"from src.tools import tool_publish_to_wechat; tool_publish_to_wechat()\"")
    print("   或使用：python publish_to_wechat.py <markdown_file>")


def stage_1_translate_all(checkpoint):
    """Stage 1: 翻译所有未完成的文章"""
    from src import translator
    from src.tools import _save_md_and_docx, OUTPUT_ROOT

    pending = checkpoint.get_pending_for_stage(1)
    if not pending:
        print("  ✅ Stage 1: 所有文章已翻译完成")
        return

    print(f"\n📝 Stage 1: 翻译 {len(pending)} 篇文章...")
    translate_dir = os.path.join(OUTPUT_ROOT, "translated")
    os.makedirs(translate_dir, exist_ok=True)

    for article_id in pending:
        article = checkpoint.get_article(article_id)
        if not article:
            continue

        preview = article['raw_text'].replace('\n', ' ')[:50]
        print(f"  - 翻译第 {article_id+1} 篇: {preview}...")

        try:
            cn_text = translator.translate_article(article['raw_text'])
            if cn_text:
                checkpoint.update_article(article_id, cn_text=cn_text)
                checkpoint.mark_stage_completed(1, article_id)

                # 生成文件名：日期_文章标题
                date_str = datetime.now().strftime("%Y%m%d")
                title = generate_attractive_title(cn_text[:1000])
                if not title:
                    title = f"文章_{article_id}"
                # 清理标题中的非法字符
                safe_title = re.sub(r'[\\/*?:"<>|]', '', title).strip()
                # 限制标题长度
                if len(safe_title) > 50:
                    safe_title = safe_title[:50]
                filename_base = f"{date_str}_{safe_title}"
                _save_md_and_docx(cn_text, translate_dir, filename_base)
                print(f"    ✅ 翻译完成: {filename_base}.md")
            else:
                checkpoint.log_error(1, article_id, "翻译结果为空")
        except Exception as e:
            checkpoint.log_error(1, article_id, str(e))
            print(f"    ❌ 翻译失败: {e}")


async def stage_2_summarize_all(checkpoint):
    """Stage 2: 使用 NotebookLM 生成摘要"""
    try:
        from src.notebook_tool import NotebookSkill
    except ImportError:
        print("  ⚠️ NotebookSkill 不可用，跳过 Stage 2")
        # 标记所有已翻译的文章为 stage 2 完成（跳过）
        for article_id in checkpoint.stage_1_completed:
            if not checkpoint.is_stage_completed(2, article_id):
                checkpoint.mark_stage_completed(2, article_id)
        return

    pending = checkpoint.get_pending_for_stage(2)
    if not pending:
        print("  ✅ Stage 2: 所有文章已生成摘要")
        return

    print(f"\n🎙️ Stage 2: 为 {len(pending)} 篇文章生成摘要...")

    for article_id in pending:
        article = checkpoint.get_article(article_id)
        if not article or not article.get('cn_text'):
            continue

        print(f"  - 处理第 {article_id+1} 篇...")

        try:
            async with NotebookSkill() as skill:
                # 1. 创建笔记本
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                nb_id = await skill.create_notebook(f"Article_{article_id}_{timestamp}")

                # 2. 上传文章内容
                await skill.upload_text(nb_id, article['cn_text'], title=f"Article_{article_id}")

                # 3. 提问获取摘要
                summary = await skill.ask_question(nb_id, "请为这篇文章生成一个详细的中文摘要，包括主要观点、关键信息和结论。")

                if summary:
                    checkpoint.update_article(article_id, notebooklm_summary=summary)
                    checkpoint.mark_stage_completed(2, article_id)
                    print(f"    ✅ 摘要生成完成")
                else:
                    checkpoint.log_error(2, article_id, "摘要结果为空")
        except Exception as e:
            checkpoint.log_error(2, article_id, str(e))
            print(f"    ❌ 摘要生成失败: {e}")


def stage_3_analyze_summaries(checkpoint):
    """Stage 3: 使用 Gemini 分析文章"""
    pending = checkpoint.get_pending_for_stage(3)
    if not pending:
        print("  ✅ Stage 3: 所有文章已分析完成")
        return

    print(f"\n🔍 Stage 3: 分析 {len(pending)} 篇文章...")

    for article_id in pending:
        article = checkpoint.get_article(article_id)
        if not article:
            continue

        print(f"  - 分析第 {article_id+1} 篇...")

        try:
            cn_text = article.get('cn_text', '')
            summary = article.get('notebooklm_summary', '')
            content_to_analyze = summary if summary else cn_text

            if not content_to_analyze:
                checkpoint.log_error(3, article_id, "无内容可分析")
                continue

            analysis = analyze_single_article_content(content_to_analyze)
            if analysis:
                checkpoint.update_article(article_id, analysis=analysis)
                checkpoint.mark_stage_completed(3, article_id)
                print(f"    ✅ 分析完成")
            else:
                checkpoint.log_error(3, article_id, "分析结果为空")
        except Exception as e:
            checkpoint.log_error(3, article_id, str(e))
            print(f"    ❌ 分析失败: {e}")


def stage_4_filter_and_publish(checkpoint):
    """Stage 4: 筛选并发布文章"""
    from src.tools import _save_md_and_docx, OUTPUT_ROOT

    print("\n🎯 Stage 4: 筛选并发布...")

    # 收集所有已分析的文章
    analyzed_articles = []
    for article_id in checkpoint.stage_3_completed:
        article = checkpoint.get_article(article_id)
        if article and article.get('analysis'):
            analyzed_articles.append(article)

    if not analyzed_articles:
        print("  ⚠️ 没有已分析的文章可供筛选")
        return

    print(f"  - 共 {len(analyzed_articles)} 篇文章待筛选...")

    try:
        # 使用 Gemini 决策最佳文章
        best_ids = decide_best_articles(analyzed_articles)

        if not best_ids:
            print("  ⚠️ 没有文章通过筛选")
            return

        print(f"  ✅ 筛选出 {len(best_ids)} 篇文章")

        # 生成最终成品
        final_dir = os.path.join(OUTPUT_ROOT, "final")
        os.makedirs(final_dir, exist_ok=True)

        for article_id in best_ids:
            article = checkpoint.get_article(article_id)
            if not article:
                continue

            cn_text = article.get('cn_text', '')
            if cn_text:
                # 生成标题
                title = generate_attractive_title(cn_text[:1000])
                if not title:
                    title = f"文章_{article_id}"

                # 生成文件名：日期_文章标题
                date_str = datetime.now().strftime("%Y%m%d")
                # 清理标题中的非法字符
                safe_title = re.sub(r'[\\\\/*?:"<>|]', '', title).strip()
                # 限制标题长度
                if len(safe_title) > 50:
                    safe_title = safe_title[:50]
                filename_base = f"{date_str}_{safe_title}"

                final_content = f"# {title}\n\n{cn_text}"
                _save_md_and_docx(final_content, final_dir, filename_base)
                print(f"    ✅ 已生成: {filename_base}.md")

        # 清理 checkpoint
        checkpoint.clear()
        print("  ✅ Pipeline 完成，checkpoint 已清理")

    except Exception as e:
        print(f"  ❌ 筛选发布失败: {e}")


def run_staged_pipeline(articles):
    """运行分阶段流水线（带 checkpoint）"""
    checkpoint = PipelineCheckpoint()

    # 尝试加载已有 checkpoint
    if checkpoint.load():
        print("  📂 从 checkpoint 恢复...")
    elif articles:
        checkpoint.start_new_run(articles)
    else:
        print("  ⚠️ 无文章且无 checkpoint，退出")
        return

    # 运行各阶段
    stage_1_translate_all(checkpoint)
    asyncio.run(stage_2_summarize_all(checkpoint))
    stage_3_analyze_summaries(checkpoint)
    stage_4_filter_and_publish(checkpoint)

def has_incomplete_checkpoint():
    """检查是否有未完成的 checkpoint 需要恢复"""
    if not os.path.exists(CHECKPOINT_FILE):
        return False
    try:
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        stage_1 = data.get("stage_1_completed", [])
        stage_2 = data.get("stage_2_completed", [])
        stage_3 = data.get("stage_3_completed", [])
        total = len(data.get("articles", []))
        # 如果有任何 stage 没完成，返回 True
        return len(stage_1) < total or len(stage_2) < total or len(stage_3) < total
    except:
        return False

def resume_from_checkpoint():
    """从 checkpoint 恢复并继续处理"""
    print("\n" + "="*60)
    print("📂 发现未完成的 checkpoint，尝试恢复...")
    print("="*60)
    
    checkpoint = PipelineCheckpoint()
    if not checkpoint.load():
        print("  ⚠️ 无法加载 checkpoint")
        return False
    
    total = len(checkpoint.articles)
    s1 = len(checkpoint.stage_1_completed)
    s2 = len(checkpoint.stage_2_completed)
    s3 = len(checkpoint.stage_3_completed)
    
    print(f"  📊 进度: 翻译={s1}/{total}, 总结={s2}/{total}, 分析={s3}/{total}")
    
    # 直接调用 run_staged_pipeline，它会检测 checkpoint 并恢复
    try:
        run_staged_pipeline([])  # 传空列表，因为 checkpoint 已经有所需的文章
        print("  ✅ Checkpoint 处理完成")
        return True
    except Exception as e:
        print(f"  ❌ 恢复失败: {e}")
        return False


def monitor():
    """自动监控循环"""
    print("="*60)
    print("🔔 网站自动监控已启动")
    print(f"⏰ 检查间隔: 每{CHECK_INTERVAL//3600}小时")
    print("📡 运行时间: 全天24小时")
    print("="*60)

    last_run_time = None  # Track last run time to handle sleep/wake

    while True:
        try:
            if is_locked():
                # 即使有锁，也检查是否有未完成的 checkpoint 需要恢复
                if has_incomplete_checkpoint():
                    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ⚠️ 检测到未完成的 checkpoint，尝试恢复...")
                    if resume_from_checkpoint():
                        last_run_time = None
                        continue
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ⏳ 上一次运行尚未完成，跳过本次检查...")
                time.sleep(60)
                continue

            if not is_daytime():
                wait_until_daytime()
                last_run_time = None  # Reset after overnight wait
                continue

            # Check if enough time has passed since last run (handles sleep/wake)
            now = datetime.now()
            if last_run_time is not None:
                elapsed = (now - last_run_time).total_seconds()
                if elapsed < CHECK_INTERVAL:
                    # Sleep for remaining time, but check every 60s to detect wake from sleep
                    time.sleep(min(60, CHECK_INTERVAL - elapsed))
                    continue

            acquire_lock()

            # 再次检查 checkpoint（获取锁后）
            if has_incomplete_checkpoint():
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 📂 检测到未完成的 checkpoint，继续处理...")
                if resume_from_checkpoint():
                    release_lock()
                    last_run_time = None
                    continue

            print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 🔍 检查网站更新...")

            tracked = load_tracked_articles()
            tracked_hashes = set(a.get("content_hash") for a in tracked if a.get("content_hash"))

            articles = fetch_latest_articles()

            if not articles:
                print("⏳ 暂未发现新文章")
            else:
                new_articles = []
                for article in articles:
                    # 使用 hashlib 生成稳定的哈希值（跨进程一致）
                    article_hash = hashlib.md5(article[:500].encode('utf-8')).hexdigest()
                    if article_hash not in tracked_hashes:
                        new_articles.append(article)
                        tracked.append({
                            "url": f"article_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                            "content_hash": article_hash,
                            "processed_at": datetime.now().strftime("%Y%m%d_%H%M%S")
                        })

                if not new_articles:
                    print("⏳ 没有发现新文章（已全部处理过）")
                else:
                    print(f"\n发现 {len(new_articles)} 篇新文章，准备自动处理...")
                    run_full_pipeline(new_articles)
                    save_tracked_articles(tracked)

            # Update last run time after successful check
            last_run_time = datetime.now()
            print(f"\n💤 等待{CHECK_INTERVAL//3600}小时后再次检查...")

            release_lock()

        except KeyboardInterrupt:
            print("\n\n🛑 用户停止监控")
            release_lock()
            break
        except Exception as e:
            print(f"\n❌ 错误: {e}")
            print("  💡 Checkpoint preserves progress - retrying in 5 minutes...")
            release_lock()
            time.sleep(300)  # 5-minute retry instead of overnight wait

def main():
    print("\n" + "="*50)
    print("🚀 微信公众号主编 Agent 已启动")
    print("="*50 + "\n")

    try:
        monitor()  # 进入每2小时循环的自动监控模式
    except KeyboardInterrupt:
        print("\n\n🛑 用户手动停止了程序。")
    except Exception as e:
        print(f"\n❌ 程序发生未知错误: {e}")

if __name__ == "__main__":
    main()
