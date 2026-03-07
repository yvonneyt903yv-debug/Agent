

import time
import schedule
import pyperclip
import json 
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from docx import Document
import os
import re
import markdown
import json
import dateutil.parser
from deepseek import call_deepseek_api
import traceback
from selenium.common.exceptions  import TimeoutException
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.common.exceptions import StaleElementReferenceException
import subprocess
import platform
import shutil

# --- 配置区 (macOS 版本) ---
# !!! 用户需要修改这里 !!!
# ----------------------------------------------------
# 1. WebDriver 的路径 (如果用 Homebrew 安装，通常不需要设置，可以留空或注释掉)
# 如果手动安装，请提供绝对路径，例如: '/Users/your_username/Documents/drivers/chromedriver'
CHROME_DRIVER_PATH = None # 设为 None，让 Selenium 自动寻找

# 2. 目标网站URL (与之前相同)
URL_SITE_1_ARTICLE = "https://singjupost.com"

# 3. 翻译的Prompt (与之前相同)
TRANSLATION_PROMPT = """你是一位专业的中文翻译和内容编辑专家。你的任务是接收以下英文文本，并严格按照下列要求，输出一份高质量的中文译稿。翻译要求:精准流畅： 译文必须精准传达原文含义，同时语言表达要流畅自然，完全符合中文母语者的阅读习惯。例如You know这种口语化表述不需要翻译， 直接删除即可。风格优美： 语言风格应力求专业、精炼且优美，避免因直译而产生的生硬感和翻译腔。内容清理要求:删除时间戳： 必须删除文本中所有形式的时间戳标记，例如 (00:38:28) 或 [01:15:10] 等模式，确保最终文稿内容纯净。格式化要求:标题层级： 将文中的大标题设置为一级标题（Markdown格式: # 标题），将小标题设置为二级标题（Markdown格式: ## 标题）。突出说话人： 将文稿中所有的说话人标识（例如 Speaker Name: 或 约翰:）进行加粗处理。delete all the timestamp marks.
注意避免以下常见问题：1. **遗漏翻译**：如发现仍保留英文原文，请补充对应的完整中文翻译。2. **冗余说明**：如存在与正文主题无关的翻译解释、注释或元说明性内容，请删除。3. **格式错误（重要）**：- **说话人切换格式**：当对话中说话人发生切换时，必须确保： * 每个说话人的标识（如 **说话人**：）必须独占一行；说话人的内容结束后，必须有一个空行（两个换行符）与下一个说话人分隔；若出现对话人切换，请确保该说话内容 作为独立段落存在。 对话人标签（如 姓名：）前必须为空行（或为文档起始）， 仅有单行换行但未形成新段落的情况，视为格式错误，必须修正。正确格式示例：
       ```
       **说话人A**：这是说话人A的内容。
       
       **说话人B**：这是说话人B的内容。
       
       **说话人A**：继续的内容。
       ```
   - **段落分隔**：确保不同说话人的内容之间有空行分隔，同一说话人的连续内容可以不分段
   - **换行问题**：如果发现说话人标识和内容在同一行，或两个说话人之间没有空行，必须修正

请勿新增内容、总结或评论，仅输出最终修订结果。"""

# 4. 保存Word文档的文件夹路径（使用相对路径，便于服务器部署）
SAVE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gps", "Automated_Articles")

# 5. (备选方案) 如果你确定需要为脚本手动指定代理, 请取消下面三行代码的注释
# 默认的Clash代理地址通常是 http://127.0.0.1:7890
# PROXY_URL = "http://127.0.0.1:7890" 
# os.environ['HTTP_PROXY'] = PROXY_URL
# os.environ['HTTPS_PROXY'] = PROXY_URL
# ----------------------------------------------------





