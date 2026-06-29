#!/bin/bash

# 1. 强制定义你的工作空间（家）
export PROJECT_ROOT="/wyw/meeting_agent_workspace/my_agent"

echo "--- 🚀 正在前往 Meeting Agent 工作空间 ---"

# 2. 瞬间移动到项目根目录 (这步最关键！)
cd "$PROJECT_ROOT" || { echo "❌ 找不到目录: $PROJECT_ROOT"; exit 1; }

# 3. 激活虚拟环境
if [ -f ".venv/bin/activate" ]; then
    source ".venv/bin/activate"
    echo "✅ 环境已激活: $(python --version)"
else
    echo "❌ 没找到 .venv，请确认你在 $PROJECT_ROOT"
fi

# 4. 启动服务
if pgrep -x "ollama" > /dev/null; then
    echo "ℹ️  Ollama 已在运行。"
else
    echo "🚀 启动 Ollama..."
    nohup ollama serve > /dev/null 2>&1 &
    sleep 2
fi

echo "📍 当前位置: $(pwd)"
echo "--- ✨ 准备就绪，可以开工了！ ---"

LOG_FILE="/wyw/meeting_agent_workspace/my_agent/logs/ollama.log"

if pgrep -x "ollama" > /dev/null; then
    echo "ℹ️  Ollama 服务已经在后台运行。"
else
    echo "🚀 正在后台启动 Ollama 服务，日志写入 $LOG_FILE ..."
    # 将标准输出和错误全部追加 (>>) 到你的 ollama.log 中
    nohup ollama serve >> "$LOG_FILE" 2>&1 &
    sleep 2
    echo "✅ Ollama 服务已启动。"
fi