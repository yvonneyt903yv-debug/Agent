# Agent - 微信公众号自动化发布系统

自动化内容处理和微信公众号发布工具。

## 功能

- RSS 监控和文章抓取（Jina Reader 智能提取）
- 图片自动下载（保存到本地，支持微信发布）
- AI 翻译和审校（DeepSeek）
- AI 内容分析和筛选（Gemini）
- 发布前 Gemini 审核（格式优化、去除无关内容）
- 微信公众号自动发布（Chrome 自动化）
- 可复用的��共模块，支持多数据源扩展

## 安装

```bash
pip install -r requirements.txt
```

## 使用方法

### 1. 运行 RSS 监控

支持多个数据源，每个脚本独立运行：

```bash
# Philips 监控
nohup python ph.py > ph.log 2>&1 &

# GE HealthCare 监控
nohup python ge.py > ge.log 2>&1 &

# Siemens Healthineers 监控
nohup python siemens.py > siemens.log 2>&1 &

# 查看日志
tail -f ph.log
tail -f ge.log
tail -f siemens.log
```

### 2. 单独发布文章到微信公众号

```bash
# 交互式模式（列出文章供选择）
python publish_to_wechat.py

# 命令行模式
python publish_to_wechat.py <markdown文件> [主题] [--skip-review]

# 示例
python publish_to_wechat.py output/final_published/PUBLISH_xxx.md
python publish_to_wechat.py article.md grace
python publish_to_wechat.py article.md wechat-nice --skip-review
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `<markdown文件>` | 要发布的 Markdown 文件路径 |
| `[主题]` | 可选，默认 `grace`。可选值：`grace`, `wechat-nice`, `cyan`, `purple`, `green`, `orange`, `red`, `blue` |
| `--skip-review` | 跳过 Gemini 审核步骤 |

### 3. 单独使用 Gemini 审核

```bash
python src/gemini_reviewer.py <markdown文件>
# 输出: xxx_reviewed.md
```

### 4. 单独使用 Premailer 转换 HTML

```bash
python src/md_to_html_premailer.py <markdown文件>
# 输出: xxx.html（带内联样式）
```

## 完整处理流程

```
RSS 获取文章列表
    ↓
Jina Reader 智能内容提取
    ↓
图片下载到本地 (downloaded_images/<source>/<article_id>/)
    ↓
DeepSeek 翻译（英译中）
    ↓
DeepSeek 审核（初步格式优化）
    ↓
Gemini 审核（去除无关内容、格式优化）
    ↓
保存 Markdown
    ↓
自动发布到微信公众号草稿箱
```

## 模块说明

### rss_monitor_base.py（公共模块）

可复用的核心功能，包含：

- 状态管理（load_state, save_state 等）
- 日期处理（parse_date, is_recent_article, get_target_dates）
- Jina Reader 内容提取（get_article_content_jina）
- Selenium 备用方案（get_article_content_selenium）
- 图片下载（download_images_from_markdown）
- 文章处理流程（process_single_article）

### ph.py（Philips 监控）

Philips RSS 监控脚本：

- 数据源：Philips RSS feed
- 每 4 小时运行一次
- 仅处理今天和昨天的文章

### ge.py（GE HealthCare 监控）

GE HealthCare RSS 监控脚本：

- 数据源：主站 RSS + 投资者页面
- 每 4 小时运行一次
- 仅处理今天和昨天的文章

### siemens.py（Siemens Healthineers 监控）

Siemens Healthineers 新闻监控脚本：

- 数据源：Press 页面（无 RSS，Selenium 抓取列表）
- 内容提取：Jina Reader
- 每 4 小时运行一次
- 仅处理今天和昨天的文章
- 已处理文章记录在 `siemens_state.json` 和 `siemens_processed.json`

### src/gemini_reviewer.py

使用 Gemini API 对 Markdown 进行发布前审核：

- 去除无关内容：
  - 导航、页脚、广告、分享按钮
  - "更多信息可在此处查阅" 等引导性链接
  - "更多信息将在适当时候发布" 等预告性文字
  - CSS 样式代码、HTML 标签残留
  - 媒体联系人信息、公司简介模板
- 格式优化（标题层级、段落间距、列表格式）
- 保持内容完整性

### src/md_to_html_premailer.py

使用 Python `markdown2` + `premailer` 将 Markdown 转换为带内联样式的 HTML：

- 微信公众号兼容的 CSS 样式
- 支持复杂 CSS 选择器
- 自动将 CSS 转为内联样式

CSS 样式特点：
- 段落 `letter-spacing: 3px`
- 二级标题带下划线
- 链接颜色 `rgb(71, 193, 168)`
- 引用样式简洁

## 依赖

- `openai` - Gemini/DeepSeek API 调用
- `markdown2` - Markdown 转 HTML
- `premailer` - CSS 内联化
- `requests` - Jina Reader API 调用 & 图片下载
- `selenium` - 备用网页抓取
- `apscheduler` - 定时任务调度

## 注意事项

1. 首次运行需要微信扫码登录
2. 发布过程中请勿操作浏览器窗口
3. 确保 Chrome 浏览器已安装
4. 需要 Node.js 和 Bun 运行 TypeScript 脚本
5. 需要配置代理 `http://127.0.0.1:7890` 访问外网
6. 图片会下载到 `downloaded_images/` 目录，可定期清理

