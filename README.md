# Agent - 微信公众号主编 Agent

自动化内容采集、翻译、分析和发布系统。从 singjupost.com 抓取英文播客/访谈文章，翻译成中文，通过 AI 分析筛选，最终发布到微信公众号。

## 核心功能

- **智能抓取**: Jina Reader 优先获取干净内容，Selenium 作为回退
- **网站监控**: 每2小时自动检查 singjupost.com 新文章
- **智能翻译**: DeepSeek API 英译中（成本低）
- **内容摘要**: NotebookLM 生成 ~500 字摘要 + 播客音频
- **AI 分析**: Gemini 分析文章类别、敏感度、核心要点
- **智能筛选**: Gemini 根据编辑规则自动筛选适合发布的文章
- **摘要汇总**: 自动生成每日文章摘要汇总文档
- **断点续传**: 4阶段流水线，每步保存检查点，崩溃后可恢复

## 8步完整流水线

```
Step 1: 抓取文章 (Jina Reader + Selenium 回退)
    ↓
Step 2: 翻译文章 (DeepSeek API)
    ↓
Step 3: NotebookLM 生成摘要和播客
    ↓
Step 4: Gemini 分析并存档
    ↓
Step 5: 筛选决策
    ↓
Step 6: 生成最终成品
    ↓
Step 7: 合并摘要汇总
    ↓
Step 8: 发布到微信（可选）
```

**Token 节省**: Gemini 分析 ~500 字摘要，而非 ~15,000 字全文（节省 97%）

## 智能抓取策略

采用 Jina Reader 优先 + Selenium 回退的双重策略：

```python
# 1. 优先使用 Jina Reader（更干净的内容）
content = fetch_with_jina(url)

# 2. Jina 失败时，回退到 Selenium
if not content:
    content = extract_with_selenium(url)
```

**Jina Reader 优势**:
- 自动去除广告、导航栏、页脚等干扰
- 返回干净的 Markdown 格式
- 免费 API，无需配置

### 检查点机制

每个阶段完成后自动保存状态到 `output/pipeline_checkpoint.json`：
- 崩溃后自动从断点恢复
- 跳过已完成的文章
- 错误日志带时间戳

## 安装

```bash
pip install -r requirements.txt
```

## 使用方法

### 1. 启动自动监控

```bash
python main.py
```

- 运行时间: 7:00-20:00
- 检查间隔: 每2小时
- 自动处理新文章

### 2. 从崩溃中恢复

如果上次运行中断，使用恢复脚本：

```bash
python resume_pipeline.py
```

### 3. 手动发布到微信

```bash
python publish_to_wechat.py output/final_published/PUBLISH_xxx.md
```

### 4. NotebookLM 总结并接 publisher

如果你已经有一篇现成 Markdown，想先让 NotebookLM 生成要点，再把要点合并回原稿，最后交给 publisher 生成可发布版本，可以直接运行：

```bash
python3 md-to-publish.py /absolute/path/to/article.md
```

默认会生成两个文件：

- `*_publish_source.md`：已合并 `## 【NotebookLM 智能总结】` 的中间稿
- `*_publish.md`：publisher 输出的最终发布稿

如果环境里已配置 `MINIMAX_API_KEY` 和 `MINIMAX_API_URL`，会走完整 publisher 改写流程；如果没有配置，也会继续完成 publisher 的结构整理和姓名统一，并保留 NotebookLM 总结作为观点总结。

脚本在生成 `*_publish.md` 后，会继续询问是否发布到公众号：

- 输入 `y`：调用 `/Users/yvonne/Documents/publish_to_wechat_ds.py`
- 输入其他任意内容：直接终止，不发布

如果只是本地验证合并逻辑，不想实际调用 NotebookLM，可以传入测试总结文本：

```bash
python3 md-to-publish.py /absolute/path/to/article.md \
  --summary-text $'1. 要点一\n2. 要点二' \
  --skip-publisher
```

## VPS 同步（当前生产结构）

当前 VPS（`root@107.174.255.109`）的 `~/projects/Agent` 目录不是 git 仓库，不能使用 `git pull`。
实际运行目录在：

- `~/projects/Agent/gps`
- `~/projects/Agent/gps/src`

当本地修改以下文件时，需要用 `scp` 直接覆盖到 VPS 对应位置：

- 本地 `src/notebook_tool.py` -> VPS `~/projects/Agent/gps/src/notebook_tool.py`
- 本地 `notebook_tool.py` -> VPS `~/projects/Agent/gps/notebook_tool.py`
- 本地 `notebooklm_summary_podcast.py` -> VPS `~/projects/Agent/gps/notebooklm_summary_podcast.py`

推荐命令：

```bash
scp /Users/yvonne/Documents/Agent/src/notebook_tool.py \
  root@107.174.255.109:/root/projects/Agent/gps/src/notebook_tool.py

scp /Users/yvonne/Documents/Agent/notebook_tool.py \
  /Users/yvonne/Documents/Agent/notebooklm_summary_podcast.py \
  root@107.174.255.109:/root/projects/Agent/gps/
```

## Telegram 通知逻辑

