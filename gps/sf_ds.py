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
import sys
from datetime import datetime, timedelta
import traceback
from urllib.parse import parse_qs, urlparse

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

# 兼容从 Agent/gps 直接运行，补齐 src 模块搜索路径
_script_dir = os.path.dirname(os.path.abspath(__file__))
_candidate_module_roots = [
    os.path.dirname(_script_dir),
    os.path.join(os.path.dirname(_script_dir), "src"),
    _script_dir,
]
for _path in _candidate_module_roots:
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

# 导入您现有的辅助模块和配置文件
import singju_ds as gemini_helper
import config

try:
    from src.translator import translate_article as strict_translate_article
except Exception:
    try:
        from translator import translate_article as strict_translate_article
    except Exception:
        strict_translate_article = None

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
DEBUG_DIR = os.path.join(SCRIPT_ROOT, "podscribe_debug")
FAILED_LOG_FILE = os.path.join(SCRIPT_ROOT, "failed_transcripts.log")
TRANSLATE_MAX_RETRIES = int(os.getenv("PODSCRIBE_TRANSLATE_MAX_RETRIES", "5"))
TRANSLATE_RETRY_BASE_SECONDS = int(os.getenv("PODSCRIBE_TRANSLATE_RETRY_BASE_SECONDS", "15"))
LIST_PAGE_MAX_RETRIES = int(os.getenv("PODSCRIBE_LIST_PAGE_MAX_RETRIES", "3"))
REVIEW_MIN_RATIO = float(os.getenv("PODSCRIBE_REVIEW_MIN_RATIO", "0.85"))
REVIEW_RATIO_CHECK_MIN_SOURCE = int(os.getenv("PODSCRIBE_REVIEW_RATIO_CHECK_MIN_SOURCE", "1200"))


def _resolve_podscribe_save_path():
    env_path = os.getenv("PODSCRIBE_SAVE_PATH")
    default_path = os.path.join(SCRIPT_ROOT, "output", "podscribe")

    def _normalize(path_value):
        return os.path.abspath(os.path.expanduser(str(path_value)))

    if env_path:
        return _normalize(env_path), "env"

    config_path = getattr(config, "PODSCRIBE_SAVE_PATH", None)
    if config_path:
        normalized = _normalize(config_path)
        # VPS 运行时如果误读到 macOS 本地路径，强制回落到脚本目录下的 output。
        if SCRIPT_ROOT.startswith("/root/") and normalized.startswith("/Users/"):
            return default_path, "default_vps_override"
        return normalized, "config"

    return default_path, "default"


PODSCRIBE_SAVE_PATH, PODSCRIBE_SAVE_PATH_SOURCE = _resolve_podscribe_save_path()
os.makedirs(PODSCRIBE_SAVE_PATH, exist_ok=True)
config.PODSCRIBE_SAVE_PATH = PODSCRIBE_SAVE_PATH
logger.info(
    "Podscribe 保存目录已解析: %s (source=%s)",
    PODSCRIBE_SAVE_PATH,
    PODSCRIBE_SAVE_PATH_SOURCE,
)

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
    
    # 1) 优先解析带年份格式
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(clean_date_str, fmt).date()
        except ValueError:
            pass

    # 2) 解析无年份格式（M/D），并做跨年回推
    try:
        month_day = datetime.strptime(clean_date_str, "%m/%d")
        today = datetime.now().date()
        candidate = month_day.replace(year=today.year).date()

        # 若无年份日期被解析到“明显未来”，判定其属于上一年
        # 例如在 2026-03-10 看到 12/14，应回推为 2025-12-14
        if candidate > (today + timedelta(days=7)):
            candidate = candidate.replace(year=candidate.year - 1)
            logger.info(
                f"检测到无年份日期跨年回推: 原始='{clean_date_str}', "
                f"回推后='{candidate}'"
            )
        return candidate
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

def _build_transcript_unique_key(series_id, title):
    return _make_safe_key(f"{series_id}_{(title or '').strip()}")

def _build_output_basename(series_id, title):
    safe_title = re.sub(r'[\\/*?:"<>|]', "", (title or "")).strip()[:50]
    series_prefix = f"S{series_id}_"
    today_date_str = datetime.now().strftime("%Y-%m-%d")
    return f"{today_date_str}-{series_prefix}{safe_title}"

def _preserve_existing_text_if_better(existing_text, new_text, min_ratio):
    existing_len = len(existing_text or "")
    new_len = len(new_text or "")
    if existing_len <= 0 or new_len <= 0:
        return False, existing_len, new_len, 0.0

    ratio = new_len / max(1, existing_len)
    return new_len < existing_len and ratio < min_ratio, existing_len, new_len, ratio

def _install_copy_capture(driver):
    driver.execute_script("""
        window.__podscribeCopiedText = '';
        window.__podscribeCopyEventCount = 0;
        if (window.__podscribeCopyCaptureInstalled) {
            return;
        }
        window.__podscribeCopyCaptureInstalled = true;

        document.addEventListener('copy', function(event) {
            try {
                window.__podscribeCopyEventCount = (window.__podscribeCopyEventCount || 0) + 1;
                const text = event.clipboardData && event.clipboardData.getData('text/plain');
                if (text) {
                    window.__podscribeCopiedText = text;
                }
            } catch (err) {}
        }, true);

        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                const originalWriteText = navigator.clipboard.writeText.bind(navigator.clipboard);
                navigator.clipboard.writeText = async function(text) {
                    window.__podscribeCopiedText = text || '';
                    return originalWriteText(text);
                };
            }
        } catch (err) {}
    """)

def _read_clipboard_text(driver):
    try:
        return driver.execute_async_script("""
            const done = arguments[0];
            try {
                if (window.__podscribeCopiedText && window.__podscribeCopiedText.length > 0) {
                    done(window.__podscribeCopiedText);
                    return;
                }
                if (!navigator.clipboard || !navigator.clipboard.readText) {
                    done('');
                    return;
                }
                navigator.clipboard.readText().then(
                    text => done(text || ''),
                    () => done('')
                );
            } catch (err) {
                done('');
            }
        """)
    except Exception:
        return ""