def setup_driver():
    """初始化并返回一个Selenium WebDriver实例。"""
    # <<< 关键修改 (5): 解决 "ERR_INTERNET_DISCONNECTED" 和 "error sending request"
    # 当系统存在网络代理(如Clash)时, 不仅浏览器需要代理, Selenium Manager(用于下载驱动)本身也需要。
    # 下面的代码为Python脚本和将要启动的浏览器同时设置代理。
    # 代理只给 Chrome 浏览器用，不污染 os.environ（避免影响 deepseek API 直连）
    PROXY_URL = "http://127.0.0.1:7890" if platform.system() == "Darwin" else None
    try:
        # 避免 Selenium Python 客户端访问本地 chromedriver(127.0.0.1) 时被系统代理劫持
        no_proxy_hosts = "127.0.0.1,localhost"
        os.environ["NO_PROXY"] = no_proxy_hosts
        os.environ["no_proxy"] = no_proxy_hosts

        chrome_options = webdriver.ChromeOptions()

        # 只给浏览器设代理参数，不写 os.environ
        if PROXY_URL:
            chrome_options.add_argument(f'--proxy-server={PROXY_URL}')

        # --- 伪装成真人浏览器的关键选项 ---
        # 1. 设置User-Agent，这是最重要的身份标识
        user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        chrome_options.add_argument(f'user-agent={user_agent}')

        # 2. 保持无头模式，但使用新的、更难被检测到的 "headless" 模式
        chrome_options.add_argument("--headless=new")

        # 3. 其他保持稳定的选项
        if platform.system() == "Linux":
            chrome_options.binary_location = "/usr/bin/chromium-browser"
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu') # 在新的无头模式下，这一行有时可以去掉
        chrome_options.add_argument('--window-size=1920,1080') # 设置一个真实世界的窗口大小

        # 4. 隐藏自动化痕迹
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # --- [关键修改 1] 改变页面加载策略 ---
        # normal: 等待所有资源加载完成 (默认)
        # eager:  等待HTML文档加载和解析完成，不等待图片、样式表等次要资源
        # none:   立即返回，不等待任何加载
        # 我们使用 'eager' 来提高效率，避免被慢速资源卡住
        chrome_options.page_load_strategy = 'eager'

        # 优先使用本机已安装的 chromedriver，避免 Selenium Manager 在线下载失败
        chromedriver_path = None
        if CHROME_DRIVER_PATH and os.path.exists(CHROME_DRIVER_PATH):
            chromedriver_path = CHROME_DRIVER_PATH
        else:
            candidate_paths = [
                "/opt/homebrew/bin/chromedriver",  # macOS (Apple Silicon Homebrew)
                "/usr/local/bin/chromedriver",     # macOS (Intel/Homebrew)
                "/usr/bin/chromedriver",           # Linux
            ]
            for p in candidate_paths:
                if os.path.exists(p):
                    chromedriver_path = p
                    break
            if not chromedriver_path:
                chromedriver_path = shutil.which("chromedriver")

        service = Service(chromedriver_path) if chromedriver_path else Service()
        driver = webdriver.Chrome(service=service, options=chrome_options)

        # --- [关键修改 2] 设置页面加载超时时间 ---
        # 将默认的300秒(5分钟)延长到600秒(10分钟)，给慢速网站更充足的加载时间
        driver.set_page_load_timeout(600)

        # --- 在浏览器环境中执行JS，进一步抹除自动化工具的指纹 ---
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            })
            """
        })

        print("WebDriver初始化成功 (已进行反检测配置，并优化了加载策略和超时)。")
        return driver
    except Exception as e:
        print(f"WebDriver初始化失败: {e}")
        return None

def generate_text_basic(prompt):
    """
    [优化版] 使用本地 deepseek.py API 生成文本，并智能解析JSON响应。
    :param prompt: str, 用户输入的prompt
    :param model_name: str, 模型名 (当前未使用)
    :return: str, 解析后提取出的纯净文本
    """
    try:
        # call_deepseek_api 现在返回的是一个JSON格式的字符串
        response_str = call_deepseek_api(prompt)

        if not response_str:
            print("API 返回为空。")
            return None

        # 步骤 1: 尝试将响应字符串解析为 JSON 对象 (Python字典)
        try:
            data = json.loads(response_str)
            
            # 步骤 2: 按照观察到的结构，层层深入，提取核心文本内容
            # 路径: candidates -> [0] -> content -> parts -> [0] -> text
            text_content = data['candidates'][0]['content']['parts'][0]['text']
            
            # 返回提取出的、干净的文本
            return text_content.strip()

        # 步骤 3: 如果解析JSON失败，说明它可能是一个我们未预料到的纯文本响应
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            # 这个except能捕捉多种错误:
            # - json.JSONDecodeError: 响应不是一个有效的JSON字符串。
            # - KeyError: 字典中缺少'candidates'这样的键。
            # - IndexError: 'candidates'或'parts'列表是空的。
            # - TypeError: 试图在非字典或非列表上进行操作。
            print("WARN: 无法将API响应解析为预期的JSON结构，将直接返回原始文本作为备用方案。")
            # 假设它可能是一个纯文本响应，直接返回它
            return response_str.strip()

    except Exception as e:
        print(f"调用 deepseek.py API 或解析时出错: {e}")
        traceback.print_exc() # 打印更详细的错误堆栈信息
        return None

def split_text_by_length(text, max_chars=10000, target_chunk_size=10000):
    """
    检查文本长度，如果超过指定字符数则按句子拆分文本

    :param text: str, 要检查的文本
    :param max_chars: int, 最大字符数限制（默认5万字）
    :param target_chunk_size: int, 目标分块大小（默认10万字）
    :return: list, 拆分后的文本块列表
    """
    text_length = len(text)
    print(f"文本总长度: {text_length} 字符")

    # 如果文本长度未超过限制，直接返回原文本
    if text_length <= max_chars:
        print(f"文本长度 {text_length} 未超过 {max_chars} 字符限制，无需拆分")
        return [text]

    print(f"文本长度 {text_length} 超过 {max_chars} 字符限制，开始按句子拆分...")

    # 按句子拆分文本（支持中英文标点符号）
    sentences = re.split(r'(?<=[.!?。！？])\s*', text)
    print(f"文本已拆分为 {len(sentences)} 个句子")

    text_chunks = []
    current_chunk = ""
    current_length = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:  # 跳过空句子
            continue

        sentence_length = len(sentence)

        # 如果添加这个句子会超过目标分块大小，先保存当前分块
        if current_length + sentence_length > target_chunk_size and current_chunk:
            text_chunks.append(current_chunk.strip())
            print(f"创建分块 {len(text_chunks)}: {current_length} 字符")
            current_chunk = sentence
            current_length = sentence_length
        else:
            # 添加句子到当前分块
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence
            current_length += sentence_length

    # 添加最后一个分块
    if current_chunk:
        text_chunks.append(current_chunk.strip())
        print(f"创建分块 {len(text_chunks)}: {current_length} 字符")

    print(f"文本拆分完成，共创建 {len(text_chunks)} 个分块")
    for i, chunk in enumerate(text_chunks, 1):
        print(f"  分块 {i}: {len(chunk)} 字符")

    return text_chunks


from selenium.webdriver.common.action_chains import ActionChains


def get_todays_article_from_site1(driver, url):
    """
    模块一：[终极防御版] 智能滚动、精准定位、处理广告干扰。
    """
    print(f"正在访问网站1 (列表页): {url}")
    driver.get(url)
    driver.maximize_window()

    # --- 处理cookie同意弹窗 ---
    try:
        print("检查并处理cookie同意弹窗...")
        time.sleep(2) # 给页面和弹窗加载时间

        cookie_selectors = [
            "button[data-testid='cookie-banner-accept']",
            "button[data-testid='cookie-banner-reject']",
            "button[data-testid='cookie-banner-decline']",
            "button[data-testid='cookie-banner-deny']",
            "button[data-testid='cookie-banner-not-consent']",
            "button[data-testid='cookie-banner-no']",
            "//button[contains(text(), 'Not consent')]",
            "//button[contains(text(), 'Reject')]",
            "//button[contains(text(), 'Decline')]",
            "//button[contains(text(), 'Deny')]",
            "//button[contains(text(), 'No')]",
            "//button[contains(text(), '拒绝')]",
            "//button[contains(text(), '不同意')]",
            "//button[contains(text(), '不接受')]",
            ".cookie-banner button",
            ".cookie-notice button",
            ".cookie-popup button",
            ".gdpr-banner button",
            ".privacy-banner button",
            "[id*='cookie'] button",
            "[class*='cookie'] button",
            "[id*='gdpr'] button",
            "[class*='gdpr'] button",
            "[id*='privacy'] button",
            "[class*='privacy'] button"
        ]

        cookie_handled = False
        for selector in cookie_selectors:
            try:
                if selector.startswith("//"):
                    cookie_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                else:
                    cookie_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )

                print(f"找到cookie弹窗按钮: {selector}")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", cookie_button)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", cookie_button)
                time.sleep(1)
                cookie_handled = True
                print("已处理cookie弹窗")
                break
            except TimeoutException:
                continue
            except Exception as e:
                print(f"处理cookie弹窗时出错 ({selector}): {e}")
                continue

        if not cookie_handled:
            print("未检测到cookie弹窗或无需处理")

    except Exception as e:
        print(f"处理cookie弹窗时发生异常: {e}")

    # --- 计算目标日期（今天和昨天），并转换为日期对象以便比较 ---
    today_date = datetime.now().date()
    yesterday_date = (datetime.now() - timedelta(days=1)).date()
    target_date_objects = {today_date, yesterday_date}

    print(f"目标日期（今天和昨天）: {target_date_objects}")

    wait = WebDriverWait(driver, 20)

    # --- 步骤一: 智能滚动并收集链接 (保持不变) ---
    print("步骤一：正在智能滚动列表页以加载所有文章...")
    article_links_to_visit = []
    # 增加滚动次数和稳定性
    for i in range(15):
        try:
            # 获取滚动前页面高度
            last_height = driver.execute_script("return document.body.scrollHeight")
            
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            print(f"  滚动第 {i+1} 次...")
            # 等待新内容加载
            time.sleep(2)

            # 检查页面高度是否有变化
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height and i > 5: # 如果滚动5次后高度不再变化
                print("页面高度不再增加，停止滚动。")
                break
        except Exception as e:
            print(f"滚动时发生错误: {e}")
            break

    # 滚动结束后，统一收集所有链接
    articles_on_list_page = driver.find_elements(By.CSS_SELECTOR, "article.post")
    print(f"滚动完成，共找到 {len(articles_on_list_page)} 个文章元素。")

    for article in articles_on_list_page:
        try:
            date_element = article.find_element(By.CSS_SELECTOR, "time.entry-date")
            article_datetime_str = date_element.get_attribute('datetime')
            parsed_article_date = None

            if article_datetime_str:
                try:
                    parsed_article_date = dateutil.parser.parse(article_datetime_str).date()
                except ValueError:
                    print(f"  DEBUG: 无法解析 datetime 属性 '{article_datetime_str}'")

            if not parsed_article_date:
                inner_text_date_str = date_element.get_attribute('innerText').strip()
                if inner_text_date_str:
                    try:
                        # 尝试更灵活的日期解析
                        parsed_article_date = dateutil.parser.parse(inner_text_date_str).date()
                    except (ValueError, dateutil.parser.ParserError):
                         print(f"  DEBUG: 无法解析innerText中的日期: '{inner_text_date_str}'")

            if parsed_article_date and parsed_article_date in target_date_objects:
                link_element = article.find_element(By.CSS_SELECTOR, "h2.entry-title a")
                link = link_element.get_attribute('href')
                if link and link not in article_links_to_visit:
                    article_links_to_visit.append(link)
                    print(f"  > 找到目标链接: {link} (日期: {parsed_article_date})")
        
        except Exception as e:
            # print(f"  DEBUG: 查找日期或链接时跳过一个元素: {e}")
            continue

    if not article_links_to_visit:
        print("未在列表页找到任何符合日期的文章。")
        return None

    print(f"\n步骤二：收集完成，共找到 {len(article_links_to_visit)} 个目标链接。准备逐一访问并提取全文...")
    all_full_articles = []

    # --- 步骤二: 独立循环，访问每个链接并处理 ---
    for article_url in article_links_to_visit:
        try:
            print(f"\n--- 正在处理: {article_url} ---")
            driver.get(article_url)
            
            # 等待核心内容区域出现
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.entry-content, article, div.post-content")))

            # --- 强化 "Continue Reading" 按钮处理 ---
            try:
                # 使用更通用的XPath来定位按钮
                continue_button_xpath = "//button[contains(., 'Continue Reading') or contains(., 'Show More') or contains(., 'Load More')]"
                continue_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, continue_button_xpath))
                )
                print("找到 'Continue Reading' 或类似按钮，尝试点击...")
                driver.execute_script("arguments[0].scrollIntoView(true);", continue_button)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", continue_button)
                print("按钮已点击。")
                time.sleep(2) # 等待内容加载
            except TimeoutException:
                print("未找到 'Continue Reading' 按钮，或无需点击。")

            # --- 提取内容 (使用更灵活的元素查找) ---
            print("开始提取文章内容...")

            # 提取标题
            full_title = "无标题文章"
            title_selectors = ["h1.entry-title", "h1.post-title", "h1"]
            for selector in title_selectors:
                try:
                    title_element = driver.find_element(By.CSS_SELECTOR, selector)
                    full_title = title_element.text.strip()
                    if full_title:
                        print(f"找到标题: {full_title[:50]}...")
                        break
                except Exception:
                    continue

            # 提取内容
            full_content = ""
            content_selectors = ["div.entry-content", "div.post-content", "article"]
            for selector in content_selectors:
                try:
                    content_element = driver.find_element(By.CSS_SELECTOR, selector)
                    # 使用JavaScript获取文本，通常更稳定
                    full_content = driver.execute_script("return arguments[0].innerText;", content_element).strip()
                    if len(full_content) > 200: # 确保内容足够长
                        print(f"找到内容 (来自 {selector})，长度: {len(full_content)} 字符")
                        break
                except Exception:
                    continue

            if full_content:
                full_article = f"# {full_title}\n\n{full_content}"
                print("成功提取文章全文。")
                all_full_articles.append(full_article)
            else:
                print("错误: 未能提取到足够的文章内容，跳过此文章。")

        except Exception as e:
            print(f"处理文章 {article_url} 时出错，跳过此篇。错误详情: {str(e)}")
            traceback.print_exc()
            continue

    if all_full_articles:
        print("\n所有文章处理完毕。")
        return '\n\n---\n\n'.join(all_full_articles)

    return None


def convert_to_markdown_and_copy(markdown_text):
    """
    将Markdown文本转换为带有自定义CSS样式的HTML片段，并复制到剪贴板，适合粘贴到微信公众号不变形。
    :param markdown_text: str, Markdown格式的文本
    :return: tuple, (HTML片段, 完整HTML文档)
    """
    css_style = """
