import time
from datetime import datetime, timedelta, timezone
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import os
import requests
import dateutil.parser
import platform

URL_SITE_1 = "https://singjupost.com"
JINA_READER_BASE = "https://r.jina.ai/"
RECENT_WINDOW_HOURS = 24
JINA_TIMEOUT_SECONDS = 60
PAGE_LOAD_TIMEOUT_SECONDS = 60

print("🔥 USING JINA READER + SELENIUM FALLBACK 🔥")

def fetch_with_jina(url: str, timeout: int = JINA_TIMEOUT_SECONDS) -> str | None:
    """
    使用 Jina Reader API 获取干净的文章内容

    Jina Reader 会自动：
    - 提取文章主体内容
    - 去除广告、导航栏等干扰
    - 转换为干净的 Markdown 格式

    参数:
        url: 文章 URL
        timeout: 请求超时时间（秒）

    返回:
        干净的 Markdown 内容，失败返回 None
    """
    jina_url = f"{JINA_READER_BASE}{url}"

    try:
        print(f"    🌐 尝试 Jina Reader: {url[:50]}...")

        # Jina Reader 支持的请求头
        headers = {
            "Accept": "text/markdown",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        }

        response = requests.get(jina_url, headers=headers, timeout=timeout)

        if response.status_code == 200:
            content = response.text.strip()

            # 检查内容是否有效（至少 200 字符）
            if len(content) > 200:
                print(f"    ✅ Jina Reader 成功: {len(content)} 字符")
                return content
            else:
                print(f"    ⚠️ Jina Reader 返回内容过短: {len(content)} 字符")
                return None
        else:
            print(f"    ⚠️ Jina Reader 请求失败: HTTP {response.status_code}")
            return None

    except requests.exceptions.Timeout:
        print(f"    ⚠️ Jina Reader 超时")
        return None
    except requests.exceptions.RequestException as e:
        print(f"    ⚠️ Jina Reader 请求异常: {e}")
        return None
    except Exception as e:
        print(f"    ⚠️ Jina Reader 未知错误: {e}")
        return None


def setup_driver():
    PROXY_URL = "http://127.0.0.1:7890" if platform.system() == "Darwin" else None
    if PROXY_URL:
        os.environ["HTTP_PROXY"] = PROXY_URL
        os.environ["HTTPS_PROXY"] = PROXY_URL
    else:
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("ALL_PROXY", None)
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"

    chrome_options = webdriver.ChromeOptions()
    if PROXY_URL:
        chrome_options.add_argument(f"--proxy-server={PROXY_URL}")
    
    # Anti-detection & Stability
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.page_load_strategy = 'eager'

    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
    return driver


def scroll_page(driver, pause=1.5, max_scroll=3): # Reduced scroll to speed up
    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(max_scroll):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height


def extract_article_with_selenium(driver, url: str) -> str | None:
    """
    使用 Selenium 提取文章内容（作为 Jina 的回退方案）

    参数:
        driver: Selenium WebDriver 实例
        url: 文章 URL

    返回:
        Markdown 格式的文章内容，失败返回 None
    """
    try:
        driver.get(url)

        # Handle "Continue Reading" button
        try:
            continue_button_xpath = "//button[contains(., 'Continue Reading') or contains(., 'Show More') or contains(., 'Load More')]"
            continue_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, continue_button_xpath))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", continue_button)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", continue_button)
            time.sleep(2)
        except TimeoutException:
            pass

        return extract_article_markdown(driver)

    except Exception as e:
        print(f"    ❌ Selenium 提取失败: {e}")
        return None


def extract_article_markdown(driver) -> str | None:
    try:
        # Try multiple selectors
        article = None
        for selector in ["article", ".entry-content", ".post-content", "main"]:
            try:
                article = driver.find_element(By.CSS_SELECTOR, selector)
                break
            except:
                continue
        
        if not article:
            return None
        
        # Get title first
        full_title = "Untitled"
        title_selectors = ["h1.entry-title", "h1.post-title", "h1"]
        for selector in title_selectors:
            try:
                title_element = driver.find_element(By.CSS_SELECTOR, selector)
                full_title = title_element.text.strip()
                if full_title:
                    break
            except Exception:
                continue

        elements = article.find_elements(
            By.XPATH,
            ".//h1 | .//h2 | .//h3 | .//p | .//blockquote"
        )

        lines = [f"# {full_title}", ""]
        
        for el in elements:
            text = el.text.strip()
            if not text:
                continue

            tag = el.tag_name.lower()
            if tag == "h1":
                 # Skip if it duplicates the title we already added
                 if text == full_title: continue
                 lines.append(f"# {text}")
            elif tag == "h2":
                lines.append(f"## {text}")
            elif tag == "h3":
                lines.append(f"### {text}")
            elif tag == "blockquote":
                lines.append(f"> {text}")
            else:
                lines.append(text)
            lines.append("")

        result = "\n".join(lines).strip()
        return result if len(result) > 200 else None # Consistent threshold
    except Exception as e:
        print(f"Error extracting markdown: {e}")
        return None


