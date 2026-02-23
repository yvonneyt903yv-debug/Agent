import json
import re
import os
import sys
from openai import OpenAI

# ================= 配置区 =================
# 请将你的 sk-xxx 填入这里，或者从环境变量获取
API_KEY = "sk-vSLybqB74iJss9IYYlg4HIRuc7onYNtE3T7BM6egRynyPjgE"  
BASE_URL = "https://hiapi.online/v1"
MODEL_NAME = "gemini-2.5-pro"

# 初始化客户端
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ================= GLM-5 备用模块导入 =================
# 获取 glm5.py 的路径
GLM5_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "glm5.py")
GLM5_AVAILABLE = False
_glm5_module = None

def _ensure_glm5_loaded():
    """确保 GLM-5 模块已加载"""
    global GLM5_AVAILABLE, _glm5_module
    if _glm5_module is not None:
        return _glm5_module
    
    try:
        # 动态导入 glm5 模块
        import importlib.util
        spec = importlib.util.spec_from_file_location("glm5", GLM5_PATH)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法创建 glm5 模块的 spec: {GLM5_PATH}")
        _glm5_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_glm5_module)
        GLM5_AVAILABLE = True
        print(f"[INFO] GLM-5 备用模块已加载: {GLM5_PATH}")
        return _glm5_module
    except Exception as e:
        print(f"[WARNING] 无法加载 GLM-5 备用模块: {e}")
        GLM5_AVAILABLE = False
        return None


def _call_with_fallback(func_name, *args, **kwargs):
    """
    通用故障转移函数
    先调用 Gemini，如果失败则使用 GLM-5 作为备用
    """
    # 首先尝试 Gemini
    try:
        # 使用 gemini_brain 中的原始函数
        gemini_func = globals()[f"_{func_name}_gemini"]
        result = gemini_func(*args, **kwargs)
        return result
    except Exception as e:
        print(f"[WARNING] Gemini {func_name} 调用失败: {e}")
        
        # 如果 Gemini 失败，尝试 GLM-5
        if GLM5_AVAILABLE or _ensure_glm5_loaded():
            try:
                glm5_func = getattr(_glm5_module, func_name)
                print(f"[INFO] 切换到 GLM-5 执行 {func_name}...")
                result = glm5_func(*args, **kwargs)
                print(f"[INFO] GLM-5 执行 {func_name} 成功")
                return result
            except Exception as glm5_error:
                print(f"[ERROR] GLM-5 备用也失败: {glm5_error}")
        else:
            print(f"[ERROR] GLM-5 备用不可用")
        
        # 都失败了，返回默认错误值
        return None

def _clean_json_text(text):
    """
    辅助函数：清理 LLM 返回的文本，去除 Markdown 标记，提取纯 JSON 字符串
    """
    try:
        # 1. 尝试找到 ```json ... ``` 包裹的内容
        match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        
        # 2. 如果没有代码块，尝试直接找 { ... } 或 [ ... ]
        # 这里做一个简单的清洗，防止有些只有单引号或者多余空格
        text = text.strip()
        return text
    except Exception as e:
        print(f"JSON 清洗出错: {e}")
        return text

