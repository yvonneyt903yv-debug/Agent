import json
import os
import re
import asyncio
import subprocess
import markdown
import requests
from datetime import datetime
from src.gemini_brain import analyze_single_article_content, decide_best_articles, generate_attractive_title

# 导入真实的功能模块
from src import crawler
from src import translator
from src import reviewer

# 动态获取项目根目录 (假设 tools.py 在 MyAgent/src/ 目录下)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_ROOT = os.path.join(PROJECT_ROOT, 'output')

# 导入 NotebookLM 工具 - 使用标准导入方式
try:
    from src.notebook_tool import NotebookSkill
    print("✅ NotebookSkill 导入成功")
except ImportError:
    try:
        # 如果上面失败，尝试直接导入
        from notebook_tool import NotebookSkill
        print("✅ NotebookSkill 导入成功")
    except ImportError:
        NotebookSkill = None
        print(f"⚠️ 警告: 无法导入 NotebookSkill，NotebookLM 功能将不可用")

# === 全局数据暂存区 ===
GLOBAL_DB = []

# ================= 辅助函数：Unsplash 图库 =================

def search_and_download_cover_image(keywords: str, save_dir: str, filename: str) -> str:
    """
    从 Unsplash 搜索并下载封面图

    参数:
        keywords: 搜索关键词
        save_dir: 保存目录
        filename: 文件名（不含扩展名）

    返回:
        图片路径，如果失败返回 None
    """
    # 从环境变量获取 Unsplash Access Key
    access_key = os.getenv("UNSPLASH_ACCESS_KEY")

    if not access_key:
        print("    ⚠️ 未配置 UNSPLASH_ACCESS_KEY，跳过封面图下载")
        return None

    try:
        # 搜索图片
        url = "https://api.unsplash.com/search/photos"
        params = {
            "query": keywords,
            "per_page": 1,
            "orientation": "landscape",  # 横版图片
            "content_filter": "high"  # 高质量内容
        }
        headers = {"Authorization": f"Client-ID {access_key}"}

        print(f"    🔍 正在 Unsplash 搜索关键词: {keywords}")
        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code != 200:
            print(f"    ⚠️ Unsplash API 请求失败: {response.status_code}")
            return None

        data = response.json()

        if not data.get("results"):
            print(f"    ⚠️ 未找到相关图片")
            return None

        # 获取第一张图片
        photo = data["results"][0]
        image_url = photo["urls"]["regular"]  # 1080px 宽度
        photographer = photo["user"]["name"]
        photo_link = photo["links"]["html"]

        print(f"    📸 找到图片，摄影师: {photographer}")

        # 下载图片
        img_response = requests.get(image_url, timeout=30)
        if img_response.status_code != 200:
            print(f"    ⚠️ 图片下载失败")
            return None

        # 保存图片
        os.makedirs(save_dir, exist_ok=True)
        img_path = os.path.join(save_dir, f"{filename}_cover.jpg")

        with open(img_path, 'wb') as f:
            f.write(img_response.content)

        print(f"    ✅ 封面图已保存: {img_path}")
        print(f"    📷 图片来源: {photo_link}")

        # 触发 Unsplash 下载统计（API 要求）
        download_endpoint = photo["links"]["download_location"]
        requests.get(download_endpoint, headers=headers, timeout=5)

        return img_path

    except requests.exceptions.Timeout:
        print(f"    ⚠️ Unsplash API 请求超时")
        return None
    except Exception as e:
        print(f"    ⚠️ 封面图下载失败: {e}")
        return None

# ================= 辅助函数：MD 转 Word & 保存 =================

