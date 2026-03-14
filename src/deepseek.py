from openai import OpenAI
import httpx
import os
import time
from typing import Optional

# ===== 配置区 =====
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or "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"
BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL_NAME = "deepseek-ai/deepseek-v3.2"

# 超时和重试配置
TIMEOUT = 300  # 增加到300秒（5分钟）
MAX_RETRIES = 5
RETRY_DELAY = 10

# 网络模式:
# - auto: 优先复用采集侧代理配置（gps/server_utils），其次环境变量
# - proxy: 强制使用环境代理
# - direct: 强制直连，不使用环境代理
NETWORK_MODE = os.getenv("DEEPSEEK_NETWORK_MODE", "auto").strip().lower()


def _get_crawler_proxy() -> Optional[str]:
    """优先复用采集侧代理配置，确保采集和 LLM 网络路径一致。"""
    try:
        from gps.server_utils import get_proxy_config  # type: ignore

        cfg = get_proxy_config()
        if isinstance(cfg, dict):
            return cfg.get("https") or cfg.get("http")
    except Exception:
        return None
    return None


def _get_env_proxy() -> Optional[str]:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def _resolve_proxy_strategy() -> tuple[Optional[str], bool, str]:
    crawler_proxy = _get_crawler_proxy()

    if NETWORK_MODE == "direct":
        return None, False, "direct"

    if NETWORK_MODE == "proxy":
        # proxy 模式下优先复用采集侧；若采集侧未配置，则信任环境变量。
        if crawler_proxy:
            return crawler_proxy, False, "crawler_proxy"
        return None, True, "env_proxy"

    # auto 模式：先采集侧，再环境变量，最后直连
    if crawler_proxy:
        return crawler_proxy, False, "crawler_proxy"

    env_proxy = _get_env_proxy()
    if env_proxy:
        return env_proxy, False, "env_proxy"

    return None, False, "direct_fallback"


RESOLVED_PROXY, TRUST_ENV_PROXY, PROXY_SOURCE = _resolve_proxy_strategy()


def _build_client(proxy: Optional[str], trust_env: bool, timeout: float) -> OpenAI:
    return OpenAI(
        base_url=BASE_URL,
        api_key=DEEPSEEK_API_KEY,
        timeout=timeout,
        http_client=httpx.Client(proxy=proxy, trust_env=trust_env),
    )


def _is_connection_error(error_msg: str) -> bool:
    message = (error_msg or "").lower()
    needles = (
        "connection error",
        "ssl",
        "connecterror",
        "connect error",
        "connection reset",
        "unexpected eof",
        "error syscall",
        "network is unreachable",
    )
    return any(token in message for token in needles)


def _is_timeout_error(error_msg: str) -> bool:
    message = (error_msg or "").lower()
    return "timeout" in message or "timed out" in message


def _fallback_to_direct_allowed(proxy_in_use: Optional[str], trust_env: bool) -> bool:
    if NETWORK_MODE == "direct":
        return False
    return bool(proxy_in_use) or trust_env


def call_deepseek_api(
    prompt: str,
    *,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
    retry_delay: Optional[float] = None,
    thinking: bool = True,
    max_tokens: int = 8192,
    stream: bool = True,
    temperature: float = 1,
    top_p: float = 0.95,
) -> str:
    """
    调用 DeepSeek 模型，输入 prompt，返回生成的 content 字符串
    使用流式响应，带重试机制，处理超时和网络错误
    """
    if not prompt or not isinstance(prompt, str):
        raise ValueError("prompt must be a non-empty string")

    last_error = None
    effective_timeout = timeout if timeout is not None else TIMEOUT
    effective_max_retries = max_retries if max_retries is not None else MAX_RETRIES
    effective_retry_delay = retry_delay if retry_delay is not None else RETRY_DELAY

    print(
        f"🌐 DeepSeek network mode={NETWORK_MODE}, proxy_source={PROXY_SOURCE}, "
        f"proxy_enabled={bool(RESOLVED_PROXY) or TRUST_ENV_PROXY}"
    )

    current_proxy = RESOLVED_PROXY
    current_trust_env = TRUST_ENV_PROXY
    current_source = PROXY_SOURCE
    client = _build_client(current_proxy, current_trust_env, effective_timeout)

    for attempt in range(effective_max_retries):
        try:
            print(f"🔄 API 调用尝试 {attempt + 1}/{effective_max_retries}...")

            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stream=stream,
                timeout=effective_timeout,
                extra_body={"chat_template_kwargs": {"thinking": thinking}},
            )

            if stream:
                # 收集流式响应
                full_content = ""
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        full_content += chunk.choices[0].delta.content
            else:
                full_content = (response.choices[0].message.content or "").strip()

            if full_content:
                print(f"✅ API 调用成功")
                return full_content.strip()
            else:
                raise RuntimeError("API 返回空内容")

        except Exception as e:
            last_error = e
            error_msg = str(e)

            print(f"⚠️ 尝试 {attempt + 1} 失败: {error_msg}")

            if _fallback_to_direct_allowed(current_proxy, current_trust_env) and (
                _is_connection_error(error_msg) or _is_timeout_error(error_msg)
            ):
                print("↪️ 检测到代理链路异常或超时，切换为直连后立即重试...")
                current_proxy = None
                current_trust_env = False
                current_source = "direct_retry"
                client = _build_client(current_proxy, current_trust_env, effective_timeout)
                continue

            # 如果是最后一次尝试，直接抛出错误
            if attempt == effective_max_retries - 1:
                break

            # 检查是否是超时或网络错误
            if "504" in error_msg or "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                print(f"⏳ 检测到超时错误，{effective_retry_delay}秒后重试...")
                time.sleep(effective_retry_delay)
            elif "502" in error_msg or "503" in error_msg:
                print(f"⏳ 检测到服务器错误，{effective_retry_delay}秒后重试...")
                time.sleep(effective_retry_delay)
            else:
                # 其他错误直接抛出
                raise

    # 所有重试都失败
    print(f"\n❌ API 调用失败，已重试 {effective_max_retries} 次")
    print(f"最后的错误: {last_error}")
    print("\n💡 建议:")
    print("  1. 检查网络连接")
    print("  2. 检查 API 密钥是否有效")
    print("  3. 检查 NVIDIA API 服务状态")
    print("  4. 如果在国内，可能需要配置代理\n")

    raise RuntimeError(f"API 调用失败: {last_error}")
