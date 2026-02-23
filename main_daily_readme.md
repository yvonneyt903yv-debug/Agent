# Agent 开机自启问题修复记录

## 问题描述

通过 launchd 配置开机自启动时，Python 程序无法正常运行，日志报错：

```
/Library/Developer/CommandLineTools/usr/bin/python3: can't open file '/Users/yvonne/Documents/agent/main.py': [Errno 1] Operation not permitted
```

## 根本原因

1. **路径大小写错误**：实际目录是 `Agent`（大写 A），但配置中写的是 `agent`（小写 a）
2. **Python 路径错误**：使用了 `/Library/Developer/CommandLineTools/usr/bin/python3`（Xcode 附带的 Python），应使用 `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`（系统 Python）
3. **launchd stdout/stderr 重定向问题**：launchd 对 Python 缓冲输出支持不好，导致日志文件为空

## 解决方案

### 1. 创建正确的 launchd 配置文件

文件位置：`~/Library/LaunchAgents/com.agent.monitor.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.agent.monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Library/Frameworks/Python.framework/Versions/3.13/bin/python3</string>
        <string>-u</string>
        <string>/Users/yvonne/Documents/Agent/main.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/yvonne/Documents/Agent/logs/launchd_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/yvonne/Documents/Agent/logs/launchd_stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
```

### 2. 关键配置说明

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `-u` | Python 参数 | 禁用输出缓冲，确保日志实时写入 |
| `PYTHONUNBUFFERED=1` | 环境变量 | 同样作用，确保无缓冲输出 |
| `RunAtLoad` | true | 登录后立即启动 |
| `KeepAlive` | true | 崩溃后自动重启 |
| `ProgramArguments` | 数组 | 必须用数组形式，不能用 Shell 字符串 |

### 3. 安装和启动服务

```bash
# 复制配置文件到 LaunchAgents 目录
cp /Users/yvonne/Documents/Agent/com.agent.monitor.plist ~/Library/LaunchAgents/

# 加载服务
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.agent.monitor.plist

# 查看服务状态
launchctl list | grep com.agent.monitor

# 重启服务
launchctl stop com.agent.monitor && launchctl start com.agent.monitor

# 完全移除
launchctl remove com.agent.monitor
```

## 常用命令

```bash
# 查看服务状态
launchctl list | grep com.agent.monitor

# 查看进程
ps aux | grep "Agent/main.py" | grep -v grep

# 实时查看日志
tail -f /Users/yvonne/Documents/Agent/logs/launchd_stdout.log

# 查看错误日志
cat /Users/yvonne/Documents/Agent/logs/launchd_stderr.log

# 停止服务
launchctl stop com.agent.monitor

# 启动服务
launchctl start com.agent.monitor
```

## 日志位置

- stdout: `/Users/yvonne/Documents/Agent/logs/launchd_stdout.log`
- stderr: `/Users/yvonne/Documents/Agent/logs/launchd_stderr.log`

## 程序运行时间

- **运行时段**: 每天 7:00 - 20:00
- **检查间隔**: 每 2 小时

## 修复时间

- 日期: 2026-02-11
- 操作人: yvonne
