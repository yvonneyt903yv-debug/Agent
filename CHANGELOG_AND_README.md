# 微信公众号主编 Agent - 修改记录与使用文档

## 修改记录

### 2026-02-10 更新

#### 修改内容

| 文件 | 修改说明 |
|------|----------|
| `main.py` | `main()` 函数改为调用 `monitor()` 进入每2小时循环的自动监控模式 |
| `com.agent.monitor.plist` | 新增 launchd 配置文件，实现 macOS 开机自启动 |

#### 功能说明

1. **每2小时自动循环**：程序启动后自动进入监控模式，每2小时检查一次网站更新
2. **开机自动运行**：通过 macOS launchd 服务，登录系统后自动启动
3. **文章去重**：已处理的文章记录在 `output/tracked_articles.json`，不会重复处理
4. **崩溃自动重启**：如果程序意外退出，launchd 会自动重新启动

---

## 使用文档

### 首次启用服务

```bash
# 加载并启动服务
launchctl load ~/Library/LaunchAgents/com.agent.monitor.plist
```

### 常用命令

| 操作 | 命令 |
|------|------|
| 启动服务 | `launchctl load ~/Library/LaunchAgents/com.agent.monitor.plist` |
| 停止服务 | `launchctl unload ~/Library/LaunchAgents/com.agent.monitor.plist` |
| 查看状态 | `launchctl list | grep com.agent.monitor` |
| 重启服务 | 先 unload 再 load |

### 查看日志

```bash
# 查看标准输出日志
tail -f /Users/yvonne/Documents/agent/logs/launchd_stdout.log

# 查看错误日志
tail -f /Users/yvonne/Documents/agent/logs/launchd_stderr.log
```

### 手动运行（不使用 launchd）

```bash
cd /Users/yvonne/Documents/agent
python3 main.py
```

### 停止开机自启动

```bash
# 卸载服务
launchctl unload ~/Library/LaunchAgents/com.agent.monitor.plist

# 如需彻底删除，再执行：
rm ~/Library/LaunchAgents/com.agent.monitor.plist
```

---

## 文件结构

```
/Users/yvonne/Documents/agent/
├── main.py                      # 主程序入口
├── logs/
│   ├── launchd_stdout.log       # 标准输出日志
│   └── launchd_stderr.log       # 错误日志
├── output/
│   ├── tracked_articles.json    # 已处理文章记录（用于去重）
│   ├── translated/              # 翻译稿保存目录
│   └── final_published/         # 最终成品保存目录
└── ...

~/Library/LaunchAgents/
└── com.agent.monitor.plist      # launchd 服务配置文件
```

---

## 运行时间

- 程序只在 **7:00 - 20:00** 之间运行
- 夜间自动休眠，次日7点继续

---

## 注意事项

1. 确保 Python 3 已安装且路径为 `/usr/bin/python3`，如使用其他 Python 环境需修改 plist 文件
2. 首次运行前确保已安装依赖：`pip3 install -r requirements.txt`
3. 如需修改检查间隔，编辑 `main.py` 中的 `CHECK_INTERVAL` 变量（单位：秒）