def _get_copy_capture_meta(driver):
    try:
        meta = driver.execute_script("""
            return {
                copiedTextLength: (window.__podscribeCopiedText || '').length,
                copyEventCount: window.__podscribeCopyEventCount || 0
            };
        """) or {}
        return {
            "copied_text_length": int(meta.get("copiedTextLength", 0) or 0),
            "copy_event_count": int(meta.get("copyEventCount", 0) or 0),
        }
    except Exception:
        return {"copied_text_length": 0, "copy_event_count": 0}

def _copy_transcript_container_via_selection(driver, series_name):
    logger.info(f"[{series_name}] 尝试对 transcript 容器执行选中复制...")
    copied = driver.execute_script("""
        try {
            const container = document.querySelector('#transcriptContainerContainer div[data-slate-editor="true"]');
            if (!container) return false;
            const selection = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(container);
            selection.removeAllRanges();
            selection.addRange(range);
            const ok = document.execCommand('copy');
            selection.removeAllRanges();
            return !!ok;
        } catch (err) {
            return false;
        }
    """)
    logger.info(f"[{series_name}] transcript 容器选中复制结果: {bool(copied)}")
    return bool(copied)

def _parse_episode_context_from_current_url(driver):
    current_url = driver.current_url or ""
    parsed = urlparse(current_url)
    match = re.search(r"/episode/(\d+)", parsed.path)
    if not match:
        return None
    query = parse_qs(parsed.query)
    transcript_version_req_id = (query.get("transcriptVersionReqId") or [None])[0]
    if not transcript_version_req_id:
        return None
    return {
        "episode_id": int(match.group(1)),
        "transcript_version_req_id": transcript_version_req_id,
        "current_url": current_url,
    }

def _flatten_transcript_payload(payload):
    lines = []
    seen = set()
    ignored_keys = {
        "id", "uuid", "ts", "start", "end", "startTime", "endTime",
        "speaker", "speakerName", "status", "meta", "metadata", "type",
        "createdAt", "updatedAt", "episodeId", "seriesId", "transcriptVersionReqId",
    }
    transcript_like_keys = [
        "originalText", "text", "transcript", "paragraphs",
        "segments", "items", "children", "words"
    ]
    wrapper_keys = [
        "data", "payload", "result", "response", "body",
        "transcription", "transcriptPayload", "transcriptData"
    ]
    segment_text_keys = ("phrase", "value", "content", "text")
    word_item_keys = ("word", "punctuated", "normalized")
    segment_meta_keys = ignored_keys | {
        "confidence", "speakerId", "role", "lang", "language",
        "index", "offset", "duration", "kind", "display",
        "punctuated", "normalized", "word", "words"
    }

    def append_line(value):
        text = (value or "").strip()
        if not text:
            return
        if text in seen:
            return
        seen.add(text)
        lines.append(text)

    def is_segment_text_dict(node):
        if not isinstance(node, dict):
            return False
        present_text_keys = [key for key in segment_text_keys if isinstance(node.get(key), str)]
        if len(present_text_keys) != 1:
            return False
        if len(node) > 8:
            return False
        extra_keys = set(node.keys()) - set(segment_text_keys)
        return extra_keys.issubset(segment_meta_keys)

    def list_to_word_text(node):
        if not isinstance(node, list) or not node:
            return None
        word_items = []
        for item in node:
            if not isinstance(item, dict):
                return None
            token = None
            for key in word_item_keys:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    token = value.strip()
                    break
            if token is None:
                return None
            word_items.append(token)
        if len(word_items) < 20:
            return None
        text = " ".join(word_items)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        text = re.sub(r"\(\s+", "(", text)
        text = re.sub(r"\s+\)", ")", text)
        text = re.sub(r"\s+'", "'", text)
        return text.strip()

    def walk(node):
        if node is None:
            return
        if isinstance(node, str):
            text = node.strip()
            if not text:
                return
            if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
                try:
                    walk(json.loads(text))
                    return
                except Exception:
                    pass
            append_line(text)
            return
        if isinstance(node, (int, float, bool)):
            return
        if isinstance(node, list):
            word_text = list_to_word_text(node)
            if word_text:
                append_line(word_text)
                return
            for item in node:
                walk(item)
            return
        if isinstance(node, dict):
            if is_segment_text_dict(node):
                for key in segment_text_keys:
                    if isinstance(node.get(key), str):
                        append_line(node.get(key))
                        break
                return

            used_transcript_key = False
            for key in transcript_like_keys:
                if key in node:
                    walk(node.get(key))
                    used_transcript_key = True
            if used_transcript_key:
                return
            return

    candidate_payloads = []

    def collect_candidates(node, depth=0):
        if node is None or depth > 4:
            return
        if isinstance(node, str):
            candidate_payloads.append(node)
            return
        if isinstance(node, list):
            if node:
                candidate_payloads.append(node)
            return
        if not isinstance(node, dict):
            return

        for key in transcript_like_keys:
            if key in node and node.get(key) is not None:
                candidate_payloads.append(node.get(key))

        for key in wrapper_keys:
            if key in node and node.get(key) is not None:
                collect_candidates(node.get(key), depth + 1)

    collect_candidates(payload)
    if not candidate_payloads:
        candidate_payloads.append(payload)

    best_text = ""
    for candidate in candidate_payloads:
        if candidate is None:
            continue
        lines.clear()
        seen.clear()
        walk(candidate)
        text = "\n".join(lines).strip()
        if len(text) > len(best_text):
            best_text = text

    if best_text:
        return best_text
    return ""