def _convert_to_html_with_style(markdown_text):
    """
    将Markdown文本转换为带有自定义CSS样式的HTML
    """
    css_style = """
<style>
/*自定义样式，实时生效*/
body { padding: 10px; font-family: ptima-Regular; word-break: break-all; }
#nice p { margin-top: 5px; margin-bottom: 5px; line-height: 26px; word-spacing: 3px; letter-spacing: 3px; text-align: left; color: #3e3e3e; font-size: 17px; text-indent: 0em; }
#nice h1 { color: rgb(89,89,89); }
#nice h2 { border-bottom: 2px solid rgb(89,89,89); margin-bottom: 5px; color: rgb(89,89,89); }
#nice h2 .content { font-size: 22px; display: inline-block; border-bottom: 2px solid rgb(89,89,89); }
#nice blockquote { font-style: normal; padding: 10px; position: relative; line-height: 1.8; text-indent: 0; border: none; color: #888; }
#nice blockquote:before { content: "\\""; display: inline; color: #555555; font-size: 4em; font-family: Arial, serif; line-height: 1em; font-weight: 700; }
#nice a { color: rgb(71, 193, 168); border-bottom: 1px solid rgb(71, 193, 168); }
#nice strong { color: rgb(89, 89, 89); }
#nice em { color: rgb(71, 193, 168); }
#nice p code, #nice li code { color: rgb(71, 193, 168); }
#nice table tr th, #nice table tr td { font-size: 16px; border: 1px solid #ccc; padding: 5px 10px; }
#nice .footnotes-sep:before { content: "参考资料"; }
#nice .footnote-item p { color: rgb(71, 193, 168); }
</style>
"""
    html_body = markdown.markdown(markdown_text, extensions=['tables', 'fenced_code', 'sane_lists'])
    full_html = f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n{css_style}</head>\n<body>\n<div id="nice">{html_body}</div>\n</body>\n</html>'
    return f'<div id="nice">{html_body}</div>', full_html

