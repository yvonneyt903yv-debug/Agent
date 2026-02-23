# Chrome Debug Port 错误修复指南

## 🐛 错误信息
```
Error: Chrome debug port not ready: Request failed: 502 Bad Gateway
```

## 🔧 快速修复方案

### 方案1：使用改进版脚本（推荐）

改进版脚本会自动启动 Chrome 调试模式：

```bash
cd /Users/yvonne/Documents/Agent
python3 publish_to_wechat_v2.py
```

### 方案2：运行诊断脚本

诊断并自动修复问题：

```bash
cd /Users/yvonne/Documents/Agent
python3 diagnose_publish.py
```

诊断脚本会：
- ✅ 检查 Chrome 是否已安装
- ✅ 检查 Node.js/Bun 是否已安装
- ✅ 检查端口 9222 是否可用
- ✅ 自动关闭冲突的 Chrome 进程
- ✅ 启动 Chrome 调试模式

### 方案3：手动修复

#### 步骤1：关闭所有 Chrome 进程

```bash
# 方法1：使用 pkill
pkill -9 Chrome

# 方法2：使用 Activity Monitor
# 打开"活动监视器" -> 搜索 "Chrome" -> 强制退出所有 Chrome 进程
```

#### 步骤2：检查端口是否被占用

```bash
lsof -i :9222
```

如果有输出，说明端口被占用，需要关闭占用进程：

```bash
# 找到 PID（进程ID），然后：
kill -9 <PID>
```

#### 步骤3：手动启动 Chrome 调试模式

```bash
# 创建独立的用户数据目录
mkdir -p ~/Library/Application\ Support/Google/Chrome/WeChatPublish

# 启动 Chrome 调试模式
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/Library/Application Support/Google/Chrome/WeChatPublish" \
  --no-first-run \
  --no-default-browser-check &
```

#### 步骤4：验证 Chrome 是否正常启动

```bash
lsof -i :9222
```

应该看到类似输出：
```
COMMAND   PID   USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
Chrome  12345  yvonne  123u  IPv4 0x1234567890      0t0  TCP localhost:9222 (LISTEN)
```

#### 步骤5：运行发布脚本

```bash
python3 publish_to_wechat_v2.py
```

## 🔍 常见问题

### Q1: 为什么会出现这个错误？

**原因：**
- baoyu-post-to-wechat 工具需要连接到 Chrome 的远程调试端口（9222）
- 如果 Chrome 没有以调试模式启动，或端口被占用，就会出现此错误

### Q2: 端口 9222 被其他程序占用怎么办？

**解决方案：**
1. 找出占用端口的程序：
   ```bash
   lsof -i :9222
   ```

2. 关闭该程序：
   ```bash
   kill -9 <PID>
   ```

3. 或者使用其他端口（需要修改脚本）

### Q3: Chrome 启动后立即关闭怎么办？

**可能原因：**
- 用户数据目录损坏
- Chrome 版本过旧

**解决方案：**
1. 删除用户数据目录：
   ```bash
   rm -rf ~/Library/Application\ Support/Google/Chrome/WeChatPublish
   ```

2. 更新 Chrome 到最新版本

3. 重新启动 Chrome 调试模式

### Q4: 仍然无法解决怎么办？

**尝试以下步骤：**

1. **完全重启**
   ```bash
   # 1. 关闭所有 Chrome
   pkill -9 Chrome

   # 2. 等待 5 秒
   sleep 5

   # 3. 运行诊断脚本
   python3 diagnose_publish.py
   ```

2. **检查系统日志**
   ```bash
   # 查看 Chrome 错误日志
   tail -f ~/Library/Application\ Support/Google/Chrome/WeChatPublish/chrome_debug.log
   ```

3. **使用备用方案**
   - 手动复制文章内容到微信公众号后台
   - 使用微信公众号的"导入文章"功能

## 📊 诊断检查清单

运行以下命令检查环境：

```bash
# 1. 检查 Chrome 是否安装
ls -la "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 2. 检查 Node.js/Bun
node --version
bun --version

# 3. 检查端口状态
lsof -i :9222

# 4. 检查 Chrome 进程
ps aux | grep Chrome

# 5. 检查 baoyu 脚本
ls -la baoyu-skills/skills/baoyu-post-to-wechat/scripts/wechat-article.ts
```

## 🎯 推荐工作流程

1. **首次使用**
   ```bash
   # 运行诊断
   python3 diagnose_publish.py

   # 使用改进版脚本
   python3 publish_to_wechat_v2.py
   ```

2. **日常使用**
   ```bash
   # 直接使用改进版脚本（会自动处理 Chrome）
   python3 publish_to_wechat_v2.py
   ```

3. **遇到问题时**
   ```bash
   # 1. 关闭 Chrome
   pkill -9 Chrome

   # 2. 重新诊断
   python3 diagnose_publish.py

   # 3. 重试发布
   python3 publish_to_wechat_v2.py
   ```

## 📞 获取帮助

如果以上方法都无法解决问题，请提供以下信息：

1. Chrome 版本：
   ```bash
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --version
   ```

2. 系统版本：
   ```bash
   sw_vers
   ```

3. 端口状态：
   ```bash
   lsof -i :9222
   ```

4. 错误日志：
   ```bash
   # 运行发布脚本时的完整输出
   ```