当前 VPS 上“新内容提醒”主要不是由各个抓取脚本统一直接发送，而是由 systemd 定时任务统一扫描产出目录后调用 Telegram 通知脚本：

- service: `agent-new-content-check.service`
- timer: `agent-new-content-check.timer`
- runtime script: `/usr/local/bin/agent-new-content-check.sh`
- notify script: `/usr/local/bin/notify_telegram.sh`

工作方式：

1. `agent-new-content-check.timer` 每 10 分钟触发一次 `agent-new-content-check.service`
2. `agent-new-content-check.sh` 读取 `/var/lib/agent-notify/new_content_last_check` 作为上次扫描时间
3. 脚本递归扫描指定目录中自上次检查以来的新文件
4. 若发现新增文件，则把最近命中的文件列表拼成消息，调用 `/usr/local/bin/notify_telegram.sh text "..."`
5. 扫描完成后更新 `new_content_last_check`

当前约定：

- `Automated_Articles` 不在 `output/` 下，需要单独纳入扫描
- `gps/output` 应按“整个目录递归扫描”的方式监控，这样 `output/podscribe`、`output/translated`、`output/final_published` 以及未来新增子目录都会自动被纳入提醒
- 如果新增了新的产出目录，但不在扫描列表中，就会出现“文件已生成但没有 Telegram 提醒”的情况

排查新内容未提醒时，优先检查：

```bash
systemctl cat agent-new-content-check.service
systemctl cat agent-new-content-check.timer
journalctl -u agent-new-content-check.service -n 100 --no-pager
sed -n '1,240p' /usr/local/bin/agent-new-content-check.sh
```

推荐的 VPS 监控目录配置：

```bash
DIRS=(
  "/root/projects/Agent/gps/Automated_Articles"
  "/root/projects/Agent/gps/output"
)
```

## 文件结构

```
Agent/
├── main.py                 # 主入口，监控循环 + 8步流水线
├── resume_pipeline.py      # 崩溃恢复脚本
├── src/
│   ├── crawler.py          # 抓取模块（Jina + Selenium）
│   ├── tools.py            # 工具函数（翻译、分析、摘要等）
│   ├── checkpoint.py       # 检查点管理
│   └── ...
├── output/
│   ├── pipeline_checkpoint.json  # 流水线检查点
│   ├── tracked_articles.json     # 已处理文章记录
│   ├── monitor.lock              # 运行锁文件（防止并发）
│   ├── translated/               # 翻译稿
│   ├── all_archives/             # 全量存档
│   ├── final_published/          # 最终发布稿
│   ├── daily_summary/            # 每日摘要汇总
│   └── podcasts/                 # NotebookLM 播客音频
└── prompts/
    └── editor_instruction.md     # 编辑指令
```

## 检查点文件格式

`output/pipeline_checkpoint.json`:

```json
{
  "run_id": "20260211_143022",
  "articles": [
    {
      "id": 0,
      "raw_text": "...",
      "cn_text": "...",
      "notebooklm_summary": "...",
      "analysis": {"intro": "...", "key_points": "...", "category": "...", "is_sensitive": false}
    }
  ],
  "stage_1_completed": [0, 1, 2],
  "stage_2_completed": [0, 1],
  "stage_3_completed": [0],
  "errors": [{"stage": 2, "article_id": 2, "error": "...", "timestamp": "..."}]
}
```

## 筛选规则

**一票否决**:
- ❌ 政治敏感（中国政治、领导人、领土）
- ❌ 印度主题
- ❌ 娱乐明星八卦

**优先选择**:
- ✅ AI 技术突破
- ✅ 硅谷科技动态
- ✅ 深度商业分析
- ✅ 名人深度访谈（非娱乐类）

## API 配置

在 `src/gemini_brain.py` 和 `src/translator.py` 中配置 API Key：

- **Gemini**: 用于内容分析、筛选、标题生成
- **DeepSeek**: 用于翻译（成本低）
- **NotebookLM**: 用于生成摘要（需要登录凭证）

## 错误处理

- **Gemini 配额不足**: 流水线会在 Stage 3 失败，检查点保存进度，充值后运行 `resume_pipeline.py` 继续
- **翻译失败**: 单篇失败不影响其他文章，错误记录到检查点
- **网络错误**: 5分钟后自动重试

## 依赖

- `openai` - Gemini/DeepSeek API
- `notebooklm` - NotebookLM 客户端
- `requests` - HTTP 请求
- `selenium` - 网页爬取备用

## 配置

### 检查间隔

修改 `main.py` 中的 `CHECK_INTERVAL` 变量（单位：秒）：

```python
CHECK_INTERVAL = 7200  # 每2小时检查一次
```

### 运行时段

默认运行时间: 7:00-20:00，在非运行时段会自动等待。

---

## 注意事项

1. NotebookLM 需要先登录获取凭证
2. Gemini API 有配额限制，注意余额
3. 运行时间限制在 7:00-20:00，夜间自动暂停
4. 检查点文件在成功完成后自动清除
5. 锁文件 `output/monitor.lock` 用于防止并发运行

## 依赖