def _save_md_and_docx(content, folder, base_filename):
    """
    辅助函数：同时保存 Markdown、HTML 和 Word 文件
    """
    # 确保保存路径是绝对路径，并且位于 OUTPUT_ROOT 下
    if not os.path.isabs(folder):
        folder = os.path.join(OUTPUT_ROOT, folder)
    
    os.makedirs(folder, exist_ok=True)
    
    # 1. 保存 Markdown
    md_path = os.path.join(folder, f"{base_filename}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    # 2. 转换为 HTML（带样式）
    html_snippet, full_html = _convert_to_html_with_style(content)
    
    # 3. 保存 HTML
    html_path = os.path.join(folder, f"{base_filename}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(full_html)
    
    # 4. 使用 pandoc 将 HTML 转换为 Word
    docx_path = os.path.join(folder, f"{base_filename}.docx")
    try:
        command = ['/opt/homebrew/bin/pandoc', html_path, '-f', 'html', '-t', 'docx', '-o', docx_path]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        print(f"    ✅ Word 文档已生成: {docx_path}")
    except FileNotFoundError:
        print("    ⚠️ 警告：Pandoc未安装，无法生成Word文档。HTML文件已保存。")
        docx_path = None
    except subprocess.CalledProcessError as e:
        print(f"    ⚠️ 警告：Pandoc转换失败 (错误代码: {e.returncode})。")
        docx_path = None
    
    return md_path, docx_path

# ================= 工具定义 =================

def tool_fetch_news():
    """步骤1：抓取"""
    print("🚀 [Step 1] 正在调用 Selenium 爬虫抓取外网文章...")
    
    try:
        real_articles = crawler.fetch_latest_articles()
    except Exception as e:
        return f"❌ 抓取失败: {str(e)}"

    if not real_articles:
        return "⚠️ 警告：爬虫没有抓取到任何文章。"

    global GLOBAL_DB
    GLOBAL_DB = [] 
    
    for idx, text in enumerate(real_articles):
        GLOBAL_DB.append({
            "id": idx,
            "raw_text": text,
            "cn_text": "",
            "notebooklm_summary": "", # 新增字段
            "notebooklm_podcast_path": "", # 新增字段
            "analysis": {},
            "status": "pending"
        })
    
    return f"✅ 成功抓取 {len(GLOBAL_DB)} 篇真实文章。请继续。"

def tool_translate_all():
    """步骤2：批量翻译（带超时保护）"""
    import concurrent.futures
    import signal
    
    if not GLOBAL_DB: 
        return "错误：无数据。"
    
    # 配置超时
    SINGLE_ARTICLE_TIMEOUT = 3600  # 单篇文章翻译超时：60分钟（增加以处理长文章）
    TOTAL_STEP_TIMEOUT = None      # 整体步骤超时：不限制

    print(f"🚀 [Step 2] 正在批量翻译 {len(GLOBAL_DB)} 篇文章...")
    print(f"   ⏱️  单篇超时: {SINGLE_ARTICLE_TIMEOUT//60}分钟 | 整体超时: 不限制")
    
    # 翻译结果保存目录
    translate_dir = os.path.join(OUTPUT_ROOT, "translated")
    os.makedirs(translate_dir, exist_ok=True)
    
    success_count = 0
    failed_count = 0
    start_time = datetime.now()
    
    def translate_single_article(item):
        """翻译单篇文章（带独立错误处理）"""
        nonlocal success_count, failed_count
        
        preview = item['raw_text'].replace('\n', ' ')[:50]
        article_id = item['id']
        print(f"  - 翻译第 {article_id+1} 篇: {preview}...")
        
        try:
            # 使用线程执行翻译，实现超时控制
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(translator.translate_article, item['raw_text'])
                try:
                    translation_result = future.result(timeout=SINGLE_ARTICLE_TIMEOUT)
                    
                    if translation_result:
                        item["cn_text"] = translation_result
                        success_count += 1
                        
                        # 实时保存翻译结果
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename_base = f"TRANSLATED_{timestamp}_ID{article_id}_preview"
                        try:
                            _save_md_and_docx(translation_result, translate_dir, filename_base)
                            print(f"    ✅ 翻译完成并保存: {filename_base}.md")
                        except Exception as save_err:
                            print(f"    ⚠️ 保存翻译结果失败: {save_err}")
                        
                        return True
                    else:
                        item["cn_text"] = "（翻译结果为空）"
                        failed_count += 1
                        return False
                        
                except concurrent.futures.TimeoutError:
                    print(f"    ❌ 翻译超时（超过{SINGLE_ARTICLE_TIMEOUT//60}分钟）")
                    item["cn_text"] = f"（翻译超时: 超过{SINGLE_ARTICLE_TIMEOUT//60}分钟）"
                    failed_count += 1
                    
                    # 保存超时记录
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename_base = f"TRANSLATED_{timestamp}_ID{article_id}_TIMEOUT"
                    try:
                        _save_md_and_docx(f"翻译超时: 超过{SINGLE_ARTICLE_TIMEOUT//60}分钟\n\n原文前1000字符:\n{item['raw_text'][:1000]}", 
                                        translate_dir, filename_base)
                    except:
                        pass
                    return False
                    
        except Exception as e:
            error_msg = str(e)
            print(f"    ❌ 翻译失败: {error_msg[:100]}")
            item["cn_text"] = f"（翻译失败: {error_msg[:200]}）"
            failed_count += 1
            
            # 保存失败记录
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename_base = f"TRANSLATED_{timestamp}_ID{article_id}_FAILED"
            try:
                _save_md_and_docx(f"翻译失败: {error_msg}\n\n原文前1000字符:\n{item['raw_text'][:1000]}", 
                                translate_dir, filename_base)
            except:
                pass
            return False
    
    # 处理每篇文章
    for i, item in enumerate(GLOBAL_DB):
        # 翻译当前文章
        translate_single_article(item)
        
        # 显示进度
        progress = (i + 1) / len(GLOBAL_DB) * 100
        print(f"   📊 进度: {i+1}/{len(GLOBAL_DB)} ({progress:.1f}%) | 成功: {success_count} | 失败: {failed_count}")
    
    total_time = (datetime.now() - start_time).total_seconds()
    print(f"\n⏱️  翻译步骤总耗时: {total_time//60:.1f} 分钟")
    
    if success_count == 0 and len(GLOBAL_DB) > 0:
        return f"⚠️ 翻译完成，但全部失败 ({failed_count}/{len(GLOBAL_DB)} 篇)。请检查网络和API配置。"
    elif failed_count > 0:
        return f"✅ 翻译完成: {success_count} 篇成功, {failed_count} 篇失败。请继续。"
    else:
        return f"✅ 翻译完成 {success_count}/{len(GLOBAL_DB)} 篇。请继续。"

def tool_notebooklm_summary_all():
    """
    步骤3：使用 NotebookLM 对【所有】翻译好的文章进行总结要点（并生成播客）
    这是筛选前的准备工作。
    """
    if NotebookSkill is None:
        return "⚠️ NotebookLM 功能不可用：notebook_tool.py 未找到。"
    
    if not GLOBAL_DB:
        return "错误：无数据。"

    print(f"\n🚀 [Step 3] 使用 NotebookLM 对所有文章进行总结和播客生成...")
    
    results = []
    
    async def process_article(item):
        """异步处理单篇文章"""
        # 跳过翻译失败的
        if not item["cn_text"] or "翻译失败" in item["cn_text"]:
            return f"⚠️ 文章 ID{item['id']} 翻译失败，跳过 NotebookLM。"

        try:
            async with NotebookSkill() as skill: # 使用上下文管理器
                # 1. 创建笔记本
                title = f"文章摘要_{item['id']}_{datetime.now().strftime('%Y%m%d')}"
                nb_id = await skill.create_notebook(title)
                print(f"    📝 文章 ID{item['id']} -> 笔记本 ID: {nb_id}")
                
                # 2. 上传文章内容
                await skill.upload_text(nb_id, item['cn_text'], title=title)
                
                # 3. 请求总结要点 (这部分总结将用于后续筛选)
                summary_question = "请总结这篇文章的核心要点，包括被访者背景（如果有）、主要观点和结论。请用中文回答。"
                summary = await skill.ask_question(nb_id, summary_question)
                
                # 4. 生成播客（即使筛选不通过，先生成了也无妨，或者你可以移到筛选后）
                # 这里为了满足“先总结”的要求，我们先做。
                podcast_instructions = "请生成一个生动有趣的中文播客，用中文讲述这篇文章的核心内容"
                # 保存到 output/podcasts 目录下
                podcast_dir = os.path.join(OUTPUT_ROOT, "podcasts")
                os.makedirs(podcast_dir, exist_ok=True)
                
                # 注意：这里需要修改 notebook_tool.py 的 generate_podcast 支持传入 output_dir 
                # 或者我们假设 notebook_tool.py 内部已经处理好了路径，或者我们在这里移动文件
                # 暂时假设 notebook_tool.py 会返回文件路径
                podcast_path = await skill.generate_podcast(nb_id, instructions=podcast_instructions, timeout=600)
                
                # 5. 保存结果
                item['notebooklm_summary'] = summary
                item['notebooklm_podcast_path'] = podcast_path
                item['notebook_id'] = nb_id
                
                if podcast_path:
                    # 移动播客文件到指定目录 (如果它不在那里)
                    if os.path.exists(podcast_path) and not podcast_path.startswith(podcast_dir):
                        import shutil
                        new_path = os.path.join(podcast_dir, os.path.basename(podcast_path))
                        shutil.move(podcast_path, new_path)
                        item['notebooklm_podcast_path'] = new_path
                        return f"✅ 文章 ID{item['id']} NotebookLM 处理完成，播客已保存。"
                    return f"✅ 文章 ID{item['id']} NotebookLM 处理完成，播客已保存。"
                else:
                    return f"⚠️ 文章 ID{item['id']} 总结完成，但播客生成失败。"
            
        except Exception as e:
            return f"❌ 文章 ID{item['id']} NotebookLM 处理失败: {str(e)}"
    
    # 处理所有文章
    async def process_all():
        tasks = [process_article(item) for item in GLOBAL_DB]
        return await asyncio.gather(*tasks)
    
    # 运行异步任务
    try:
        async_results = asyncio.run(process_all())
        results.extend(async_results)
    except Exception as e:
        return f"❌ NotebookLM 批量处理异常: {str(e)}"
    
    return "\n".join(results)

def tool_analyze_individual():
    """
    步骤4：Gemini 分析（基于 NotebookLM 的总结进行增强分析）+ 全量存档
    """
    if not GLOBAL_DB: return "错误：无数据。"
    
    # 存档目录：使用绝对路径
    archive_dir = os.path.join(OUTPUT_ROOT, "all_archives")
    
    print("🚀 [Step 4] 正在让 Gemini 结合 NotebookLM 的总结进行分析并存档...")
    
    saved_count = 0
    for item in GLOBAL_DB:
        if not item["cn_text"] or "翻译失败" in item["cn_text"]:
            item["analysis"] = {"category": "error", "intro": "翻译失败"}
            continue

        print(f"  - 分析并存档 ID {item['id']} ...")
        
        # 优先使用 NotebookLM 的总结作为输入给 Gemini 分析，如果为空则用原文
        content_to_analyze = item.get('notebooklm_summary', "")
        if not content_to_analyze or len(content_to_analyze) < 50:
             content_to_analyze = item['cn_text']
        else:
             content_to_analyze = f"【NotebookLM 总结】\n{content_to_analyze}\n\n【原文片段】\n{item['cn_text'][:2000]}"

        # 1. 调用 Gemini 分析
        analysis = analyze_single_article_content(content_to_analyze)
        
        if analysis:
            item["analysis"] = analysis
            item["analysis"]["index"] = item["id"]
            
            # 2. 构造存档内容
            archive_content = f"""# [存档] ID{item['id']} - {analysis.get('category', '未知')}

> 存档时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
> 敏感性判断：{analysis.get('is_sensitive', '未知')}
> NotebookLM 播客：{item.get('notebooklm_podcast_path', '无')}

## 【Gemini 结构化分析】
**简介**：{analysis.get('intro', '无')}
**要点**：
{analysis.get('key_points', '无')}

---

## 【NotebookLM 智能总结】
{item.get('notebooklm_summary', '未生成')}

---

## 【中文全译文】
{item['cn_text']}

---

## 【英文原文】
{item['raw_text']}
"""
            # 3. 生成唯一文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = re.sub(r'[\\/*?:"<>|]', "", analysis.get('intro', '未命名')[:10])
            filename_base = f"ARCHIVE_{timestamp}_ID{item['id']}_{safe_title}"
            
            # 4. 保存
            try:
                _save_md_and_docx(archive_content, archive_dir, filename_base)
                saved_count += 1
            except Exception as e:
                print(f"    └── 保存失败: {e}")

        else:
            item["analysis"] = {"category": "unknown", "error": True}
            
    return f"✅ 全量分析与存档完成。{saved_count} 篇文章已存入 '{archive_dir}'。请执行筛选。"

def tool_filter_decision():
    """步骤5：筛选决策"""
    analysis_report_list = [item["analysis"] for item in GLOBAL_DB if "analysis" in item and not item.get("analysis", {}).get("error")]
    
    if not analysis_report_list:
        return "FILTERED_OUT: 没有有效分析报告。"

    print("🚀 [Step 5] 正在提交给主编进行筛选...")
    selected_ids = decide_best_articles(analysis_report_list)
    
    if not selected_ids:
        return "FILTERED_OUT: 没有合适的文章。"
    
    approved_ids = []
    for item in GLOBAL_DB:
        if item["id"] in selected_ids:
            item["status"] = "approved"
            approved_ids.append(item["id"])
        else:
            item["status"] = "rejected"
            
    return f"✅ 筛选完成！选中文章ID：{approved_ids}。请执行生成 (tool_generate_final)。"

def tool_generate_final():
    """
    步骤6：生成成品 (仅针对通过筛选的)
    新增功能：自动生成吸引人的微信公众号标题
    """
    approved_items = [i for i in GLOBAL_DB if i["status"] == "approved"]

    if not approved_items:
        return "错误：没有通过筛选的文章。"

    results = []
    # 最终成品文件夹：使用绝对路径
    final_dir = os.path.join(OUTPUT_ROOT, "final_published")

    for item in approved_items:
        print(f"\n🚀 [Step 6] 正在生成最终成品：文章 ID {item['id']} ...")

        # 1. 准备内容
        # 优先使用 NotebookLM 的总结，如果不够好则结合 Gemini 的分析
        summary_source = item.get('notebooklm_summary', "")
        if not summary_source:
             summary_source = item['analysis'].get('key_points', '暂无')

        # 🆕 2. 生成吸引人的标题（使用Gemini，输入NotebookLM总结）
        print("  - 🎯 正在使用Gemini生成吸引人的微信公众号标题...")
        attractive_title = generate_attractive_title(summary_source)
        print(f"  - ✨ 生成的标题：{attractive_title}")

        # 保存标题到item中，方便后续使用
        item['generated_title'] = attractive_title

        # 🆕 3. 下载封面图（使用Unsplash）
        print("  - 📸 正在下载封面图...")
        # 使用标题前15个字作为搜索关键词
        search_keywords = attractive_title[:15]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title_for_file = re.sub(r'[\\/*?:"<>|]', "", attractive_title)
        if len(safe_title_for_file) > 30:
            safe_title_for_file = safe_title_for_file[:30]
        filename_base = f"PUBLISH_{timestamp}_ID{item['id']}_{safe_title_for_file}"

        cover_image_path = search_and_download_cover_image(
            keywords=search_keywords,
            save_dir=final_dir,
            filename=filename_base
        )

        # 保存封面图路径
        item['cover_image_path'] = cover_image_path if cover_image_path else ""

        # 4. 拼接文章内容（使用生成的标题和封面图）
        # 如果有封面图，添加到文章开头
        cover_image_markdown = ""
        if cover_image_path:
            cover_image_markdown = f"![封面图]({os.path.basename(cover_image_path)})\n\n"

        draft_content = f"""{cover_image_markdown}# {attractive_title}

## 【被访者简介】
{item['analysis'].get('intro', '暂无')}

## 【核心要点】 (基于 NotebookLM & Gemini 分析)
{summary_source}

## 【相关播客】
[点击收听生成的中文播客]({os.path.basename(item.get('notebooklm_podcast_path', ''))})

## 【正文实录】
{item['cn_text']}
"""

        # 4. 审校
        print("  - 调用 Reviewer 审校...")
        try:
            final_content = reviewer.review_article(draft_content)
        except Exception as e:
            print(f"  ❌ 审校出错: {e}")
            final_content = draft_content

        # 5. 保存 (MD + DOCX) - 使用生成的标题作为文件名

        try:
            paths = _save_md_and_docx(final_content, final_dir, filename_base)
            results.append(f"✅ ID{item['id']} 标题：《{attractive_title}》已发布: {paths}")
        except Exception as e:
            results.append(f"❌ ID{item['id']} 保存失败: {e}")

    return "\n".join(results)

def tool_publish_to_wechat():
    """
    步骤7：发布到微信公众号（使用 baoyu-post-to-wechat）
    """
    approved_items = [i for i in GLOBAL_DB if i["status"] == "approved"]

    if not approved_items:
        return "错误：没有通过筛选的文章。"

    results = []
    final_dir = os.path.join(OUTPUT_ROOT, "final_published")

    print("\n🚀 [Step 7] 正在发布到微信公众号...")

    for item in approved_items:
        print(f"\n📤 正在发布文章 ID {item['id']}...")

        # 查找最新生成的 Markdown 文件
        timestamp = datetime.now().strftime("%Y%m%d")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", item.get('generated_title', 'article'))[:30]

        # 查找匹配的文件
        import glob
        pattern = os.path.join(final_dir, f"PUBLISH_{timestamp}*ID{item['id']}*.md")
        md_files = glob.glob(pattern)

        if not md_files:
            results.append(f"❌ ID{item['id']} 未找到 Markdown 文件")
            continue

        md_file = md_files[0]  # 使用第一个匹配的文件
        print(f"  - 📄 找到文章文件: {os.path.basename(md_file)}")

        # 调用 baoyu-post-to-wechat
        baoyu_script = os.path.join(
            PROJECT_ROOT,
            "baoyu-skills/skills/baoyu-post-to-wechat/scripts/wechat-article.ts"
        )

        if not os.path.exists(baoyu_script):
            results.append(f"❌ 未找到 baoyu-post-to-wechat 脚本: {baoyu_script}")
            continue

        # 构建命令
        cmd = [
            "npx", "-y", "bun",
            baoyu_script,
            "--markdown", md_file,
            "--theme", "grace"  # 使用 grace 主题（优雅风格）
        ]

        print(f"  - 🌐 正在启动浏览器自动化...")
        print(f"  - ⚠️  请确保：")
        print(f"    1. Chrome 浏览器已安装")
        print(f"    2. 准备好微信扫码登录")
        print(f"    3. 不要操作浏览器窗口")

        try:
            # 执行命令
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
                cwd=os.path.dirname(baoyu_script)
            )

            if result.returncode == 0:
                results.append(f"✅ ID{item['id']} 《{item.get('generated_title', '文章')}》已发布到微信公众号")
                print(f"  - ✅ 发布成功！")
            else:
                error_msg = result.stderr if result.stderr else result.stdout
                results.append(f"❌ ID{item['id']} 发布失败: {error_msg[:200]}")
                print(f"  - ❌ 发布失败: {error_msg[:200]}")

        except subprocess.TimeoutExpired:
            results.append(f"⚠️ ID{item['id']} 发布超时（可能需要手动扫码）")
            print(f"  - ⚠️ 发布超时，请检查浏览器窗口")
        except FileNotFoundError:
            results.append(f"❌ 未安装 Node.js 或 Bun，无法执行发布")
            print(f"  - ❌ 请先安装 Node.js: https://nodejs.org/")
            break
        except Exception as e:
            results.append(f"❌ ID{item['id']} 发布异常: {str(e)}")
            print(f"  - ❌ 发布异常: {e}")

    return "\n".join(results)


def tool_merge_summaries():
    """
    步骤8：合并所有文章摘要为一个汇总文档

    功能：
    - 将所有文章的 NotebookLM 摘要合并成一个文档
    - 包含每篇文章的标题、摘要、分析结果
    - 保存到 output/daily_summary/ 目录
    """
    if not GLOBAL_DB:
        return "错误：无数据。"

    print("\n🚀 [Step 8] 正在合并所有文章摘要...")

    # 汇总目录
    summary_dir = os.path.join(OUTPUT_ROOT, "daily_summary")
    os.makedirs(summary_dir, exist_ok=True)

    # 生成汇总内容
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y%m%d")

    summary_content = f"""# 每日文章摘要汇总

> 生成时间：{timestamp}
> 文章总数：{len(GLOBAL_DB)} 篇

---

"""

    # 统计信息
    approved_count = len([i for i in GLOBAL_DB if i.get("status") == "approved"])
    rejected_count = len([i for i in GLOBAL_DB if i.get("status") == "rejected"])

    summary_content += f"""## 📊 统计概览

- 总文章数：{len(GLOBAL_DB)}
- 通过筛选：{approved_count}
- 未通过筛选：{rejected_count}

---

## 📝 文章摘要列表

"""

    # 遍历所有文章
    for item in GLOBAL_DB:
        article_id = item.get("id", "?")
        status = item.get("status", "pending")
        status_emoji = "✅" if status == "approved" else "❌" if status == "rejected" else "⏳"

        # 获取分析结果
        analysis = item.get("analysis", {})
        intro = analysis.get("intro", "暂无简介")
        category = analysis.get("category", "未分类")
        is_sensitive = analysis.get("is_sensitive", "未知")

        # 获取 NotebookLM 摘要
        notebooklm_summary = item.get("notebooklm_summary", "")
        if not notebooklm_summary:
            notebooklm_summary = "（未生成 NotebookLM 摘要）"

        # 获取播客路径
        podcast_path = item.get("notebooklm_podcast_path", "")
        podcast_info = f"[播客文件]({os.path.basename(podcast_path)})" if podcast_path else "无"

        summary_content += f"""### {status_emoji} 文章 ID{article_id}

**简介**：{intro}

**分类**：{category} | **敏感性**：{is_sensitive} | **状态**：{status}

**播客**：{podcast_info}

#### NotebookLM 摘要

{notebooklm_summary}

---

"""

    # 保存文件
    filename_base = f"DAILY_SUMMARY_{date_str}"

    try:
        paths = _save_md_and_docx(summary_content, summary_dir, filename_base)
        return f"✅ 摘要汇总已保存: {paths}"
    except Exception as e:
        return f"❌ 保存摘要汇总失败: {e}"

# ================= 映射表 =================
TOOLS_MAP = {
    "tool_fetch_news": tool_fetch_news,
    "tool_translate_all": tool_translate_all,
    "tool_notebooklm_summary_all": tool_notebooklm_summary_all,
    "tool_analyze_individual": tool_analyze_individual,
    "tool_filter_decision": tool_filter_decision,
    "tool_generate_final": tool_generate_final,
    "tool_publish_to_wechat": tool_publish_to_wechat,
    "tool_merge_summaries": tool_merge_summaries  # 新增：合并摘要
}