## 文件结构

```
Documents/
├── rss_monitor_base.py     # 公共模块（可复用）
├── ph.py                   # Philips RSS 监控
├── ge.py                   # GE HealthCare RSS 监控
├── siemens.py              # Siemens Healthineers 监控
├── singju_ds.py            # DeepSeek 翻译模块
├── review_markdown_ds.py   # DeepSeek 审核模块
├── downloaded_images/      # 下载的图片目录
│   ├── ph/                 # Philips 图片
│   ├── ge/                 # GE 图片
│   └── siemens/            # Siemens 图片
├── ph.log                  # Philips 运行日志
├── ge.log                  # GE 运行日志
└── siemens.log             # Siemens 运行日志

Agent/
├── publish_to_wechat.py    # 微信发布入口
├── requirements.txt        # Python 依赖
├── src/
│   ├── gemini_reviewer.py      # Gemini 审核模块
│   └── md_to_html_premailer.py # HTML 转换模块
└── baoyu-skills/           # TypeScript 发布脚本
```

## 进程管理

```bash
# 查看运行状态
ps aux | grep -E "ph.py|ge.py|siemens.py"

# 停止 Philips 监控
kill $(pgrep -f "ph.py")

# 停止 GE 监控
kill $(pgrep -f "ge.py")

# 停止 Siemens 监控
kill $(pgrep -f "siemens.py")

# 重启 Philips
kill $(pgrep -f "ph.py"); nohup python ph.py > ph.log 2>&1 &

# 重启 GE
kill $(pgrep -f "ge.py"); nohup python ge.py > ge.log 2>&1 &

# 重启 Siemens
kill $(pgrep -f "siemens.py"); nohup python siemens.py > siemens.log 2>&1 &
```

## 扩展新数据源

基于公共模块，新增监控源只需：

```python
# 新增 siemens.py
from rss_monitor_base import (
    PROXIES, load_state, save_state, load_processed, save_processed,
    get_target_dates, get_article_content_jina, process_single_article
)

# 配置
RSS_URL = "https://siemens.com/..."
STATE_FILE = "siemens_state.json"
PROCESSED_FILE = "siemens_processed.json"
IMAGES_DIR = "downloaded_images/siemens"

# 实现 get_article_links() 和 process_articles()
# ...
```
## 核心的优化逻辑
20260214
Ph.py: 

所有的gemini 调用都从gemini_brain.py 调用，保证api只需要维护一个即可。
主逻辑都在Rss_monitor_base.py
保证WECHAT_PUBLISH_AVAILABLE = True   

### 核心库修改：
- rss_monitor_base.py
- gemini_brain.py

