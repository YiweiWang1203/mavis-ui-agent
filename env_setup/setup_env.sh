#!/bin/bash
set -e 

# 💡 优化 1：消除跨盘挂载时的 Hardlink 警告，强制使用 copy 模式
export UV_LINK_MODE=copy

echo "=================================================="
echo "🚀 欢迎使用 Meeting Agent 一键环境初始化脚本 (终极优化版)"
echo "=================================================="

# 获取路径
SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(dirname "$SETUP_DIR")"
LANGMANUS_DIR="$(dirname "$AGENT_DIR")/LangManus"

if ! command -v uv &> /dev/null; then
    echo "📦 [1/5] 未检测到 uv，正在全局安装..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
else
    echo "✅ [1/5] uv 极速包管理器已就绪."
fi

echo "🔄 [2/5] 正在进入框架目录构建隔离环境..."
cd "$LANGMANUS_DIR"
uv sync

# 💡 优化 2 & 3：使用国内镜像 + 只下载 Chromium 单内核，实现极速安装
echo "🌐 [3/5] 正在通过国内镜像极速下载 Chromium 浏览器内核..."
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/ uv run playwright install chromium

echo "🧠 [4/5] 正在注入 langchain-ollama..."
uv pip install langchain-ollama

if [ ! -f .env ]; then
    echo "📄 [5/5] 正在生成 .env 配置文件..."
    cp .env.example .env
else
    echo "✅ [5/5] .env 已存在，跳过."
fi

cd "$AGENT_DIR"
echo "=================================================="
echo "🎉 环境组装大功告成！全量极速部署完毕！"
echo "=================================================="
