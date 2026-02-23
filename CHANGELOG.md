# Changelog

本文件记录 Agent 项目的所有重要变更。

## [2.1.0] - 2026-02-12

### 新增功能

#### 1. Jina Reader 智能抓取（`src/crawler.py`）

- **新增 `fetch_with_jina()` 函数**：使用 Jina Reader API (`https://r.jina.ai/`) 获取干净的文章内容
  - 自动去除广告、导航栏等干扰内容
  - 返回干净的 Markdown 格式
  - 支持超时控制（默认 30 秒）

- **新增 `extract_article_with_selenium()` 函数**：封装 Selenium 提取逻辑作为回退方案

- **修改 `fetch_latest_articles()` 函数**：实现 Jina 优先 + Selenium 回退策略
  ```
  抓取策略：
  1. 优先使用 Jina Reader 获取干净内容
  2. 如果 Jina 失败，自动回退到 Selenium 提取
  ```

#### 2. 摘要汇总功能（`src/tools.py`）

- **新增 `tool_merge_summaries()` 函数**：将所有文章摘要合并为一个汇总文档
  - 包含统计概览（总数、通过/未通过筛选数量）
  - 每篇文章的简介、分类、敏感性、NotebookLM 摘要
  - 保存到 `output/daily_summary/` 目录
  - 同时生成 Markdown、HTML、Word 格式

#### 3. 完善流水线（`main.py`）

- **完善 `run_full_pipeline()` 函数**：实现完整的 8 步流水线
  ```
  Step 1: 抓取文章 (Jina + Selenium)
  Step 2: 翻译文章 (DeepSeek)
  Step 3: NotebookLM 生成摘要和播客
  Step 4: Gemini 分析并存档
  Step 5: 筛选决策
  Step 6: 生成最终成品
  Step 7: 合并摘要汇总
  Step 8: 发布到微信（可选）
  ```

### 技术说明

#### Jina Reader API

Jina Reader 是一个免费的网页内容提取 API：
- 端点：`https://r.jina.ai/{url}`
- 功能：将任意网页转换为干净的 Markdown
- 优势：自动去除广告、导航、页脚等干扰内容

#### 回退机制

```python
# 抓取逻辑
content = fetch_with_jina(url)      # 1. 优先 Jina
if not content:
    content = extract_with_selenium(url)  # 2. 回退 Selenium
```

---

## [2.0.1] - 2026-02-11

### Bug 修复

- **`main.py`** - 修复缺失变量和函数定义
  - 新增 `CHECK_INTERVAL = 7200` 检查间隔变量
  - 新增 `is_locked()` / `acquire_lock()` / `release_lock()` 锁机制函数
  - 新增 `is_daytime()` / `wait_until_daytime()` 运行时段控制函数
  - 新增 `load_tracked_articles()` / `save_tracked_articles()` 文章追踪函数
  - 新增 `run_full_pipeline()` / `run_staged_pipeline()` 流水线框架

---

## [2.0.0] - 2026-02-11

### 重大变更：4阶段流水线架构

将原有的顺序处理流程重构为带检查点的4阶段流水线。

#### 新增

- **`src/checkpoint.py`** - 流水线检查点管理模块
  - `PipelineCheckpoint` 类：加载/保存检查点状态
  - 跟踪每篇文章的阶段完成状态
  - 存储文章数据：`raw_text`, `cn_text`, `notebooklm_summary`, `analysis`
  - 错误日志带时间戳
  - 支持从任意阶段恢复

- **`resume_pipeline.py`** - 崩溃恢复脚本
  - 重新获取文章列表
  - 从已保存的翻译文件恢复状态
  - 创建检查点并继续流水线

- **`README.md`** - 项目文档

#### 修改

- **`main.py`** - 主流程重构
  - 新增 `stage_1_translate_all()`: 批量翻译，每篇立即保存
  - 新增 `stage_2_summarize_all()`: NotebookLM 生成 ~500 字摘要（异步）
  - 新增 `stage_3_analyze_summaries()`: Gemini 分析摘要（非全文）
  - 新增 `stage_4_filter_and_publish()`: 筛选并发布
  - 新增 `run_staged_pipeline()`: 编排4阶段流水线
  - 新增 `generate_final_from_checkpoint()`: 从检查点数据生成最终稿
  - 修改 `run_full_pipeline()`: 调用新的 `run_staged_pipeline()`
  - 修改 `monitor()` 错误处理: 5分钟重试（原60秒）

- **`src/gemini_brain.py`** - Gemini 分析优化
  - `analyze_single_article_content()` 新增 `is_summary=True` 参数
  - 摘要输入跳过截断（已经是 ~500 字）
  - 调整 prompt 指明输入类型

#### 优化

- **Token 节省 97%**: Gemini 分析 ~500 字摘要，而非 ~15,000 字全文
- **断点续传**: 崩溃后可从任意阶段恢复，不丢失进度
- **容错性**: 单篇文章失败不影响其他文章处理

#### 检查点文件

位置: `output/pipeline_checkpoint.json`

```json
{
  "run_id": "20260211_143022",
  "articles": [...],
  "stage_1_completed": [0, 1, 2],
  "stage_2_completed": [0, 1],
  "stage_3_completed": [0],
  "errors": [...]
}
```

---

## [1.0.0] - 2026-01-15

### 初始版本

- 网站监控（singjupost.com）
- DeepSeek 翻译
- Gemini 分析和筛选
- 微信公众号发布
- 顺序处理流程（无检查点）
