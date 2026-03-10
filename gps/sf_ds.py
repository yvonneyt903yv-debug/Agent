# podscribe_automation.py (Version 6.0 - Multi-Series Support)
#!/usr/bin/env python3

import os
import time
import re
import json
import logging
import schedule
import argparse
import fcntl
from datetime import datetime, timedelta
import traceback

# ==================== 进程锁 ====================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE = os.path.join(SCRIPT_DIR, "sf_ds.lock")

class FileLock:
    """文件锁，防止多个进程同时运行"""
    def __init__(self, lock_file):
        self.lock_file = lock_file
        self.fd = None

    def acquire(self):
        try:
            self.fd = open(self.lock_file, 'w')
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fd.write(str(os.getpid()))
            self.fd.flush()
            return True
        except (IOError, OSError):
            if self.fd:
                self.fd.close()
            return False

    def release(self):
        if self.fd:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                self.fd.close()
                os.remove(self.lock_file)
            except:
                pass

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# 导入您现有的辅助模块和配置文件
import singju_ds as gemini_helper
import config

def setup_logging():
    """配置日志记录，输出到控制台和文件。"""
    log_directory = os.path.dirname(os.path.abspath(__file__))
    log_filepath = os.path.join(log_directory, "podscribe_log.txt")
    log_txt_path = os.path.join(log_directory, "log.txt")

    logger = logging.getLogger('PodscribeLogger')
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    file_handler = logging.FileHandler(log_filepath, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    log_txt_handler = logging.FileHandler(log_txt_path, encoding='utf-8')
    log_txt_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    log_txt_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.addHandler(log_txt_handler)
    return logger

logger = setup_logging()

# 导入 DeepSeek review 模块
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'src'))
try:
    from review_markdown_ds import review_markdown_content
    REVIEW_AVAILABLE = True
except ImportError:
    REVIEW_AVAILABLE = False
    logger.warning("review_markdown_ds 模块未找到，将跳过审校步骤")

parser = argparse.ArgumentParser(description='Podscribe 自动化脚本')
parser.add_argument('--date', type=str, help='指定日期，格式: 2026-02-08')
args = parser.parse_args()

SCRIPT_ROOT = os.path.dirname(os.path.abspath(__file__))
PENDING_DIR = os.path.join(SCRIPT_ROOT, "podscribe_pending")
FAILED_LOG_FILE = os.path.join(SCRIPT_ROOT, "failed_transcripts.log")
TRANSLATE_MAX_RETRIES = int(os.getenv("PODSCRIBE_TRANSLATE_MAX_RETRIES", "5"))
TRANSLATE_RETRY_BASE_SECONDS = int(os.getenv("PODSCRIBE_TRANSLATE_RETRY_BASE_SECONDS", "15"))
LIST_PAGE_MAX_RETRIES = int(os.getenv("PODSCRIBE_LIST_PAGE_MAX_RETRIES", "3"))

# ==================== Podcast 系列配置 ====================
PODCAST_SERIES = [
    {
        "name": "Series 1 (1524727)",
        "url": "https://app.podscribe.com/series/1524727",
        "series_id": "1524727"
    },
    {
        "name": "Series 2 (2209654)", 
        "url": "https://app.podscribe.com/series/2209654",
        "series_id": "2209654"
    },
    {
        "name": "Series 3 (127199)",
        "url": "https://app.podscribe.com/series/127199?uid=6448c448-d071-709f-ca38-e981ced5f79e",
        "series_id": "127199"
    },
    {
        "name": "Series 4 (2121)",
        "url": "https://app.podscribe.com/series/2121?uid=6448c448-d071-709f-ca38-e981ced5f79e",
        "series_id": "2121"
    },
    {
        "name": "Series 5 (103505)",
        "url": "https://app.podscribe.com/series/103505?uid=6448c448-d071-709f-ca38-e981ced5f79e",
        "series_id": "103505"
    }
]

