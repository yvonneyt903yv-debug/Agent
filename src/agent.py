import json
import re
from typing import Dict, Any
import os
from src.deepseek import client, MODEL_NAME  # 从 deepseek.py 导入 MODEL_NAME
from src.tools import TOOLS_MAP

# MODEL_NAME 现在从 deepseek.py 导入，不再在这里定义
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load_prompt(filename):
    """读取 prompts 文件夹下的 Markdown 文件"""
    path = os.path.join(PROJECT_ROOT, "prompts", filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"⚠️ 无法读取 Prompt 文件: {path}, 错误: {e}")
        return ""

# 加载 Prompt
SYSTEM_PROMPT = load_prompt("system_prompt.md")

# 更新后的 System Prompt，与 tools.py 中的工具完全对应
SYSTEM_PROMPT = """
你是一个专业的微信公众号主编 Agent。你的目标是发布高质量文章。

**你拥有的工具箱（请严格使用以下工具名）：**

1. `tool_fetch_news`
   - 功能：模拟抓取外网文章。
   - 参数：无。
   - 返回：抓取状态。

2. `tool_translate_all`
   - 功能：将抓取到的所有文章批量翻译成中文。
   - 参数：无。

3. `tool_analyze_individual`
   - 功能：让 Gemini 逐篇阅读中文译文，提取简介和要点。**同时会自动将所有文章的翻译稿和摘要保存到 `output/all_archives` 文件夹备份**。
   - 参数：无。

4. `tool_filter_decision`
   - 功能：让 Gemini 根据要点列表进行筛选，决定哪些文章通过。
   - 参数：无。
   - 返回：筛选结果，如果通过则提示下一步，否则提示结束。

5. `tool_notebooklm_summary_all`
   - 功能：使用 NotebookLM 对通过筛选的文章进行智能总结要点，并生成中文播客音频。
   - 参数：无。
   - 返回：总结结果和播客文件路径。

6. `tool_generate_final`
   - 功能：生成最终成品。它会自动拼接【简介+要点+正文】，进行审校，并保存文件。
   - 参数：无。

**你的标准工作流程（请按顺序执行）：**
Step 1: 调用 `tool_fetch_news` 抓取文章。
Step 2: 调用 `tool_translate_all` 进行翻译。
Step 3: 调用 `tool_analyze_and_filter` (注意：这里实际对应的是 `tool_analyze_individual`) 进行逐篇分析。
Step 4: 调用 `tool_filter_decision` 进行筛选决策。
   - 如果返回结果包含 "FILTERED_OUT"，则输出 "今日无合适文章" 并结束。
Step 5: 调用 `tool_notebooklm_summary_all` 使用 NotebookLM 进行总结要点并生成播客。
Step 6: 调用 `tool_generate_final` (对应工具层里的 `process_save`) 生成并保存最终文件。

**交互规则（ReAct 模式）：**
- 每次只输出一步思考和行动。
- 格式必须是：
ACTION: <tool_name>
ARGS: <json_args> (如果没有参数，请传空字典 {})

- 当所有步骤完成，输出最终结果。
""".strip()


ACTION_PATTERN = re.compile(
    r"ACTION:\s*(?P<tool>[a-zA-Z0-9_]+)\s*ARGS:\s*(?P<args>\{.*\})",
    re.DOTALL,
)


def call_llm(messages, max_retries=3):
    """调用 LLM，使用流式响应，带重试机制"""
    import time

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
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

            return full_content.strip()

        except Exception as e:
            error_msg = str(e)

            if attempt < max_retries - 1:
                print(f"⚠️ LLM 调用失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")
                print(f"⏳ 10秒后重试...")
                time.sleep(10)
            else:
                print(f"\n❌ LLM 调用错误: {error_msg}")
                return f"LLM 调用错误: {e}"

    return "LLM 调用失败: 已达到最大重试次数"


def run_agent(max_steps: int = 15):
    """
    主 Agent Loop（ReAct）
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "请开始工作，执行今天的文章发布任务。"},
    ]

    for step in range(max_steps):
        llm_output = call_llm(messages)
        print(f"\n===== LLM STEP {step} =====\n{llm_output}\n")

        # 尝试解析 ACTION
        match = ACTION_PATTERN.search(llm_output)

        if match:
            tool_name = match.group("tool")
            args_raw = match.group("args")
            
            # 映射修正：Prompt 里写的名字可能和 tools.py 里的 key 不完全一致，这里做个容错映射
            # 或者你直接修改 Prompt 里的名字。这里为了保险，做一个简单的别名处理。
            tool_aliases = {
                "tool_analyze_and_filter": "tool_analyze_individual", # 修正 Agent 可能��误用
                "tool_process_save": "tool_save",
                "tool_save": "tool_save", # 映射到 tools.py 里的 tool_generate_final
                "tool_notebooklm_summary": "tool_notebooklm_summary_all" # 修正 NotebookLM 工具名
            }
            
            # 在 tools.py 里，我们将 'tool_save' key 映射到了 tool_generate_final 函数
            # 所以这里只需要确保 tool_name 能在 TOOLS_MAP 里找到
            
            if tool_name in tool_aliases:
                tool_name = tool_aliases[tool_name]

            if tool_name not in TOOLS_MAP:
                observation = f"错误：工具 {tool_name} 不存在。请检查工具列表。"
            else:
                try:
                    # 处理参数
                    if not args_raw.strip():
                        args = {}
                    else:
                        try:
                            args = json.loads(args_raw)
                        except:
                            args = {} #如果解析失败，尝试空参数
                    
                    print(f"⚙️ 正在执行工具: {tool_name} ...")
                    # 执行工具
                    # 注意：我们在 tools.py 里定义的那些 tool_xxx 函数大多不需要参数
                    # 但为了通用性，我们检查一下函数签名，或者直接尝试调用
                    result = TOOLS_MAP[tool_name](**args)
                    observation = result
                except Exception as e:
                    observation = f"工具执行失败：{str(e)}"

            print(f"🔧 工具输出: {str(observation)[:100]}...") # 只打印前100个字符

            messages.append({"role": "assistant", "content": llm_output})
            messages.append(
                {
                    "role": "user",
                    "content": f"Observation:\n{observation}",
                }
            )
            
            # 如果是最后一步保存成功，可以直接结束
            if tool_name == "tool_save" and "已生成" in str(observation):
                print("\n✅ 流程全部完成！")
                return "Task Completed"
                
            continue

        # 没有 ACTION，说明 Agent 可能在说话或者结束了
        if "结束" in llm_output or "完成" in llm_output:
            return llm_output

    print("⚠️ 达到最大步数，强制停止。")

if __name__ == "__main__":
    # 确保 tools.py 里的映射是正确的
    # 我们需要在在这里再次确认一下 TOOLS_MAP 的 key
    # 从你的 tools.py 代码看，key 是：
    # "tool_fetch_news", "tool_translate", "tool_analyze_individual", 
    # "tool_filter_decision", "tool_save" (对应 tool_generate_final)
    
    # 修正 tools.py 里的映射名以匹配 Prompt (如果需要)
    # 建议去 src/tools.py 最后确认一下 TOOLS_MAP
    
    run_agent()