def fetch_latest_articles() -> list[str]:
    """
    抓取最新文章列表

    抓取策略：
    1. 使用 Selenium 获取文章列表页，筛选今天/昨天的文章 URL
    2. 对每篇文章，优先使用 Jina Reader 获取干净内容
    3. 如果 Jina 失败，回退到 Selenium 提取

    返回:
        文章内容列表（Markdown 格式）
    """
    driver = setup_driver()
    articles = []
    article_urls = []  # 先收集所有 URL

    try:
        print(f"Opening {URL_SITE_1}...")
        try:
            driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
            print(f"    ➡️ [Debug] 正在请求页面 (Timeout={PAGE_LOAD_TIMEOUT_SECONDS}s)...")
            driver.get(URL_SITE_1)
            print("    ✅ [Debug] 页面加载完成")
        except TimeoutException:
            print("    ⚠️ [Debug] 页面加载超时，强制继续...")
            driver.execute_script("window.stop();")
        except Exception as e:
            print(f"    ❌ [Debug] 页面加载出错: {e}")

        # --- Handle Cookie Consent ---
        try:
            time.sleep(2)
            cookie_selectors = [
                 "//button[contains(text(), 'Not consent')]",
                 "//button[contains(text(), 'Reject')]",
                 "button[data-testid='cookie-banner-reject']"
            ]
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
                    driver.execute_script("arguments[0].click();", cookie_button)
                    break
                 except TimeoutException:
                     continue
        except Exception:
            pass

        # --- Calculate Lower-Bound Time Window (UTC) ---
        now_utc = datetime.now(timezone.utc)
        cutoff_utc = now_utc - timedelta(hours=RECENT_WINDOW_HOURS)
        print(
            f"🕒 抓取发布时间 >= {cutoff_utc.isoformat()} "
            f"(回看 {RECENT_WINDOW_HOURS} 小时, 当前UTC {now_utc.isoformat()})"
        )

        # --- Scroll to load more ---
        scroll_page(driver, pause=1.5, max_scroll=5)

        # --- Find Articles ---
        article_elements = driver.find_elements(By.CSS_SELECTOR, "article.post")

        for article in article_elements:
            try:
                # Check date
                parsed_article_dt = None
                try:
                    date_element = article.find_element(By.CSS_SELECTOR, "time.entry-date")
                    article_datetime_str = date_element.get_attribute('datetime')
                    if article_datetime_str:
                        parsed_article_dt = dateutil.parser.parse(article_datetime_str)

                    if not parsed_article_dt:
                        inner_text_date_str = date_element.get_attribute('innerText').strip()
                        if inner_text_date_str:
                            parsed_article_dt = dateutil.parser.parse(inner_text_date_str)
                except Exception:
                    pass

                if parsed_article_dt:
                    if parsed_article_dt.tzinfo is None:
                        parsed_article_dt = parsed_article_dt.replace(tzinfo=timezone.utc)
                    parsed_article_utc = parsed_article_dt.astimezone(timezone.utc)
                else:
                    parsed_article_utc = None

                # 仅按下限过滤：发布时间 >= cutoff_utc
                if parsed_article_utc and parsed_article_utc >= cutoff_utc:
                    link_element = article.find_element(By.CSS_SELECTOR, "h2.entry-title a")
                    href = link_element.get_attribute("href")
                    if href:
                        article_urls.append(href)
            except Exception:
                continue

        # Remove duplicates
        article_urls = list(dict.fromkeys(article_urls))
        print(f"🔍 Found {len(article_urls)} potential links.")

        if not article_urls:
             print("⚠️ No links found matching criteria.")

        # --- Process each article: Jina first, Selenium fallback ---
        for url in article_urls:
            print(f"\n➡️ Processing: {url}")

            # 1. 优先尝试 Jina Reader
            content = fetch_with_jina(url)

            # 2. Jina 失败，回退到 Selenium
            if not content:
                print(f"    🔄 Jina 失败，使用 Selenium 回退...")
                content = extract_article_with_selenium(driver, url)

            # 3. 保存结果
            if content:
                print(f"    ✅ 成功获取 {len(content)} 字符")
                articles.append(content)
            else:
                print(f"    ❌ 两种方式都失败，跳过此文章")

    except Exception as e:
        print(f"Crawler fatal error: {e}")
    finally:
        driver.quit()

    return articles
