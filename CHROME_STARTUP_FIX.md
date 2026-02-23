# Chrome 启动失败 - 快速解决指南

## 🚨 当前问题

Chrome 进程启动后立即退出，无法开启调试端口 9222。

## 🔧 解决方案（按顺序尝试）

### 方案1：运行详细诊断（推荐）

```bash
cd /Users/yvonne/Documents/Agent
./diagnose_chrome.sh
```

这个脚本会：
- ✅ 显示详细的 Chrome 启动日志
- ✅ 自动清理损坏的用户数据
- ✅ 提供具体的错误原因
- ✅ 给出针对性的解决建议

### 方案2：使用备用发布脚本

如果 Chrome 调试模式始终无法启动，使用备用方案：

```bash
cd /Users/yvonne/Documents/Agent
python3 publish_backup.py
```

备用脚本的优势：
- ✅ 不依赖预先启动的 Chrome
- ✅ 让工具自己管理浏览器
- ✅ 更稳定可靠

### 方案3：手动启动 Chrome

如果自动启动失败，尝试手动启动：

```bash
# 1. 关闭所有 Chrome
pkill -9 Chrome

# 2. 清理用户数据目录
rm -rf ~/Library/Application\ Support/Google/Chrome/WeChatPublish

# 3. 手动启动 Chrome 调试模式
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/Library/Application Support/Google/Chrome/WeChatPublish" \
  --no-first-run \
  --no-default-browser-check \
  --disable-gpu \
  2>&1 | tee /tmp/chrome_manual.log
```

观察输出，看是否有错误信息。

### 方案4：更新或重新安装 Chrome

如果以上方法都失败：

1. **检查 Chrome 版本**
   ```bash
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --version
   ```

2. **更新 Chrome**
   - 打开 Chrome
   - 菜单 -> 关于 Google Chrome
   - 等待自动更新

3. **完全重新安装**
   ```bash
   # 卸载 Chrome
   rm -rf /Applications/Google\ Chrome.app
   rm -rf ~/Library/Application\ Support/Google/Chrome

   # 重新下载安装
   # https://www.google.com/chrome/
   ```

## 🐛 常见错误及解决方案

### 错误1: Chrome 立即崩溃

**症状：**
```
Chrome PID: 29370
❌ Chrome 启动失败
```

**可能原因：**
- 用户数据目录损坏
- Chrome 版本过旧
- 系统权限问题

**解决方案：**
```bash
# 删除用户数据目录
rm -rf ~/Library/Application\ Support/Google/Chrome/WeChatPublish

# 重新运行诊断
./diagnose_chrome.sh
```

### 错误2: 端口被占用

**症状：**
```
⚠️ 端口 9222 被占用
```

**解决方案：**
```bash
# 查找占用端口的进程
lsof -i :9222

# 强制关闭
lsof -ti :9222 | xargs kill -9

# 重试
./fix_chrome.sh
```

### 错误3: 权限问题

**症状：**
```
Permission denied
```

**解决方案：**
```bash
# 修复脚本权限
chmod +x *.sh *.py

# 修复目录权限
chmod -R 755 ~/Library/Application\ Support/Google/Chrome/WeChatPublish
```

### 错误4: Chrome 版本太旧

**症状：**
```
Chrome version: 90.x.x.x (过旧)
```

**解决方案：**
- 更新 Chrome 到最新版本（建议 120+）
- 或使用备用发布脚本

## 📊 诊断检查清单

运行以下命令收集诊断信息：

```bash
# 1. Chrome 版本
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --version

# 2. 系统版本
sw_vers

# 3. 当前 Chrome 进程
ps aux | grep Chrome | grep -v grep

# 4. 端口状态
lsof -i :9222

# 5. 用户数据目录
ls -la ~/Library/Application\ Support/Google/Chrome/WeChatPublish

# 6. 系统日志（查找 Chrome 崩溃信息）
log show --predicate 'process == "Chrome"' --last 5m
```

## 🎯 推荐工作流程

### 首次诊断：

```bash
# 1. 运行详细诊断
./diagnose_chrome.sh

# 2. 查看日志
cat /tmp/chrome_debug_*.log

# 3. 根据错误信息采取行动
```

### 如果诊断失败：

```bash
# 使用备用发布方案
python3 publish_backup.py
```

### 如果备用方案也失败：

```bash
# 手动复制内容到微信公众号后台
# 或联系技术支持
```

## 💡 其他建议

1. **使用最新版 Chrome**
   - 建议版本：120 或更高
   - 定期更新

2. **保持系统更新**
   - macOS 应保持最新

3. **检查防火墙设置**
   - 确保 Chrome 可以监听本地端口

4. **使用备用方案**
   - 如果调试模式始终有问题
   - 备用脚本更稳定

## 📞 获取帮助

如果所有方案都失败，请提供：

1. 诊断脚本的完整输出
2. Chrome 版本信息
3. 系统版本信息
4. `/tmp/chrome_debug_*.log` 文件内容

运行以下命令生成诊断报告：

```bash
{
  echo "=== 系统信息 ==="
  sw_vers
  echo ""
  echo "=== Chrome 版本 ==="
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --version
  echo ""
  echo "=== 诊断输出 ==="
  ./diagnose_chrome.sh
} > diagnostic_report.txt 2>&1

echo "诊断报告已保存到: diagnostic_report.txt"
```