def _summarize_transcript_payload(node, depth=0, max_depth=3):
    if depth > max_depth:
        return "..."
    if node is None:
        return None
    if isinstance(node, str):
        return {"type": "str", "len": len(node)}
    if isinstance(node, bool):
        return {"type": "bool"}
    if isinstance(node, (int, float)):
        return {"type": type(node).__name__}
    if isinstance(node, list):
        summary = {"type": "list", "len": len(node)}
        if node and depth < max_depth:
            summary["sample"] = _summarize_transcript_payload(node[0], depth + 1, max_depth)
            summary["samples"] = [
                _summarize_transcript_payload(item, depth + 1, max_depth)
                for item in node[:3]
            ]
            if all(isinstance(item, str) for item in node[:5]):
                summary["sample_values"] = [item[:80] for item in node[:5]]
        return summary
    if isinstance(node, dict):
        summary = {"type": "dict", "keys": len(node)}
        if depth < max_depth:
            children = {}
            for key in list(node.keys())[:20]:
                try:
                    children[key] = _summarize_transcript_payload(node.get(key), depth + 1, max_depth)
                except Exception:
                    children[key] = "error"
            summary["fields"] = children
        return summary
    return {"type": type(node).__name__}


def _save_transcript_debug_artifacts(series_name, context, result):
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        stem = _make_safe_key(
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
            f"{context.get('series_id', 'unknown')}_{context.get('episode_id', 'unknown')}"
        )
        meta = {
            "series_name": series_name,
            "context": context,
            "strategy": result.get("strategy"),
            "rawLength": result.get("rawLength"),
            "debug": result.get("debug"),
            "payload_summary": _summarize_transcript_payload(result.get("payload")),
        }
        meta_path = os.path.join(DEBUG_DIR, f"{stem}_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        raw_text = result.get("rawText")
        if isinstance(raw_text, str) and raw_text:
            raw_path = os.path.join(DEBUG_DIR, f"{stem}_raw.json")
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(raw_text)

        logger.info(f"[{series_name}] 已保存 transcript API 调试文件: {meta_path}")
    except Exception as exc:
        logger.warning(f"[{series_name}] 保存 transcript API 调试文件失败: {exc}")


def _assess_transcript_text_quality(text):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return {
            "line_count": 0,
            "encoded_line_count": 0,
            "encoded_line_ratio": 0.0,
            "sample_encoded_lines": [],
            "suspicious": True,
        }

    encoded_pattern = re.compile(r"^[A-Za-z0-9]+(?:\|[A-Za-z0-9]+){2,}$")
    encoded_lines = [line for line in lines if encoded_pattern.match(line)]
    ratio = len(encoded_lines) / max(1, len(lines))
    return {
        "line_count": len(lines),
        "encoded_line_count": len(encoded_lines),
        "encoded_line_ratio": round(ratio, 4),
        "sample_encoded_lines": encoded_lines[:8],
        "suspicious": ratio >= 0.03 or len(encoded_lines) >= 20,
    }

def _extract_transcript_via_api(driver, series_name):
    context = _parse_episode_context_from_current_url(driver)
    if not context:
        raise TimeoutException("episode context not found in current url")

    logger.info(
        f"[{series_name}] 优先尝试通过 transcript API 提取全文..."
        f" (episode_id={context['episode_id']})"
    )

    result = driver.execute_async_script("""
        const episodeId = arguments[0];
        const transcriptVersionReqId = arguments[1];
        const done = arguments[arguments.length - 1];
        (async () => {
            const apiUrl = `/api/episode/${episodeId}/transcription?transcriptVersionReqId=${encodeURIComponent(transcriptVersionReqId)}&bypassTruncation=true`;
            const finalize = (payload, strategy, rawLength, rawText = '') => done({
                ok: true,
                payload,
                strategy,
                rawLength,
                rawText,
            });
            const collectDecoderCandidates = async () => {
                const candidates = [];
                const scriptUrls = Array.from(document.scripts)
                    .map((s) => s.src)
                    .filter((src) => src && src.includes('/assets/') && src.endsWith('.js'));
                for (const scriptUrl of scriptUrls) {
                    try {
                        const mod = await import(scriptUrl);
                        for (const [exportName, value] of Object.entries(mod)) {
                            if (!value) continue;
                            if (typeof value === 'function') {
                                let src = '';
                                try {
                                    src = Function.prototype.toString.call(value);
                                } catch (err) {}
                                if (src.includes('decompress') || src.includes('inflate')) {
                                    candidates.push({ exportName, methodName: null, fn: value });
                                }
                                continue;
                            }
                            if (typeof value === 'object') {
                                for (const methodName of ['decompress', 'decompressFromUTF16', 'decompressFromBase64', 'inflate', 'decode', 'parse', 'deserialize']) {
                                    if (typeof value[methodName] === 'function') {
                                        candidates.push({ exportName, methodName, fn: value[methodName].bind(value) });
                                    }
                                }
                            }
                        }
                    } catch (err) {}
                }
                return candidates;
            };
            const tryDecodeStructuredReferenceGraph = (payload) => {
                if (!Array.isArray(payload) || payload.length !== 2) return null;
                const [table, rootRef] = payload;
                if (!Array.isArray(table) || !table.length || typeof rootRef !== 'string') return null;
                if (!table.every((item) => typeof item === 'string')) return null;

                const alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
                const cache = new Map();
                const maxIndex = table.length - 1;

                const decodeIndex = (token) => {
                    if (!token || typeof token !== 'string') return null;
                    let value = 0;
                    for (const ch of token) {
                        const idx = alphabet.indexOf(ch);
                        if (idx < 0) return null;
                        value = value * alphabet.length + idx;
                    }
                    return value <= maxIndex ? value : null;
                };

                const parseNumberToken = (raw) => {
                    if (raw === '0') return 0;
                    if (/^-?\\d+(?:\\.\\d+)?$/.test(raw)) {
                        const n = Number(raw);
                        return Number.isFinite(n) ? n : raw;
                    }
                    return raw;
                };

                const decodeValue = (token) => {
                    const idx = decodeIndex(token);
                    if (idx == null) return token;
                    return decodeEntry(idx);
                };

                const decodeEntry = (idx) => {
                    if (cache.has(idx)) return cache.get(idx);
                    const raw = table[idx];
                    if (typeof raw !== 'string') return raw;

                    if (raw.startsWith('a|')) {
                        const placeholder = [];
                        cache.set(idx, placeholder);
                        const parts = raw.split('|').slice(1);
                        for (const part of parts) {
                            placeholder.push(decodeValue(part));
                        }
                        return placeholder;
                    }

                    if (raw.startsWith('o|')) {
                        const placeholder = {};
                        cache.set(idx, placeholder);
                        const parts = raw.split('|').slice(1);
                        if (!parts.length) {
                            return placeholder;
                        }

                        const maybeKeys = decodeValue(parts[0]);
                        if (
                            Array.isArray(maybeKeys)
                            && maybeKeys.length === parts.length - 1
                            && maybeKeys.every((item) => typeof item === 'string')
                        ) {
                            maybeKeys.forEach((key, valueIdx) => {
                                placeholder[key] = decodeValue(parts[valueIdx + 1]);
                            });
                            return placeholder;
                        }

                        for (let i = 0; i + 1 < parts.length; i += 2) {
                            const key = decodeValue(parts[i]);
                            const value = decodeValue(parts[i + 1]);
                            placeholder[String(key)] = value;
                        }
                        return placeholder;
                    }

                    if (raw.startsWith('n|')) {
                        const parsed = parseNumberToken(raw.slice(2));
                        cache.set(idx, parsed);
                        return parsed;
                    }

                    cache.set(idx, raw);
                    return raw;
                };

                const decodedRoot = decodeValue(rootRef);
                if (!decodedRoot || typeof decodedRoot !== 'object') return null;
                return {
                    ok: true,
                    payload: decodedRoot,
                    strategy: 'structured_graph',
                    debug: {
                        rootRef,
                        rootIndex: decodeIndex(rootRef),
                        tableLength: table.length,
                    },
                };
            };
            const tryDecodeStructuredPayload = (payload) => {
                if (!Array.isArray(payload) || payload.length !== 2) return null;
                const [rows] = payload;
                if (!Array.isArray(rows) || rows.length < 10) return null;
                if (!rows.every((item) => typeof item === 'string')) return null;
                const isHeaderLike = (value) => (
                    typeof value === 'string'
                    && /^[A-Za-z_][A-Za-z0-9_]*$/.test(value)
                    && value.length <= 40
                    && !/^https?:/i.test(value)
                );
                const headers = [];
                for (const value of rows) {
                    if (!isHeaderLike(value)) break;
                    if (headers.includes(value)) break;
                    headers.push(value);
                    if (headers.length >= 32) break;
                }
                if (headers.length < 3) return null;
                const textColumnIndex = headers.indexOf('text');
                if (textColumnIndex < 0) return null;

                const rowWidth = headers.length;
                const dataStart = rowWidth;
                const reservedValues = new Set([
                    ...headers,
                    'done', 'starttime', 'endtime', 'speaker', 'word', 'confidence',
                    'status', 'diarization', 'transcript_s3_url', 'createdat', 'url',
                    'text', 'id', 'stage'
                ]);
                const isHumanToken = (value) => {
                    if (typeof value !== 'string') return false;
                    const text = value.trim();
                    if (!text) return false;
                    if (reservedValues.has(text.toLowerCase())) return false;
                    if (/^https?:/i.test(text)) return false;
                    if (/\\.mp3(?:$|[?#])/i.test(text)) return false;
                    if (/^[A-Za-z0-9]+(?:\\|[A-Za-z0-9.]+){1,}$/.test(text)) return false;
                    if (/^[A-Za-z]\\|/.test(text)) return false;
                    if (/^[noa]\\|/i.test(text)) return false;
                    if (/^[A-Za-z0-9_-]{8,}$/.test(text) && !/[aeiouAEIOU]/.test(text)) return false;
                    if (/^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}/.test(text)) return false;
                    return true;
                };
                const joinTokens = (tokens) => tokens
                    .join(' ')
                    .replace(/\\s+([,.;:!?])/g, '$1')
                    .replace(/\\(\\s+/g, '(')
                    .replace(/\\s+\\)/g, ')')
                    .trim();
                const collectedTokens = [];
                const sampleRows = [];
                const sampleTextValues = [];
                for (let offset = dataStart; offset + textColumnIndex < rows.length; offset += rowWidth) {
                    if (sampleRows.length < 5) {
                        const row = {};
                        for (let i = 0; i < rowWidth && offset + i < rows.length; i++) {
                            row[headers[i]] = rows[offset + i];
                        }
                        sampleRows.push(row);
                    }
                    const value = rows[offset + textColumnIndex];
                    if (typeof value !== 'string') continue;
                    if (sampleTextValues.length < 8) {
                        sampleTextValues.push(value);
                    }
                    for (let i = 0; i < rowWidth && offset + i < rows.length; i++) {
                        const rowValue = rows[offset + i];
                        if (!isHumanToken(rowValue)) continue;
                        collectedTokens.push(rowValue.trim());
                    }
                }
                if (collectedTokens.length < 50) return null;
                return {
                    transcript: joinTokens(collectedTokens),
                    debug: {
                        headers,
                        rowWidth,
                        textColumnIndex,
                        sampleRows,
                        sampleTextValues,
                        sampleCollectedTokens: collectedTokens.slice(0, 40),
                    },
                };
            };
            const tryStructuredRawObject = (payload) => {
                const decoded = tryDecodeStructuredPayload(payload);
                if (!decoded) return null;
                return {
                    ok: true,
                    payload: decoded,
                    strategy: 'structured_rows',
                    debug: decoded.debug || null,
                };
            };
            const looksLikeTranscriptPayload = (payload) => {
                if (!payload) return false;
                if (typeof payload === 'string') return payload.length > 1000;
                if (Array.isArray(payload)) return false;
                if (typeof payload === 'object') {
                    return ['text', 'transcript', 'paragraphs', 'segments', 'items', 'originalText']
                        .some((key) => payload[key] != null);
                }
                return false;
            };
            const tryDecodePayload = async (input, rawLength, candidates) => {
                for (const candidate of candidates) {
                    try {
                        const decoded = await candidate.fn(input);
                        if (!decoded) continue;
                        if (typeof decoded === 'string') {
                            try {
                                return {
                                    ok: true,
                                    payload: JSON.parse(decoded),
                                    strategy: `${candidate.exportName}.${candidate.methodName || 'fn'}`,
                                    rawLength,
                                };
                            } catch (err) {
                                if (decoded.startsWith('{') || decoded.startsWith('[')) {
                                    return {
                                        ok: true,
                                        payload: decoded,
                                        strategy: `${candidate.exportName}.${candidate.methodName || 'fn'}`,
                                        rawLength,
                                    };
                                }
                            }
                        } else if (typeof decoded === 'object') {
                            return {
                                ok: true,
                                payload: decoded,
                                strategy: `${candidate.exportName}.${candidate.methodName || 'fn'}`,
                                rawLength,
                            };
                        }
                    } catch (err) {}
                }
                return null;
            };
            try {
                const response = await fetch(apiUrl, {
                    credentials: 'include',
                    headers: { 'Accept': 'application/json, text/plain, */*' },
                });
                const rawText = await response.text();
                const rawLength = (rawText || '').length;
                if (!response.ok) {
                    done({ ok: false, error: `HTTP ${response.status}`, rawLength });
                    return;
                }
                if (!rawText) {
                    done({ ok: false, error: 'empty transcript api body', rawLength: 0 });
                    return;
                }

                let parsedPayload = null;
                try {
                    parsedPayload = JSON.parse(rawText);
                } catch (err) {}

                const candidates = await collectDecoderCandidates();

                if (parsedPayload !== null) {
                    const structuredGraph = tryDecodeStructuredReferenceGraph(parsedPayload);
                    if (structuredGraph) {
                        done({ ...structuredGraph, rawLength, rawText });
                        return;
                    }
                    const decodedParsed = await tryDecodePayload(parsedPayload, rawLength, candidates);
                    if (decodedParsed) {
                        done({ ...decodedParsed, rawText });
                        return;
                    }
                    const structuredParsed = tryStructuredRawObject(parsedPayload);
                    if (structuredParsed) {
                        done({ ...structuredParsed, rawLength, rawText });
                        return;
                    }
                    if (looksLikeTranscriptPayload(parsedPayload)) {
                        finalize(parsedPayload, 'raw_json', rawLength, rawText);
                        return;
                    }
                }

                const decodedRaw = await tryDecodePayload(rawText, rawLength, candidates);
                if (decodedRaw) {
                    done({ ...decodedRaw, rawText });
                    return;
                }

                done({
                    ok: false,
                    error: 'no transcript api decoder matched',
                    rawLength,
                    rawPreview: rawText.slice(0, 200),
                });
            } catch (err) {
                done({
                    ok: false,
                    error: String(err && err.message ? err.message : err),
                    stack: String(err && err.stack ? err.stack : ''),
                });
            }
        })();
    """, context["episode_id"], context["transcript_version_req_id"])

    if not isinstance(result, dict) or not result.get("ok"):
        error = result.get("error") if isinstance(result, dict) else result
        raise TimeoutException(f"transcript api fetch failed: {error}")

    if result.get("strategy") == "structured_rows":
        _save_transcript_debug_artifacts(series_name, context, result)

    article_content = _flatten_transcript_payload(result.get("payload"))
    if len(article_content) < 1000:
        logger.warning(
            f"[{series_name}] transcript API payload 摘要(too_short): "
            f"{json.dumps(_summarize_transcript_payload(result.get('payload')), ensure_ascii=False)[:4000]}"
        )
        raise TimeoutException(
            f"transcript api payload too short after flatten: {len(article_content)}"
        )
    raw_len = result.get("rawLength") or 0
    if raw_len and len(article_content) / raw_len > 0.35:
        logger.warning(
            f"[{series_name}] transcript API payload 摘要(too_large): "
            f"{json.dumps(_summarize_transcript_payload(result.get('payload')), ensure_ascii=False)[:4000]}"
        )
        raise TimeoutException(
            f"transcript api payload suspiciously large after flatten: "
            f"{len(article_content)}/{raw_len}"
        )

    quality = _assess_transcript_text_quality(article_content)
    if quality["suspicious"]:
        logger.warning(
            f"[{series_name}] transcript API 正文质量可疑: "
            f"{json.dumps(quality, ensure_ascii=False)[:4000]}"
        )
        debug_meta = result.get("debug")
        if debug_meta:
            logger.warning(
                f"[{series_name}] transcript API structured_rows 调试: "
                f"{json.dumps(debug_meta, ensure_ascii=False)[:4000]}"
            )
        raise TimeoutException("structured_rows extracted encoded rows instead of transcript text")

    logger.info(
        f"[{series_name}] transcript API 提取成功，长度: {len(article_content)} 字符。"
        f" (strategy={result.get('strategy')}, raw_len={result.get('rawLength')})"
    )
    return article_content


def _get_transcript_text_node(driver):
    try:
        return driver.find_element(By.CSS_SELECTOR, "#transcriptContainerContainer div[data-slate-editor='true']")
    except Exception:
        return driver.find_element(By.CSS_SELECTOR, "#transcriptContainerContainer")


def _extract_transcript_from_dom_deep(driver):
    extract_js = r"""
    const root = document.querySelector('#transcriptContainerContainer');
    if (!root) return '';

    const lines = [];
    const seen = new Set();

    const addLine = (value) => {
      const text = (value || '').trim();
      if (!text) return;
      if (text.length > 4000) return;
      if (seen.has(text)) return;
      seen.add(text);
      lines.push(text);
    };

    for (const node of root.querySelectorAll('[data-paragraph-text]')) {
      addLine(node.getAttribute('data-paragraph-text'));
    }

    const selectors = [
      '[data-slate-string="true"]',
      '[data-slate-node="text"]',
      '[data-slate-node="element"]',
      'p',
      'li',
      'h1,h2,h3,h4,h5,h6',
      'div'
    ];

    for (const sel of selectors) {
      const nodes = root.querySelectorAll(sel);
      for (const n of nodes) {
        addLine(n.innerText || n.textContent || '');
      }
    }

    return lines.join('\\n');
    """
    try:
        text = driver.execute_script(extract_js) or ""
        return text.strip()
    except Exception:
        return ""


def _extract_transcript_via_copy_button(driver, wait, series_name):
    logger.info(f"[{series_name}] 优先尝试通过 Copy Transcript 按钮提取全文...")
    _install_copy_capture(driver)

    copy_button = driver.execute_script("""
        const attrCandidates = Array.from(document.querySelectorAll(
          'button,[role="button"],div,span,a,[aria-label],[title],[data-tooltip]'
        ));
        const attrPatterns = ['copy transcript', 'copy to clipboard'];
        const visible = (el) => {
          const style = window.getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        for (const el of attrCandidates) {
          const haystack = [
            el.getAttribute('aria-label') || '',
            el.getAttribute('title') || '',
            el.getAttribute('data-tooltip') || '',
            el.innerText || '',
            el.textContent || ''
          ].join(' ').toLowerCase();
          if (attrPatterns.some(p => haystack.includes(p)) && visible(el)) {
            return el;
          }
        }

        const copyPath = document.querySelector(
          'svg path[d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12zm-1 4 6 6v10c0 1.1-.9 2-2 2H7.99C6.89 23 6 22.1 6 21l.01-14c0-1.1.89-2 1.99-2zm-1 7h5.5L14 6.5z"]'
        );
        if (!copyPath) return null;

        const candidate = copyPath.closest('button,[role="button"],div,span,a') || copyPath.parentElement;
        if (candidate && visible(candidate)) {
          return candidate;
        }
        return null;
    """)

    if not copy_button:
        raise TimeoutException("copy transcript button not found")

    driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", copy_button)
    time.sleep(1)
    try:
        driver.execute_script(
            "arguments[0].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));",
            copy_button,
        )
        driver.execute_script(
            "arguments[0].dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));",
            copy_button,
        )
    except Exception:
        pass
    time.sleep(0.5)
    try:
        copy_button.click()
    except Exception:
        driver.execute_script("arguments[0].click();", copy_button)

    copied_text = ""
    stable_rounds = 0
    last_len = 0
    deadline = time.time() + 12

    while time.time() < deadline:
        copied_text = (_read_clipboard_text(driver) or "").strip()
        current_len = len(copied_text)
        if current_len >= 500:
            if current_len == last_len:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_len = current_len
            if stable_rounds >= 2:
                logger.info(f"[{series_name}] Copy Transcript 提取成功，长度: {current_len} 字符。")
                return copied_text
        time.sleep(1)

    copy_meta = _get_copy_capture_meta(driver)
    logger.warning(
        f"[{series_name}] Copy 按钮点击后未拿到稳定剪贴板文本 "
        f"(copy_events={copy_meta['copy_event_count']}, copied_text_length={copy_meta['copied_text_length']})"
    )

    if _copy_transcript_container_via_selection(driver, series_name):
        copied_text = ""
        stable_rounds = 0
        last_len = 0
        deadline = time.time() + 10
        while time.time() < deadline:
            copied_text = (_read_clipboard_text(driver) or "").strip()
            current_len = len(copied_text)
            if current_len >= 500:
                if current_len == last_len:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                    last_len = current_len
                if stable_rounds >= 2:
                    logger.info(f"[{series_name}] transcript 容器选中复制成功，长度: {current_len} 字符。")
                    return copied_text
            time.sleep(1)

    raise TimeoutException("copy transcript button did not yield stable clipboard text")

def _extract_transcript_from_dom(driver, wait, series_name):
    logger.info(f"[{series_name}] 回退到 DOM 提取文稿文本（虚拟滚动累积模式）...")
    container_selector = "#transcriptContainerContainer"
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, container_selector)))

    all_lines = []
    seen_lines = set()
    scroll_step = 350
    scroll_top = 0
    no_new_rounds = 0
    max_rounds = 800

    for _ in range(max_rounds):
        batch = driver.execute_script("""
            const container = document.querySelector('#transcriptContainerContainer');
            if (!container) return [];
            const texts = [];
            const seen = new Set();
            const pushText = (value) => {
                const t = (value || '').trim();
                if (!t) return;
                if (t.length > 4000) return;
                if (seen.has(t)) return;
                seen.add(t);
                texts.push(t);
            };

            for (const node of container.querySelectorAll('[data-paragraph-text]')) {
                pushText(node.getAttribute('data-paragraph-text'));
            }

            const nodes = container.querySelectorAll(
                'div[data-slate-editor="true"] [data-slate-leaf="true"] span,' +
                'div[data-slate-editor="true"] p,' +
                'div[data-slate-editor="true"] div[data-slate-node="element"],' +
                '#transcriptContainerContainer p'
            );
            nodes.forEach((n) => pushText(n.innerText || n.textContent || ''));
            return texts;
        """) or []

        added = 0
        for line in batch:
            line = line.strip()
            if line and line not in seen_lines:
                seen_lines.add(line)
                all_lines.append(line)
                added += 1

        if added == 0:
            no_new_rounds += 1
        else:
            no_new_rounds = 0

        if no_new_rounds >= 6:
            logger.info(f"[{series_name}] 虚拟滚动已到底，累计收集 {len(all_lines)} 行。")
            break

        scroll_top += scroll_step
        driver.execute_script(
            "const c = document.querySelector('#transcriptContainerContainer');"
            "if (c) c.scrollTop = arguments[0];"
            "window.scrollBy(0, arguments[1]);",
            scroll_top,
            max(scroll_step, 600),
        )
        time.sleep(0.25)

    article_content = "\n".join(all_lines).strip()
    deep_text = _extract_transcript_from_dom_deep(driver)
    if len(deep_text) > len(article_content):
        article_content = deep_text

    if not article_content or len(article_content) < 200:
        raise TimeoutException("dom transcript content not available or too short")

    logger.info(f"[{series_name}] DOM 虚拟滚动提取完成，长度: {len(article_content)} 字符。")
    return article_content

