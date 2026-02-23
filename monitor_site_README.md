# 网站自动监控脚本使用说明

## 脚本功能概述

本脚本用于自动监控网站更新，发现新文章后自动执行：翻译 → 分析 → 筛选 → 生成 → 发布的完整流程。

---

## 修改记录

### 1. 检查间隔调整
**修改位置**: `monitor_site.py:23`
```python
# 修改前
CHECK_INTERVAL = 3600  # 每1小时检查一次

# 修改后
CHECK_INTERVAL = 7200  # 每2小时检查一次
```
**目的**: 避免因处理流程耗时过长导致任务堆积。

---

### 2. 添加锁文件机制（防并发）
**修改位置**: `monitor_site.py:25, 29-55`

新增三个函数：
- `is_locked()` - 检查是否有其他实例正在运行
- `acquire_lock()` - 获取锁
- `release_lock()` - 释放锁

**工作流程**:
1. 启动时检查锁文件
2. 如果锁存在且对应进程仍在运行 → 跳过本次检查，5分钟后重试
3. 如果锁存在但进程已结束 → 清除旧锁，继续执行
4. 完成后释放锁

**目的**: 防止多个脚本实例同时运行，造成重复处理。

---

### 3. 文章去重机制
**修改位置**: `monitor_site.py:219-240`

```python
# 加载已处理文章的哈希集合
tracked_hashes = set(a.get("content_hash") for a in tracked if a.get("content_hash"))

# 过滤掉已处理的文章
for article in articles:
    article_hash = hash(article[:500])
    if article_hash not in tracked_hashes:
        new_articles.append(article)
```

**工作原理**:
1. 读取 `output/tracked_articles.json` 中已处理文章的内容哈希
2. 计算新文章的内容哈希
3. 只处理哈希值不在已处理列表中的文章
4. 处理完成后，将新文章的哈希值保存到记录中

**目的**: 避免同一篇文章被重复处理。

---

## 使用方法

### 启动监控
```bash
cd /Users/yvonne/Documents/Agent
python monitor_site.py
```

### 停止监控
按 `Ctrl + C` 发送中断信号，脚本会优雅退出并释放锁。

---

## 运行规则

| 规则 | 说明 |
|------|------|
| 检查间隔 | 每2小时自动检查一次 |
| 运行时段 | 仅在 07:00 - 20:00 期间执行 |
| 非运行时段 | 自动等待至次日7:00 |
| 任务堆积 | 上次任务未完成时，跳过本次检查，5分钟后重试 |

---

## 输出文件

| 文件路径 | 说明 |
|----------|------|
| `output/tracked_articles.json` | 已处理文章记录（含哈希值） |
| `output/monitor.lock` | 锁文件（自动生成/删除） |
| `final_published/*.md` | 生成的最终发布文件 |

---

## 故障排除

### 1. 脚本卡住不运行
检查锁文件是否存在：
```bash
cat /Users/yvonne/Documents/Agent/output/monitor.lock
```
如果对应进程已结束，可手动删除锁文件：
```bash
rm /Users/yvonne/Documents/Agent/output/monitor.lock
```

### 2. 重复处理同一篇文章
检查 `output/tracked_articles.json` 是否损坏，可尝试清空该文件（脚本会重新开始记录）。

### 3. 想立即执行检查
停止当前脚本，重新启动即可立即执行。

---

## 配置修改

如需调整运行参数，可修改以下变量：

```python
CHECK_INTERVAL = 7200  # 检查间隔（秒），7200=2小时
# 或
is_daytime() 函数中的小时判断
```