def _analyze_single_article_content_gemini(article_text, is_summary=False):
    """
    【单篇分析】
    让 Gemini 读一篇中文长文或摘要，提取元数据。

    参数:
        article_text: 文章内容或摘要
        is_summary: 如果为True，输入是~500字的摘要，跳过截断
    """
    # 如果是摘要，不需要截断；否则截取前1.5万字
    if is_summary:
        truncated_text = article_text
        input_type = "文章摘要"
    else:
        truncated_text = article_text[:15000]
        input_type = "文章"

    prompt = f"""
    请阅读以下{input_type}，提取关键信息并判断文章属性。

    **输入{input_type}：**
    {truncated_text}

    **任务：**
    1. 写一个【被访者简介/背景介绍】（100字以内）。
    2. 总结【核心要点】（3-5点）。
    3. 判断【文章类别】（如：AI技术、印度政治、娱乐八卦、中国时政、商业访谈等）。
    4. 判断【是否敏感】（涉及中国政治体制、领导人、领土等）。

    **输出格式（必须是严格的 JSON）：**
    {{
        "intro": "被访者是...",
        "key_points": "• 要点1...",
        "category": "科技",
        "is_sensitive": false
    }}
    """
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a helpful assistant designed to output JSON."},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            temperature=0.1 # 低温度保证 JSON 格式稳定
        )
        
        raw_content = response.choices[0].message.content
        if raw_content is None:
            raise ValueError("API 返回内容为空")
        clean_json = _clean_json_text(raw_content)
        
        return json.loads(clean_json)
        
    except Exception as e:
        print(f"Gemini 分析单篇文章失败: {e}")
        # 抛出异常，让故障转移机制处理
        raise


def _decide_best_articles_gemini(analysis_list):
    """
    【统筹决策】
    让 Gemini 看着一堆文章的"摘要列表"，决定选谁。
    """
    # 将列表转换为 JSON 字符串放入 Prompt
    analysis_json_str = json.dumps(analysis_list, ensure_ascii=False, indent=2)

    prompt = f"""
    你是一个微信公众号主编。现在有几篇备选文章的分析报告，请根据以下原则进行筛选：

    **一票否决规则：**
    1. ❌ **政治敏感**：涉及中国政治、批评国家领导人、批评社会主义制度、敏感地缘政治。
    2. ❌ **印度主题**：任何主要发生在地点的事件或涉及印度政治的内容。
    3. ❌ **娱乐明星**：影视明星八卦、绯闻。
    4. ✅ **首选**：AI 技术突破、硅谷科技动态、深度商业分析、名人深度访谈（非娱乐类）。

    **待选列表：**
    {analysis_json_str}

    **输出要求：**
    请返回一个 JSON 列表，包含被选中文章的 `index` (索引号)。
    例如：[0, 2] 表示选中第1篇和第3篇。如果不选，返回 []。
    只返回 JSON 列表，不要有其他废话。
    """

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are an editor. Output ONLY JSON list."},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            temperature=0.1
        )

        raw_content = response.choices[0].message.content
        if raw_content is None:
            raise ValueError("API 返回内容为空")
        clean_json = _clean_json_text(raw_content)

        return json.loads(clean_json)

    except Exception as e:
        print(f"Gemini 决策失败: {e}")
        raise


def _generate_attractive_title_gemini(notebooklm_summary: str) -> str:
    """
    【生成标题】
    使用 Gemini 根据 NotebookLM 的要点总结生成吸引人的微信公众号标题

    参数:
        notebooklm_summary: NotebookLM 生成的文章要点总结

    返回:
        生成的标题字符串
    """
    # 限制输入长度，避免token浪费
    summary_preview = notebooklm_summary[:1000] if len(notebooklm_summary) > 1000 else notebooklm_summary

    prompt = f"""
你是一位专业的微信公众号编辑。请根据以下文章要点总结，生成一个吸引人的标题。

**要求：**
1. 标题要简洁有力，15-25个字
2. 要能抓住读者眼球，激发好奇心
3. 体现文章核心价值和亮点
4. 适合微信公众号传播
5. 只输出标题本身，不要其他内容

**文章要点总结：**
{summary_preview}

请直接输出标题：
""".strip()

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a professional WeChat editor. Output ONLY the title."},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            temperature=0.7  # 稍高温度，让标题更有创意
        )

        raw_content = response.choices[0].message.content
        if raw_content is None:
            raise ValueError("API 返回内容为空")
        title = raw_content.strip()
        # 清理标题，去除可能的引号、换行等
        title = title.strip('"').strip("'").strip()
        # 如果标题太长，截断
        if len(title) > 50:
            title = title[:50]
        return title

    except Exception as e:
        print(f"Gemini 生成标题失败: {e}")
        raise