def _get_pending_source_path(unique_key):
    if not os.path.exists(PENDING_DIR):
        os.makedirs(PENDING_DIR)
    return os.path.join(PENDING_DIR, f"{_make_safe_key(unique_key)}.md")

def save_pending_source(unique_key, payload):
    """保存待翻译原文，供网络失败后断点续跑。"""
    path = _get_pending_source_path(unique_key)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing_payload = f.read()
            keep_existing, existing_len, new_len, ratio = _preserve_existing_text_if_better(
                existing_payload,
                payload,
                0.8,
            )
            if keep_existing:
                logger.warning(
                    f"pending 原文保护生效，保留较长缓存: {path} "
                    f"({new_len}/{existing_len}={ratio:.3f})"
                )
                return path
        except Exception as exc:
            logger.warning(f"读取已有 pending 失败，继续覆盖 {path}: {exc}")
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


def _extract_title_from_pending_payload(payload, fallback_title):
    text = (payload or "").strip()
    if not text:
        return fallback_title

    first_line = text.splitlines()[0].strip()
    if first_line.startswith("#"):
        title = first_line.lstrip("#").strip()
        if title:
            return title
    return fallback_title


def _get_pending_transcripts_for_series(series_config, processed_titles):
    entries = []
    if not os.path.isdir(PENDING_DIR):
        return entries

    series_id = str(series_config["series_id"])
    prefix = f"{series_id}_"

    for filename in sorted(os.listdir(PENDING_DIR)):
        if not filename.endswith(".md"):
            continue
        safe_key = filename[:-3]
        if not safe_key.startswith(prefix):
            continue
        if safe_key in processed_titles:
            continue

        pending_path = os.path.join(PENDING_DIR, filename)
        try:
            with open(pending_path, "r", encoding="utf-8") as f:
                pending_payload = f.read()
        except Exception as exc:
            logger.warning(f"[{series_config['name']}] 读取 pending 失败，跳过 {pending_path}: {exc}")
            continue

        fallback_title = safe_key[len(prefix):].replace("_", " ").strip() or safe_key
        title = _extract_title_from_pending_payload(pending_payload, fallback_title)
        entries.append({
            "title": title,
            "series_id": series_id,
            "series_name": series_config["name"],
            "series_url": series_config["url"],
            "unique_key": _build_transcript_unique_key(series_id, title),
            "pending_path": pending_path,
            "pending_payload": pending_payload,
        })

    return entries

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
            if strict_translate_article:
                translated_markdown = strict_translate_article(text_to_translate)
            else:
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


