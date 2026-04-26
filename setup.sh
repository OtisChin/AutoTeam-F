#!/bin/bash
set -e

# 安装系统依赖（xvfb，无头服务器需要）
if ! command -v Xvfb &> /dev/null; then
    echo "安装 xvfb..."
    sudo apt-get update && sudo apt-get install -y xvfb
fi

# 安装 uv（如果没有）
if ! command -v uv &> /dev/null; then
    echo "安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# 安装 Python 依赖
uv sync

# 安装 Playwright 浏览器
uv run playwright install chromium

# 安装 pre-commit hooks
uv run pre-commit install

# 复制配置模板
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  已创建 .env，请填入实际配置"
fi

echo ""
echo "✅ 安装完成！"
echo ""
echo "用法:"
echo "  uv run autoteam --help       # 查看所有命令"
echo "  uv run autoteam rotate       # 智能轮转"
echo "  uv run autoteam api          # 启动 API + Web 面板"