def _summarize_python_processes_gemini(process_data_list):
    """
    【Python进程监控总结】
    根据收集的Python后台进程信息，生成一个结构化的总结表格
    
    参数:
        process_data_list: 包含进程信息的字典列表，每个字典包含:
            - filename: 文件名
            - pid: 进程ID
            - start_time: 启动时间
            - last_execution: 上次执行时间
            - status: 当前状态 (运行中/已停止/错误)
            - output_preview: 输出内容预览
            - log_path: 日志文件路径
    
    返回:
        包含总结表格的Markdown格式字符串
    """
    # 将进程数据转换为JSON字符串
    processes_json = json.dumps(process_data_list, ensure_ascii=False, indent=2)
    
    prompt = f"""
你是一个系统监控助手。请根据以下Python后台进程信息，生成一个结构化的监控总结表格。

**进程数据：**
{processes_json}

**要求：**
1. 生成一个Markdown格式的表格，包含以下列：
   - 文件名
   - PID
   - 启动时间
   - 上次执行时间
   - 当前状态 (用emoji表示：🟢运行中/🔴已停止/⚠️错误)
   - 输出摘要 (前100字符)
   - 日志路径

2. 在表格之后添加：
   - 总体统计（总共X个进程，运行中Y个，已停止Z个）
   - 需要关注的进程列表（状态异常或长时间未执行）
   - 简要建议和总结

3. 只返回Markdown格式的内容，不要其他废话。

请生成监控报告：
""".strip()
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个系统监控助手，擅长整理和总结进程信息。"},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            temperature=0.3
        )
        
        raw_content = response.choices[0].message.content
        if raw_content is None:
            raise ValueError("API 返回内容为空")
        summary = raw_content.strip()
        return summary
        
    except Exception as e:
        print(f"Gemini 生成进程总结失败: {e}")
        raise


# ================= 公开 API 函数（带故障转移）=================

def analyze_single_article_content(article_text, is_summary=False):
    """
    【单篇分析】带 GLM-5 故障转移
    
    先尝试使用 Gemini 分析文章，如果失败则自动切换到 GLM-5。
    """
    result = _call_with_fallback('analyze_single_article_content', article_text, is_summary=is_summary)
    
    if result is None:
        # 如果都失败了，返回默认错误值
        return {
            "intro": "分析失败",
            "key_points": "分析失败",
            "category": "unknown",
            "is_sensitive": True  # 失败默认当敏感处理，防止发错
        }
    return result


def decide_best_articles(analysis_list):
    """
    【统筹决策】带 GLM-5 故障转移
    
    先尝试使用 Gemini 决策，如果失败则自动切换到 GLM-5。
    """
    result = _call_with_fallback('decide_best_articles', analysis_list)
    
    if result is None:
        return []
    return result


def generate_attractive_title(notebooklm_summary: str) -> str:
    """
    【生成标题】带 GLM-5 故障转移
    
    先尝试使用 Gemini 生成标题，如果失败则自动切换到 GLM-5。
    """
    result = _call_with_fallback('generate_attractive_title', notebooklm_summary)
    
    if result is None:
        return "精彩文章推荐"
    return result


def summarize_python_processes(process_data_list):
    """
    【Python进程监控总结】带 GLM-5 故障转移
    
    先尝试使用 Gemini 生成总结，如果失败则自动切换到 GLM-5。
    """
    result = _call_with_fallback('summarize_python_processes', process_data_list)
    
    if result is None:
        # 返回一个简单的备用表格
        fallback = "| 文件名 | PID | 状态 | 日志路径 |\n|--------|-----|------|----------|\n"
        for proc in process_data_list:
            fallback += f"| {proc.get('filename', 'N/A')} | {proc.get('pid', 'N/A')} | {proc.get('status', 'Unknown')} | {proc.get('log_path', 'N/A')} |\n"
        return fallback
    return result