<style>
/*自定义样式，实时生效*/

/* 全局属性 */
body {
  padding: 10px;
  font-family: ptima-Regular;
  word-break: break-all;
}

/* 段落样式 */
#nice p {
  margin-top: 5px;
  margin-bottom: 5px;
  line-height: 26px;
  word-spacing: 3px;
  letter-spacing: 3px;
  text-align: left;
  color: #3e3e3e;
  font-size: 17px;
  text-indent: 0em;
}

/* 一级标题 */
#nice h1 {
  color: rgb(89,89,89);
}

/* 二级标题 */
#nice h2 {
  border-bottom: 2px solid rgb(89,89,89);
  margin-bottom: 5px;
  color: rgb(89,89,89);
}

/* 二级标题内容 */
#nice h2 .content {
  font-size: 22px;
  display: inline-block;
  border-bottom: 2px solid rgb(89,89,89);
}

/* 引用 */
#nice blockquote {
  font-style: normal;
  padding: 10px;
  position: relative;
  line-height: 1.8;
  text-indent: 0;
  border: none;
  color: #888;
}

#nice blockquote:before {
  content: "\\"";
  display: inline;
  color: #555555;
  font-size: 4em;
  font-family: Arial, serif;
  line-height: 1em;
  font-weight: 700;
}