def parse_podscribe_date(date_str):
    """
    [增强版] 解析 Podscribe 的日期格式。
    能处理包含换行符、重复内容以及多种日期格式的情况。
    """
    if not date_str:
        return None
        
    # 清洗：移除换行符和多余空格，如果重复只取第一部分
    clean_date_str = date_str.strip().split('\n')[0].strip()
    
    try:
        # 优先尝试直接解析 "M/D/YYYY" 格式
        return datetime.strptime(clean_date_str, "%m/%d/%Y").date()
    except ValueError:
        # 如果失败，则回退到旧的 "M/D" 格式处理方式
        try:
            current_year = datetime.now().year
            full_date_str = f"{clean_date_str}/{current_year}"
            return datetime.strptime(full_date_str, "%m/%d/%Y").date()
        except ValueError:
            logger.warning(f"无法解析日期字符串: '{date_str}' (清洗后: '{clean_date_str}')")
            return None

def save_html_source_to_txt(html_content, safe_title, save_path):
    """将HTML源代码保存到txt文件中。"""
    try:
        if not os.path.exists(save_path):
            os.makedirs(save_path)
        
        today_date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{today_date_str}-{safe_title}_source.txt"
        filepath = os.path.join(save_path, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info(f"✅ 成功保存HTML源码文件到: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"❌ 保存HTML源码文件时出错: {e}")
        return None

def _make_safe_key(raw_key):
    return re.sub(r'[^a-zA-Z0-9._-]', '_', raw_key)

def _get_pending_source_path(unique_key):
    if not os.path.exists(PENDING_DIR):
        os.makedirs(PENDING_DIR)
    return os.path.join(PENDING_DIR, f"{_make_safe_key(unique_key)}.md")

def save_pending_source(unique_key, payload):
    """保存待翻译原文，供网络失败后断点续跑。"""
    path = _get_pending_source_path(unique_key)
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)
    return path

def load_pending_source(unique_key):
    """读取待翻译原文；若不存在返回 None。"""
    path = _get_pending_source_path(unique_key)
    if not os.path.exists(path):
        return None, path
    with open(path, "r", encoding="utf-8") as f:
        return f.read(), path

def remove_pending_source(path):
    if path and os.path.exists(path):
        os.remove(path)

def record_failed_transcript(unique_key, title, series_id, error_msg):
    """记录翻译失败条目，便于人工排查。"""
    payload = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "unique_key": unique_key,
        "series_id": series_id,
        "title": title,
        "error": str(error_msg),
    }
    with open(FAILED_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")

def translate_with_retry(text_to_translate, series_name, title):
    """为整篇翻译增加外层重试，降低临时网络抖动影响。"""
    last_error = None
    for attempt in range(1, TRANSLATE_MAX_RETRIES + 1):
        try:
            translated_markdown = gemini_helper.translate_text_with_deepseek_api(text_to_translate)
            if translated_markdown:
                if attempt > 1:
                    logger.info(f"[{series_name}] 文稿 '{title}' 翻译在第 {attempt} 次尝试成功")
                return translated_markdown
            last_error = "empty_translation"
            logger.warning(f"[{series_name}] 文稿 '{title}' 第 {attempt}/{TRANSLATE_MAX_RETRIES} 次翻译返回为空")
        except Exception as e:
            last_error = e
            logger.warning(f"[{series_name}] 文稿 '{title}' 第 {attempt}/{TRANSLATE_MAX_RETRIES} 次翻译异常: {e}")

        if attempt < TRANSLATE_MAX_RETRIES:
            sleep_seconds = TRANSLATE_RETRY_BASE_SECONDS * attempt
            logger.info(f"[{series_name}] {sleep_seconds} 秒后重试翻译...")
            time.sleep(sleep_seconds)

    return None, last_error

def load_series_list_with_retry(driver, wait, target_url, series_name):
    """列表页加载重试，处理偶发超时/空白页。"""
    last_error = None
    for attempt in range(1, LIST_PAGE_MAX_RETRIES + 1):
        try:
            logger.info(f"[{series_name}] 打开列表页 (尝试 {attempt}/{LIST_PAGE_MAX_RETRIES})...")
            driver.get(target_url)
            driver.maximize_window()
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody > tr")))
            time.sleep(3)
            return True
        except Exception as e:
            last_error = e
            logger.warning(f"[{series_name}] 列表页加载失败 (尝试 {attempt}/{LIST_PAGE_MAX_RETRIES}): {e}")
            if attempt < LIST_PAGE_MAX_RETRIES:
                sleep_seconds = 5 * attempt
                logger.info(f"[{series_name}] {sleep_seconds} 秒后重试列表页...")
                time.sleep(sleep_seconds)
    logger.error(f"[{series_name}] 页面加载超时，未找到文稿列表。最后错误: {last_error}")
    return False

def process_series(driver, wait, series_config, target_dates, processed_titles, PROCESSED_FILE):
    """处理单个 Podcast 系列"""
    target_url = series_config["url"]
    series_name = series_config["name"]
    
    logger.info(f"\n{'='*60}")
    logger.info(f"正在处理系列: {series_name}")
    logger.info(f"URL: {target_url}")
    logger.info(f"{'='*60}")
    
    transcripts_to_process = []
    
    try:
        logger.info(f"[{series_name}] 正在查找今天和昨天发布的文稿...")
        if not load_series_list_with_retry(driver, wait, target_url, series_name):
            driver.save_screenshot(f'debug_screenshot_{series_config["series_id"]}_list_page.png')
            return 0

        episode_rows = driver.find_elements(By.CSS_SELECTOR, "tbody > tr")
        logger.info(f"[{series_name}] 找到 {len(episode_rows)} 行数据")

        for idx, row in enumerate(episode_rows, 1):
            try:
                # 尝试多种选择器来定位日期元素
                date_element = None
                date_str = None
                
                # 方法1: 尝试原始选择器
                try:
                    date_element = row.find_element(By.CSS_SELECTOR, "td:nth-of-type(3) p")
                    date_str = date_element.text.strip()
                except NoSuchElementException:
                    # 方法2: 尝试不带 p 标签
                    try:
                        date_element = row.find_element(By.CSS_SELECTOR, "td:nth-of-type(3)")
                        date_str = date_element.text.strip()
                    except NoSuchElementException:
                        # 方法3: 尝试所有 td，查找包含日期的
                        try:
                            tds = row.find_elements(By.TAG_NAME, "td")
                            if len(tds) >= 3:
                                date_element = tds[2]  # 第三列（索引为2）
                                date_str = date_element.text.strip()
                            else:
                                logger.warning(f"[{series_name}] 第{idx}行: 表格列数不足 ({len(tds)} 列)，跳过")
                                continue
                        except Exception as e:
                            logger.warning(f"[{series_name}] 第{idx}行: 无法定位日期列，错误: {e}")
                            continue
                
                if not date_str:
                    logger.warning(f"[{series_name}] 第{idx}行: 日期文本为空，跳过")
                    continue
                
                parsed_date = parse_podscribe_date(date_str)
                if not parsed_date:
                    logger.info(f"[{series_name}] 第{idx}行: 日期 '{date_str}' 解析失败，跳过")
                    continue
                
                logger.info(f"[{series_name}] 第{idx}行: 日期='{date_str}' -> {parsed_date}")

                if parsed_date in target_dates:
                    link_element = row.find_element(By.CSS_SELECTOR, "td:nth-of-type(1) a")
                    title = link_element.text.strip()
                    if title:
                        # 添加系列标识到标题，避免不同系列的重名冲突
                        transcripts_to_process.append({
                            'title': title,
                            'series_id': series_config["series_id"],
                            'series_name': series_name,
                            'series_url': target_url
                        })
                        logger.info(f"  > [{series_name}] 找到文稿: '{title}' (日期: {parsed_date})")
                else:
                    target_str = ", ".join(str(d) for d in target_dates)
                    logger.info(f"[{series_name}] 第{idx}行: 日期 {parsed_date} 不在目标范围内（目标: {target_str}）")
                    
            except Exception as e:
                # 获取更多调试信息
                try:
                    row_text = row.text[:100] if row.text else "无法获取行文本"
                    logger.warning(f"[{series_name}] 第{idx}行结构异常，已跳过。行内容预览: {row_text}... 错误: {str(e)}")
                except:
                    logger.warning(f"[{series_name}] 第{idx}行结构异常，已跳过。错误: {str(e)}")
                continue
        
        if not transcripts_to_process:
            target_str = ", ".join(str(d) for d in target_dates)
            logger.info(f"[{series_name}] 没有符合条件的文稿（目标日期: {target_str}）")
            return 0

        target_str = ", ".join(str(d) for d in target_dates)
        logger.info(f"[{series_name}] 找到 {len(transcripts_to_process)} 篇文稿需要处理（目标日期: {target_str}）")
        
        processed_count = 0
        for i, transcript_data in enumerate(transcripts_to_process):
            title = transcript_data['title']
            series_url = transcript_data['series_url']
            
            # 使用组合键避免不同系列的重名
            unique_key = f"{transcript_data['series_id']}_{title}"
            
            if unique_key in processed_titles:
                logger.info(f"[{series_name}] 文稿 '{title}' 已处理过，跳过")
                continue
                
            logger.info(f"\n[{series_name}] --- 正在处理第 {i+1}/{len(transcripts_to_process)} 篇文稿: '{title}' ---")
            pending_payload, pending_path = load_pending_source(unique_key)
            text_to_translate = pending_payload

            if text_to_translate:
                logger.info(f"[{series_name}] 检测到断点缓存，将直接重试翻译: {pending_path}")
            else:
                if not load_series_list_with_retry(driver, wait, series_url, series_name):
                    logger.error(f"[{series_name}] 重新进入系列列表失败，跳过文稿: {title}")
                    continue
                
                # 使用更稳定的方法重新定位并点击链接
                try:
                    logger.info(f"[{series_name}] 正在通过精确文本匹配查找链接: '{title[:30]}...' ")
                    all_links_on_page = driver.find_elements(By.CSS_SELECTOR, "tbody > tr > td:nth-of-type(1) a")
                    
                    link_found_and_clicked = False
                    for link_element in all_links_on_page:
                        if link_element.text.strip() == title:
                            logger.info(f"[{series_name}] 找到完全匹配的链接。")
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", link_element)
                            time.sleep(1)

                            logger.info(f"[{series_name}] 准备点击链接...")
                            wait.until(EC.element_to_be_clickable(link_element)).click()
                            link_found_and_clicked = True
                            break
                    
                    if not link_found_and_clicked:
                        logger.error(f"[{series_name}] 无法通过精确匹配找到文稿 '{title}' 的链接，跳过此篇。")
                        continue

                except Exception as e:
                    logger.error(f"[{series_name}] 在查找和点击链接时发生意外错误: {e}", exc_info=True)
                    continue

                # 进入文章详情页后的操作
                try:
                    logger.info(f"[{series_name}] 等待详情页核心内容加载...")
                    wait.until(EC.visibility_of_element_located((By.ID, "transcriptContainerContainer")))
                    logger.info(f"[{series_name}] 详情页核心内容已加载。")

                    try:
                        intercom_close_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[aria-label="Close"]')))
                        logger.info(f"[{series_name}] 检测到Intercom弹窗，正在关闭...")
                        driver.execute_script("arguments[0].click();", intercom_close_button)
                        time.sleep(1)
                    except TimeoutException:
                        logger.info(f"[{series_name}] 未检测到Intercom弹窗，继续。")

                    logger.info(f"[{series_name}] 正在查找并操作 'Times' 开关...")
                    switch_component_locator = (By.XPATH, "//label[contains(., 'Times')]")
                    
                    switch_element = wait.until(EC.presence_of_element_located(switch_component_locator))
                    logger.info(f"[{series_name}] 'Times' 开关元素已在DOM中存在。")

                    driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", switch_element)
                    time.sleep(1)

                    try:
                        clickable_switch_element = wait.until(EC.element_to_be_clickable(switch_component_locator))
                        logger.info(f"[{series_name}] 'Times' 开关元素可点击。")
                        
                        checkbox_input = clickable_switch_element.find_element(By.TAG_NAME, "input")

                        if checkbox_input.is_selected():
                            logger.info(f"[{series_name}] 'Times' 当前已勾选，将点击取消。")
                            clickable_switch_element.click()
                            time.sleep(2)
                            logger.info(f"[{series_name}] 'Times' 已取消勾选。")
                        else:
                            logger.info(f"[{series_name}] 'Times' 已是未勾选状态，无需操作。")

                    except TimeoutException:
                        logger.warning(f"[{series_name}] 'Times' 开关元素在等待期间未能变为可点击，尝试JS点击。")
                        driver.execute_script("arguments[0].click();", switch_element)
                        time.sleep(2)
                        logger.info(f"[{series_name}] 'Times' 开关已通过JS点击操作。")
                    
                    # 直接从DOM提取文稿文本
                    logger.info(f"[{series_name}] 正在直接从DOM提取文稿文本...")
                    article_content = ""
                    try:
                        transcript_selector = "#transcriptContainerContainer div[data-slate-editor='true']"
                        transcript_container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, transcript_selector)))
                        
                        article_content = transcript_container.get_attribute('innerText')

                        if not article_content or len(article_content) < 50:
                            logger.error(f"[{series_name}] 从DOM提取文本失败或内容过短，跳过此文章。")
                            continue

                        logger.info(f"[{series_name}] 成功从DOM提取文本，长度: {len(article_content)} 字符。")
                    
                    except TimeoutException:
                        logger.error(f"[{series_name}] 找不到指定的文本容器，无法提取内容。")
                        continue
                    
                    text_to_translate = f"# {title}\n\n{article_content}"
                    pending_path = save_pending_source(unique_key, text_to_translate)
                    logger.info(f"[{series_name}] 已保存断点原文: {pending_path}")
                except Exception as e:
                    logger.error(f"[{series_name}] 处理详情页时发生错误: {title}")
                    logger.error(traceback.format_exc())
                    error_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                    screenshot_path = f"debug_screenshot_{series_config['series_id']}_{error_time}.png"
                    pagesource_path = f"debug_page_source_{series_config['series_id']}_{error_time}.html"
                    driver.save_screenshot(screenshot_path)
                    logger.error(f"[{series_name}] 屏幕截图已保存到: {screenshot_path}")
                    with open(pagesource_path, "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                    logger.error(f"[{series_name}] 页面源代码已保存到: {pagesource_path}")
                    continue

            try:
                logger.info(f"[{series_name}] 调用 DeepSeek 进行翻译...")
                translated_markdown = translate_with_retry(text_to_translate, series_name, title)

                if isinstance(translated_markdown, tuple):
                    _, error_obj = translated_markdown
                    record_failed_transcript(unique_key, title, series_config["series_id"], error_obj)
                    logger.error(f"[{series_name}] 翻译失败，已记录失败日志并保留断点原文: {pending_path}")
                    continue

                # DeepSeek Review 审校
                if REVIEW_AVAILABLE:
                    logger.info(f"[{series_name}] 调用 DeepSeek 进行审校...")
                    try:
                        reviewed_markdown = review_markdown_content(translated_markdown)
                        if reviewed_markdown:
                            translated_markdown = reviewed_markdown
                            logger.info(f"[{series_name}] 审校完成")
                        else:
                            logger.warning(f"[{series_name}] 审校返回为空，使用原翻译结果")
                    except Exception as e:
                        logger.warning(f"[{series_name}] 审校失败: {e}，使用原翻译结果")

                logger.info(f"[{series_name}] 翻译完成，正在保存文件...")
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:50]
                
                # 在文件名中添加系列标识
                series_prefix = f"S{series_config['series_id']}_"
                safe_title_with_prefix = series_prefix + safe_title

                # 保存 Markdown 文件
                gemini_helper.SAVE_PATH = config.PODSCRIBE_SAVE_PATH
                md_filepath = gemini_helper.save_to_markdown_file(translated_markdown, safe_title_with_prefix)
                if md_filepath:
                    logger.info(f"[{series_name}] Markdown 文件已保存: {md_filepath}")

                # 保存 HTML 和 Word
                _, full_html = gemini_helper.convert_to_markdown_and_copy(translated_markdown)
                
                html_filepath = gemini_helper.save_to_html_file(full_html, safe_title_with_prefix)
                if html_filepath:
                    save_html_source_to_txt(full_html, safe_title_with_prefix, config.PODSCRIBE_SAVE_PATH)
                    gemini_helper.save_to_word_document(html_filepath, safe_title_with_prefix)
                    processed_titles.add(unique_key)
                    remove_pending_source(pending_path)
                    with open(PROCESSED_FILE, 'a', encoding='utf-8') as f:
                        f.write(f"{unique_key}\n")
                    logger.info(f"[{series_name}] 文稿已记录到去重列表")
                    processed_count += 1
                else:
                    logger.error(f"[{series_name}] HTML文件保存失败，无法创建其他文件。")
            except Exception as e:
                record_failed_transcript(unique_key, title, series_config["series_id"], e)
                logger.error(f"[{series_name}] 翻译/保存流程异常: {title}")
                logger.error(traceback.format_exc())
        
        return processed_count
        
    except Exception as e:
        logger.error(f"[{series_name}] 处理系列时发生严重错误: {e}")
        logger.error(traceback.format_exc())
        return 0

