from openai import OpenAI
import os
import time

# ===== 配置区 =====
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or "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"
BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL_NAME = "deepseek-ai/deepseek-v3.2"

# 超时和重试配置
TIMEOUT = 300  # 增加到300秒（5分钟）
MAX_RETRIES = 5
RETRY_DELAY = 10

# ===== Client 初始化 =====
client = OpenAI(
    base_url=BASE_URL,
    api_key=DEEPSEEK_API_KEY,
    timeout=TIMEOUT,
)


def call_deepseek_api(prompt: str) -> str:
    """
    调用 DeepSeek 模型，输入 prompt，返回生成的 content 字符串
    使用流式响应，带重试机制，处理超时和网络错误
    """
    if not prompt or not isinstance(prompt, str):
        raise ValueError("prompt must be a non-empty string")

    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            print(f"🔄 API 调用尝试 {attempt + 1}/{MAX_RETRIES}...")

            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=1,
                top_p=0.95,
                max_tokens=8192,
                stream=True,
                extra_body={"chat_template_kwargs": {"thinking": True}},
            )

            # 收集流式响应
            full_content = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    full_content += chunk.choices[0].delta.content

            if full_content:
                print(f"✅ API 调用成功")
                return full_content.strip()
            else:
                raise RuntimeError("API 返回空内容")

        except Exception as e:
            last_error = e
            error_msg = str(e)

            print(f"⚠️ 尝试 {attempt + 1} 失败: {error_msg}")

            # 如果是最后一次尝试，直接抛出错误
            if attempt == MAX_RETRIES - 1:
                break

            # 检查是否是超时或网络错误
            if "504" in error_msg or "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                print(f"⏳ 检测到超时错误，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
            elif "502" in error_msg or "503" in error_msg:
                print(f"⏳ 检测到服务器错误，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
            else:
                # 其他错误直接抛出
                raise

    # 所有重试都失败
    print(f"\n❌ API 调用失败，已重试 {MAX_RETRIES} 次")
    print(f"最后的错误: {last_error}")
    print("\n💡 建议:")
    print("  1. 检查网络连接")
    print("  2. 检查 API 密钥是否有效")
    print("  3. 检查 NVIDIA API 服务状态")
    print("  4. 如果在国内，可能需要配置代理\n")

    raise RuntimeError(f"API 调用失败: {last_error}")