/* 链接 */
#nice a {
  color: rgb(71, 193, 168);
  border-bottom: 1px solid rgb(71, 193, 168);
}

/* 加粗 */
#nice strong {
  color: rgb(89, 89, 89);
}

/* 斜体 */
#nice em {
  color: rgb(71, 193, 168);
}

/* 行内代码 */
#nice p code, #nice li code {
  color: rgb(71, 193, 168);
}

/* 表格内的单元格 */
#nice table tr th,
#nice table tr td {
  font-size: 16px;
  border: 1px solid #ccc;
  padding: 5px 10px;
}

/* "参考资料"四个字 */
#nice .footnotes-sep:before {
  content: "参考资料";
}

/* 参考资料文字 */
#nice .footnote-item p {
  color: rgb(71, 193, 168);
}
</style>
"""
    # 将Markdown转为HTML
    html_body = markdown.markdown(markdown_text, extensions=['tables', 'fenced_code', 'sane_lists'])
    # 包裹在#nice容器中
    full_html = f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n{css_style}</head>\n<body>\n<div id="nice">{html_body}</div>\n</body>\n</html>'

    # 复制到剪贴板
    try:
        pyperclip.copy(f'<div id="nice">{html_body}</div>')
        print("已将带样式的HTML片段复制到剪贴板，可直接粘贴到微信公众号。")
    except pyperclip.PyperclipException as e:
        print(f"无法复制到剪贴板: {e}")
        print("请确保您在图形环境中运行此脚本, 或者安装了 xclip/xsel (Linux) 或 pbcopy/pbpaste (macOS)。")

    return f'<div id="nice">{html_body}</div>', full_html

def save_to_html_file(html_content, markdown_first_line):
    """
    将 HTML 内容保存为文件。
    文件名根据 Markdown 文本的第一行生成。

    :param html_content: str, 完整的 HTML 格式字符串。
    :param markdown_first_line: str, 原始 Markdown 文本的第一行，用于生成文件名。
    :return: str or None, 成功则返回文件路径，失败则返回 None。
    """
    try:
        # 1. 确保保存目录存在
        if not os.path.exists(SAVE_PATH):
            os.makedirs(SAVE_PATH)

        # 2. 生成文件名
        safe_title = re.sub(r'[\\/*?:"<>|]', "", markdown_first_line).strip()[:50]
        today_date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{today_date_str}-{safe_title}.html"
        filepath = os.path.join(SAVE_PATH, filename)

        # 3. 将HTML内容写入文件
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"✅ 成功保存 HTML 文件到: {filepath}")
        return filepath

    except Exception as e:
        print(f"❌ 保存 HTML 文件时出错: {e}")
        return None

def save_to_word_document(html_filepath, markdown_first_line):
    """
    模块四：使用pandoc将HTML文件转换为Word文档。
    :param html_filepath: str, 之前保存的HTML文件的完整路径。
    :param markdown_first_line: str, 原始 Markdown 文本的第一行，用于生成文件名。
    """
    if not html_filepath or not os.path.exists(html_filepath):
        print("未找到要转换的HTML文件。")
        return

    try:
        if not os.path.exists(SAVE_PATH):
            os.makedirs(SAVE_PATH)

        # 根据文章标题生成安全的文件名
        safe_first_line = re.sub(r'[\\/*?:"<>|]', "", markdown_first_line).strip()[:50]
        today_date_str = datetime.now().strftime("%Y-%m-%d")

        # 生成Word文档的文件路径
        word_filename = f"{today_date_str}-{safe_first_line}.docx"
        word_filepath = os.path.join(SAVE_PATH, word_filename)

        # 调用pandoc进行转换
        print(f"正在使用pandoc将 {html_filepath} 转换为 {word_filepath}...")
        
        command = ['pandoc', html_filepath, '-f', 'html', '-t', 'docx', '-o', word_filepath]
        
        result = subprocess.run(command, capture_output=True, text=True, check=True)

        print(f"✅ 成功保存Word文档: {word_filepath}")
        if result.stdout:
            print("Pandoc stdout:", result.stdout)
        if result.stderr:
            print("Pandoc stderr:", result.stderr)

    except FileNotFoundError:
        print("错误：Pandoc未安装或不在系统PATH中。请先安装Pandoc。")
        print("macOS用户可以通过 `brew install pandoc` 安装。")
    except subprocess.CalledProcessError as e:
        print(f"Pandoc转换失败 (错误代码: {e.returncode})。")
        print("Stdout:", e.stdout)
        print("Stderr:", e.stderr)
    except Exception as e:
        print(f"保存Word文档时出错: {e}")
    finally:
        pass


def save_to_markdown_file(markdown_content, markdown_first_line):
    """
    将 Markdown 内容保存为 .md 文件。
    文件名根据 Markdown 文本的第一行生成。

    :param markdown_content: str, 完整的 Markdown 格式字符串。
    :param markdown_first_line: str, 原始 Markdown 文本的第一行，用于生成文件名。
    :return: str or None, 成功则返回文件路径，失败则返回 None。
    """
    try:
        # 1. 确保保存目录存在
        if not os.path.exists(SAVE_PATH):
            os.makedirs(SAVE_PATH)

        # 2. 生成文件名
        safe_title = re.sub(r'[\\/*?:"<>|]', "", markdown_first_line).strip()[:50]
        today_date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{today_date_str}-{safe_title}.md"
        filepath = os.path.join(SAVE_PATH, filename)

        # 3. 将Markdown内容写入文件
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        print(f"✅ 成功保存 Markdown 文件到: {filepath}")
        return filepath

    except Exception as e:
        print(f"❌ 保存 Markdown 文件时出错: {e}")
        return None


def _create_name_glossary(text):
    """从文本块中提取人名并创建术语表。"""
    print("正在为第一块文本创建人名术语表...")
    prompt = f"""
    **Task:**
    1.  Analyze the following English text and identify all person names.
    2.  Create a JSON object that maps the original English names to their standard Chinese translations.
    3.  You MUST return ONLY the JSON object, with a single key "name_glossary".

    **Example of the required output format:**
    ```json
    {{
      "name_glossary": {{
        "John Smith": "约翰·史密斯",
        "Dr. Emily Carter": "艾米丽·卡特博士"
      }}
    }}
    ```

    **Text to Process:**
    ---
    {text}
    """
    # 术语抽取只用于提升一致性，不应阻塞主翻译流程。
    # 这里采用短超时 + 单次尝试，失败直接降级为空术语表。
    glossary_timeout_seconds = int(os.getenv("GLOSSARY_TIMEOUT_SECONDS", "45"))
    max_retries = 1
    for attempt in range(max_retries):
        try:
            response_text = call_deepseek_api(
                prompt,
                timeout=glossary_timeout_seconds,
                max_retries=1,
                retry_delay=1,
                thinking=False,
                max_tokens=1200,
                stream=False,
                temperature=0.2,
                top_p=0.9,
            )
            if not response_text:
                continue

            json_match = re.search(r'```(?:json)?\s*({.*?})\s*```', response_text, re.DOTALL)
            json_str = json_match.group(1) if json_match else response_text
            data = json.loads(json_str)
            glossary = data.get("name_glossary", {})
            if glossary:
                print(f"术语表创建成功: {glossary}")
                return glossary
        except Exception as e:
            print(f"创建术语表尝试 {attempt + 1} 失败: {e}")
            time.sleep(1)
            continue
    print("警告: 创建术语表失败，将不使用术语表继续翻译。")
    return {}

def _translate_chunk(text, name_glossary):
    """使用提供的人名术语表翻译单个文本块。"""
    prompt = ""
    if name_glossary:
        glossary_str = "\n".join([f"- {en}: {zh}" for en, zh in name_glossary.items()])
        prompt = f"""
        **Primary Directive:**
        You MUST strictly follow the provided name glossary for all person names to ensure consistency.

        **Name Glossary to Follow:**
        ---
        {glossary_str}
        ---

        **Task:**
        1.  Translate the following English text into fluent Chinese.
        2.  Apply the name translations from the glossary above.
        3.  Use Markdown formatting: '#' for main title, '##' for subtitles, and '**' for bolding speaker names. Remove timestamps.
        4.  Return ONLY the translated Chinese text.
        5. Delete all the timestamp marks.

        **Text to Translate:**
        ---
        {text}
        """
    else:
        prompt = f"""
        **Task:**
        1.  Translate the following English text into fluent Chinese.
        2.  Use Markdown formatting: '#' for main title, '##' for subtitles, and '**' for bolding speaker names. Remove timestamps.
        3.  Return ONLY the translated Chinese text.
        4. Delete all the timestamp marks.

        **Text to Translate:**
        ---
        {text}
        """

    print(f"开始翻译文本块 (长度: {len(text)} 字符)...")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response_text = generate_text_basic(prompt)
            if response_text and len(response_text) > 10:
                print(f"文本块翻译成功 (输出长度: {len(response_text)} 字符)")
                return response_text
            print(f"翻译尝试 {attempt + 1}/{max_retries} 失败：API返回空内容或内容过短。")
        except Exception as e:
            print(f"翻译尝试 {attempt + 1}/{max_retries} 失败，错误: {e}")

        if attempt < max_retries - 1:
            wait_time = (attempt + 1) * 5
            print(f"将在 {wait_time} 秒后进行下一次重试...")
            time.sleep(wait_time)
            
    print(f"错误：此文本块在重试 {max_retries} 次后仍然失败，跳过。")
    return None

def translate_text_with_deepseek_api(text):
    """
   # 专业中文编辑审核系统