def _is_output_complete_enough(source_text, candidate_text, min_ratio, min_source_len):
    source_len = len(source_text or "")
    candidate_len = len(candidate_text or "")
    if candidate_len <= 0:
        return False, source_len, candidate_len, 0.0

    ratio = candidate_len / max(1, source_len)
    if source_len < min_source_len:
        return True, source_len, candidate_len, ratio
    return ratio >= min_ratio, source_len, candidate_len, ratio


def _contains_excessive_english(candidate_text):
    """拦截明显未翻完的英文段落，避免中英混排结果落盘。"""
    text = (candidate_text or "").strip()
    if not text:
        return True, {"reason": "empty"}

    total_chars = len(text)
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    ascii_letters = len(re.findall(r"[A-Za-z]", text))

    suspicious_lines = []
    suspicious_chars = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue

        words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", line)
        line_cjk = len(re.findall(r"[\u4e00-\u9fff]", line))
        line_alpha = len(re.findall(r"[A-Za-z]", line))

        # 允许少量人名、术语和标题英文，但不允许整段英文正文漏翻。
        if len(words) >= 8 and line_alpha >= 40 and line_cjk <= 6:
            suspicious_lines.append(line[:120])
            suspicious_chars += len(line)

    ascii_ratio = ascii_letters / max(1, total_chars)
    cjk_ratio = cjk_chars / max(1, total_chars)

    has_excessive_english = (
        suspicious_chars >= 200
        or len(suspicious_lines) >= 3
        or (ascii_letters >= 1200 and cjk_ratio < 0.12)
        or (ascii_ratio >= 0.55 and cjk_chars < 400)
    )

    return has_excessive_english, {
        "total_chars": total_chars,
        "cjk_chars": cjk_chars,
        "ascii_letters": ascii_letters,
        "ascii_ratio": round(ascii_ratio, 4),
        "cjk_ratio": round(cjk_ratio, 4),
        "suspicious_line_count": len(suspicious_lines),
        "suspicious_chars": suspicious_chars,
        "sample": suspicious_lines[:2],
    }