def main_workflow():
    """主工作流程，处理所有 Podcast 系列"""
    logger.info(f"---=== 开始执行 Podscribe 自动化任务 @ {datetime.now()} ===---")
    driver = None
    PROCESSED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed_transcripts.txt")
    processed_titles = set()
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r', encoding='utf-8') as f:
            processed_titles = set(line.strip() for line in f if line.strip())
    logger.info(f"已加载 {len(processed_titles)} 个已处理的文稿记录")
    
    # 解决 "Bad Gateway" 错误
    os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
    
    try:
        driver = gemini_helper.setup_driver()
        if not driver:
            logger.error("WebDriver初始化失败，任务终止。")
            return

        wait = WebDriverWait(driver, 30)
        
        # 确定目标日期
        if args.date:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
            target_dates = {target_date}
            logger.info(f"指定日期模式: {target_date}")
        else:
            today_date = datetime.now().date()
            yesterday_date = (datetime.now() - timedelta(days=1)).date()
            target_dates = {today_date, yesterday_date}
            logger.info(f"默认模式: 今天={today_date}, 昨天={yesterday_date}")
        
        # 处理所有系列
        total_processed = 0
        for series_config in PODCAST_SERIES:
            count = process_series(driver, wait, series_config, target_dates, processed_titles, PROCESSED_FILE)
            total_processed += count
        
        logger.info(f"\n{'='*60}")
        logger.info(f"所有系列处理完成！")
        logger.info(f"总共处理: {total_processed} 篇文稿")
        logger.info(f"{'='*60}")

    except Exception as e:
        logger.error("主流程发生严重错误。")
        logger.error(traceback.format_exc())
    finally:
        if driver:
            driver.quit()
            logger.info("浏览器已关闭。")
        logger.info(f"---=== Podscribe 自动化任务执行完毕 @ {datetime.now()} ===---")

if __name__ == "__main__":
    # 获取进程锁，防止重复运行
    lock = FileLock(LOCK_FILE)
    if not lock.acquire():
        logger.warning("另一个 sf_ds.py 实例已在运行，退出。")
        exit(0)

    try:
        PROCESSED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed_transcripts.txt")
        if not os.path.exists(PROCESSED_FILE):
            with open(PROCESSED_FILE, 'w', encoding='utf-8') as f:
                f.write("")
        logger.info("脚本启动，立即执行一次用于测试...")
        main_workflow()

        schedule.every(2).hours.do(main_workflow)
        logger.info("任务已安排，将每2小时执行一次。按 Ctrl+C 退出。")

        while True:
            schedule.run_pending()
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到退出信号，正在关闭...")
    finally:
        lock.release()
        logger.info("进程锁已释放。")