你是一位专业的中文编辑和翻译专家。请按以下流程处理文章：

## 📋 处理流程

### 第一步：内容筛选
- **立即跳过**以下类型的文章（不做任何处理）：
  - 娱乐明星访谈
  - 演艺界人物专访
  - 明星八卦或娱乐新闻
  - 印度名人、政客（对国际社会影响不足）访谈，或者发生在印度的访谈
  - 印度国家发展相关的访谈
- 如判定为需跳过的内容，直接输出：`[已跳过：娱乐明星类内容]`

### 第二步：术语表构建（仅处理非娱乐内容）
**任务**：通读全文，提取并标准化所有关键术语
- 识别所有人名（中外人名）
- 识别专业术语、机构名称、地名
- 为每个术语确定统一的翻译/表述方式
- 输出格式：
  ```
  【术语表】
  - 人名：[原文] → [标准中文表述]
  - 术语：[原文] → [标准中文翻译]
  - 机构：[原文] → [标准中文名称]
  ```

### 第三步：分块翻译与编辑
**对于长文本**（超过3000字）：
1. 自动拆分为逻辑段落块（每块2000-3000字）
2. 逐块处理，确保：
   - 严格遵循术语表中的译名
   - 保持上下文连贯性
   - 段落间过渡自然

**翻译与编辑标准**：
- ✅ 使用地道的中文表达，避免翻译腔
- ✅ 删除冗余词汇（如"你知道""其实""那个"等口语填充词）
- ✅ 保持专业性与可读性的平衡
- ✅ 句式简洁有力，避免冗长拖沓
- ❌ 禁止逐字直译
- ❌ 禁止保留英文原文插入