def process_series(driver, wait, series_config, target_dates, processed_titles, PROCESSED_FILE):
    """处理单个 Podcast 系列"""
    target_url = series_config["url"]
    series_name = series_config["name"]
    
    logger.info(f"\n{'='*60}")
    logger.info(f"正在处理系列: {series_name}")
    logger.info(f"URL: {target_url}")
    logger.info(f"{'='*60}")
    
    transcripts_to_process = []
    pending_entries = _get_pending_transcripts_for_series(series_config, processed_titles)
    if pending_entries:
        transcripts_to_process.extend(pending_entries)
        logger.info(
            f"[{series_name}] 发现 {len(pending_entries)} 篇待补跑 pending 文稿，将优先重试"
        )
    
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
                            'series_url': target_url,
                            'unique_key': _build_transcript_unique_key(series_config["series_id"], title),
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
        
        deduped_transcripts = []
        deduped_index = {}
        for item in transcripts_to_process:
            item_key = item.get("unique_key") or _build_transcript_unique_key(item["series_id"], item["title"])
            item["unique_key"] = item_key
            existing_idx = deduped_index.get(item_key)
            if existing_idx is None:
                deduped_index[item_key] = len(deduped_transcripts)
                deduped_transcripts.append(item)
                continue

            existing_item = deduped_transcripts[existing_idx]
            existing_has_pending = bool(existing_item.get("pending_payload"))
            new_has_pending = bool(item.get("pending_payload"))
            if new_has_pending and not existing_has_pending:
                deduped_transcripts[existing_idx] = item
                logger.info(f"[{series_name}] 检测到重复文稿，优先保留 pending 补跑版本: '{item['title']}'")
            else:
                logger.info(f"[{series_name}] 检测到重复文稿，跳过重复项: '{item['title']}'")
        transcripts_to_process = deduped_transcripts

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
            unique_key = transcript_data.get("unique_key") or f"{transcript_data['series_id']}_{title}"
            
            if unique_key in processed_titles:
                logger.info(f"[{series_name}] 文稿 '{title}' 已处理过，跳过")
                continue
                
            logger.info(f"\n[{series_name}] --- 正在处理第 {i+1}/{len(transcripts_to_process)} 篇文稿: '{title}' ---")
            pending_payload = transcript_data.get("pending_payload")
            pending_path = transcript_data.get("pending_path")
            if pending_payload is None:
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
                    
                    try:
                        article_content = _extract_transcript_via_api(driver, series_name)
                    except Exception as api_exc:
                        logger.warning(f"[{series_name}] transcript API 提取失败，回退 Copy Transcript: {api_exc}")
                        try:
                            article_content = _extract_transcript_via_copy_button(driver, wait, series_name)
                        except Exception as copy_exc:
                            logger.warning(f"[{series_name}] Copy Transcript 提取失败，回退 DOM 提取: {copy_exc}")
                            try:
                                article_content = _extract_transcript_from_dom(driver, wait, series_name)
                            except TimeoutException:
                                logger.error(f"[{series_name}] 找不到指定的文本容器，无法提取内容。")
                                continue

                    text_to_translate = f"# {title}\n\n{article_content}"
                    existing_pending_payload, existing_pending_path = load_pending_source(unique_key)
                    if existing_pending_payload:
                        keep_existing, existing_len, new_len, ratio = _preserve_existing_text_if_better(
                            existing_pending_payload,
                            text_to_translate,
                            0.8,
                        )
                        if keep_existing:
                            logger.warning(
                                f"[{series_name}] 新抓取正文明显更短，保留已有 pending 原文 "
                                f"({new_len}/{existing_len}={ratio:.3f})"
                            )
                            text_to_translate = existing_pending_payload
                            pending_path = existing_pending_path
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
                        pre_review_markdown = translated_markdown
                        reviewed_markdown = review_markdown_content(translated_markdown)
                        if reviewed_markdown:
                            ok, source_len, reviewed_len, ratio = _is_output_complete_enough(
                                pre_review_markdown,
                                reviewed_markdown,
                                REVIEW_MIN_RATIO,
                                REVIEW_RATIO_CHECK_MIN_SOURCE,
                            )
                            if ok:
                                translated_markdown = reviewed_markdown
                                logger.info(
                                    f"[{series_name}] 审校完成 "
                                    f"(len {reviewed_len}/{source_len}={ratio:.3f})"
                                )
                            else:
                                logger.warning(
                                    f"[{series_name}] 审校结果长度比例过低 "
                                    f"({reviewed_len}/{source_len}={ratio:.3f} < {REVIEW_MIN_RATIO})，"
                                    "回退到审校前翻译结果"
                                )
                        else:
                            logger.warning(f"[{series_name}] 审校返回为空，使用原翻译结果")
                    except Exception as e:
                        logger.warning(f"[{series_name}] 审校失败: {e}，使用原翻译结果")

                mixed_lang, mixed_lang_meta = _contains_excessive_english(translated_markdown)
                if mixed_lang:
                    error_msg = f"translated output is not fully Chinese: {mixed_lang_meta}"
                    record_failed_transcript(unique_key, title, series_config["series_id"], error_msg)
                    logger.error(
                        f"[{series_name}] 检测到明显英文残留，拒绝保存半成品并保留断点原文: "
                        f"{mixed_lang_meta}"
                    )
                    continue

                logger.info(
                    f"[{series_name}] 翻译完成，正在保存文件... "
                    f"(final_len={len(translated_markdown or '')})"
                )
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:50]
                safe_title_with_prefix = f"S{series_config['series_id']}_{safe_title}"
                output_basename = _build_output_basename(series_config["series_id"], title)
                md_output_path = os.path.join(PODSCRIBE_SAVE_PATH, f"{output_basename}.md")
                if os.path.exists(md_output_path):
                    try:
                        with open(md_output_path, "r", encoding="utf-8") as f:
                            existing_markdown = f.read()
                        keep_existing, existing_len, new_len, ratio = _preserve_existing_text_if_better(
                            existing_markdown,
                            translated_markdown,
                            0.8,
                        )
                        if keep_existing:
                            logger.warning(
                                f"[{series_name}] 检测到已有更长结果，跳过覆盖保存 "
                                f"({new_len}/{existing_len}={ratio:.3f}) -> {md_output_path}"
                            )
                            processed_titles.add(unique_key)
                            with open(PROCESSED_FILE, 'a', encoding='utf-8') as f:
                                f.write(f"{unique_key}\n")
                            if pending_path and transcript_data.get("pending_payload"):
                                remove_pending_source(pending_path)
                            continue
                    except Exception as exc:
                        logger.warning(f"[{series_name}] 读取已有 Markdown 失败，继续保存: {exc}")

                # 保存 Markdown 文件
                gemini_helper.SAVE_PATH = PODSCRIBE_SAVE_PATH
                md_filepath = gemini_helper.save_to_markdown_file(translated_markdown, safe_title_with_prefix)
                if md_filepath:
                    logger.info(f"[{series_name}] Markdown 文件已保存: {md_filepath}")

                # 保存 HTML 和 Word
                _, full_html = gemini_helper.convert_to_markdown_and_copy(translated_markdown)
                
                html_filepath = gemini_helper.save_to_html_file(full_html, safe_title_with_prefix)
                if html_filepath:
                    save_html_source_to_txt(full_html, safe_title_with_prefix, PODSCRIBE_SAVE_PATH)
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
