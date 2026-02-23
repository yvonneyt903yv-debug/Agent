#!/bin/bash
# Agent启动脚本 - 自动清理并启动

echo "========================================"
echo "🚀 Agent 启动脚本"
echo "========================================"

# 切换到项目目录
cd "$(dirname "$0")" || exit 1

# 1. 清理僵尸锁文件
LOCK_FILE="output/monitor.lock"
if [ -f "$LOCK_FILE" ]; then
    echo "🔍 发现锁文件，检查状态..."
    PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if [ -n "$PID" ]; then
        if ! ps -p "$PID" > /dev/null 2>&1; then
            echo "⚠️  发现僵尸锁文件 (PID $PID 不存在)，自动清理..."
            rm -f "$LOCK_FILE"
            echo "✅ 已清理"
        else
            echo "ℹ️  程序正在运行中 (PID $PID)"
            echo "   如需强制重启，请手动删除: $LOCK_FILE"
            exit 1
        fi
    else
        echo "⚠️  发现空锁文件，清理..."
        rm -f "$LOCK_FILE"
        echo "✅ 已清理"
    fi
fi

# 2. 检查Python环境
echo ""
echo "🐍 检查Python环境..."
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "❌ 错误: 未找到Python"
    exit 1
fi

echo "✅ 使用Python: $($PYTHON --version)"

# 3. 启动程序
echo ""
echo "🎯 启动Agent程序..."
echo "   日志将输出到: logs/launchd_stdout.log 和 logs/launchd_stderr.log"
echo ""

# 使用nohup在后台运行，但立即显示输出
$PYTHON main.py 2>&1 | tee -a logs/launchd_stdout.log &

PID=$!
echo "✅ Agent已启动，PID: $PID"
echo ""
echo "📋 常用命令:"
echo "   查看日志: tail -f logs/launchd_stdout.log"
echo "   停止程序: kill $PID"
echo "   检查状态: ps aux | grep python"
echo ""
echo "💡 提示: 程序将在7:00-20:00自动运行，每2小时检查一次"