### 第四步：说话人核验
- 通读全文对话逻辑
- 根据上下文判断说话人标注是否正确
- 发现错误时：
  - 标记错误位置：`[原标注：XXX → 更正为：YYY]`
  - 在文中直接更正

### 第五步：内容清理
**删除以下无关内容**：
- "另请阅读""相关文章""延伸阅读"等推荐性文字
- 广告插入、订阅提示
- 网站导航、版权声明
- 社交媒体分享按钮文字

### 第六步：标题优化
- "Transcript" 统一翻译为：**"访谈全文"** 或 **"对话实录"**
- 禁止使用："抄本""誊本""记录稿"
- 标题应简洁有力，体现核心主题

---

## 📤 输出格式

### 如果是娱乐明星内容：
```
[已跳过：娱乐明星类内容]
```

### 如果是需处理的内容：
```
【术语表】
[列出所有关键术语]

【说话人更正记录】
[如有更正，列出更正内容；如无，写"无需更正"]

【清理内容记录】
[列出删除的无关内容类型]

---

【处理后正文】
[完整的编辑审核后文章]
```

---

## 🎯 质量标准检查清单
处理完成后，请自查：
- [ ] 术语表中的所有译名在全文中保持一致
- [ ] 没有"你知道""其实"等翻译腔残留
- [ ] 说话人标注与对话逻辑匹配
- [ ] 所有"另请阅读"等推广内容已清除
- [ ] 标题中的 Transcript 已正确翻译
- [ ] 全文表达流畅自然，符合中文阅读习惯
- [ ] 长文本拆分合理，过渡自然

---

## 💡 特别提示
- 人名首次出现时可注明身份（如：埃隆·马斯克，特斯拉CEO）
- 专业术语首次出现时可加简短解释
- 保留原文中的数据、引用的准确性
- 对于多人对话，确保说话人标识清晰明确

请开始处理文章。
    """
    text_chunks = split_text_by_length(text)
    
    if not text_chunks:
        return None

    # 步骤 1: 从第一个块创建术语表
    name_glossary = _create_name_glossary(text_chunks[0])

    # 步骤 2: 使用术语表翻译所有块
    translated_chunks = []
    print(f"\n--- 开始使用术语表翻译所有 {len(text_chunks)} 个文本块 ---")
    for i, chunk in enumerate(text_chunks, 1):
        print(f"\n--- 正在翻译第 {i}/{len(text_chunks)} 块 ---")
        translated_chunk = _translate_chunk(chunk, name_glossary)
        
        if translated_chunk:
            translated_chunks.append(translated_chunk)
        else:
            print(f"第 {i} 块翻译失败，跳过")

    if translated_chunks:
        final_translation = '\n\n'.join(translated_chunks)
        print(f"\n所有文本块翻译完成，合并后总长度: {len(final_translation)} 字符")
        return final_translation
    else:
        print("错误: 所有文本块翻译都失败了。")
        return None


def main_workflow():
    """主工作流程。每篇文章单独翻译、单独保存。优先本地缓存原始文章，避免重复翻译。"""
    print(f"\n--- 开始执行自动化任务 @ {datetime.now()} ---")

    today = datetime.now().strftime('%Y%m%d')
    raw_filename = f"all_articles_raw_{today}.txt"
    completed_file = f"completed_translations_{today}.json"

    completed_articles = []
    if os.path.exists(completed_file):
        try:
            with open(completed_file, 'r', encoding='utf-8') as f:
                completed_articles = json.load(f)
            print(f"已加载 {len(completed_articles)} 个已完成翻译的文章记录")
        except json.JSONDecodeError:
            print(f"WARN: {completed_file} 文件损坏或为空，将重新创建。")
            completed_articles = []

    all_articles_content = None
    if os.path.exists(raw_filename):
        print(f"检测到本地缓存 {raw_filename}，直接读取...")
        with open(raw_filename, 'r', encoding='utf-8') as f:
            all_articles_content = f.read()
    else:
        driver = setup_driver()
        if not driver:
            print("WebDriver初始化失败，无法继续。")
            return
        try:
            all_articles_content = get_todays_article_from_site1(driver, URL_SITE_1_ARTICLE)
            if not all_articles_content:
                print("未获取到任何原始文章。")
                return
            with open(raw_filename, 'w', encoding='utf-8') as f:
                f.write(all_articles_content)
                print(f"已保存原始文章到本地: {raw_filename}")
        finally:
            if driver:
                driver.quit()
                print("浏览器已关闭。")

    if not all_articles_content:
        print("没有可处理的文章内容。")
        return

    articles = all_articles_content.split('\n\n---\n\n')
    print(f"共需处理 {len(articles)} 篇文章。")

    for idx, article in enumerate(articles, 1):
        if not article.strip():
            continue

        first_line = article.split('\n')[0].strip().replace('#', '').strip()
        safe_first_line = re.sub(r'[\\/*?:"<>|]', "", first_line)[:50]
        
        if not safe_first_line:
            safe_first_line = f"无标题文章-{idx}"

        # 使用 safe_first_line 作为唯一标识
        if safe_first_line in completed_articles:
            print(f"文章 {idx} (标题: {safe_first_line}) 已存在于完成列表中，跳过。")
            continue
        
        # 检查Word文档是否已存在
        today_date_str = datetime.now().strftime("%Y-%m-%d")
        word_filename = f"{today_date_str}-{safe_first_line}.docx"
        word_filepath = os.path.join(SAVE_PATH, word_filename)
        if os.path.exists(word_filepath):
            print(f"文章 {idx} (标题: {safe_first_line}) 的Word文档已存在，跳过。")
            if safe_first_line not in completed_articles:
                 completed_articles.append(safe_first_line)
                 with open(completed_file, 'w', encoding='utf-8') as f:
                    json.dump(completed_articles, f, ensure_ascii=False, indent=2)
            continue

        print(f"\n--- 正在翻译第 {idx}/{len(articles)} 篇文章 (标题: {safe_first_line}) ---")

        translated_full_article_markdown = translate_text_with_deepseek_api(article)

        if translated_full_article_markdown:
            print(f"文章 {idx} 翻译完成。")

            html_snippet, full_html_content = convert_to_markdown_and_copy(translated_full_article_markdown)

            # 从翻译后的内容中重新获取标题，以防万一
            translated_first_line = translated_full_article_markdown.split('\n')[0].strip().replace('#', '').strip()
            safe_translated_title = re.sub(r'[\\/*?:"<>|]', "", translated_first_line)[:50] or safe_first_line


            html_file_path = save_to_html_file(full_html_content, safe_translated_title)

            save_to_markdown_file(translated_full_article_markdown, safe_translated_title)

            if html_file_path:
                save_to_word_document(html_file_path, safe_translated_title)
                completed_articles.append(safe_first_line) # 仍然用原始标题的标识记录
                with open(completed_file, 'w', encoding='utf-8') as f:
                    json.dump(completed_articles, f, ensure_ascii=False, indent=2)
                print(f"文章 {idx} 已保存并记录为已完成。")
            else:
                print(f"文章 {idx} 翻译成功但HTML文件保存失败，无法转换为Word。")
        else:
            print(f"文章 {idx} 翻译失败或内容为空，跳过保存。")

    print(f"\n--- 所有文章处理完毕 @ {datetime.now()} ---")

# --- 任务调度 ---
if __name__ == "__main__":
    main_workflow()

    schedule.every().day.at("08:05").do(main_workflow)
    print("任务已安排，将在每天08:05执行。")
    while True:
        schedule.run_pending()
        time.sleep(60)
