#!/bin/bash
# Shennong Stock Analysis Platform - Start Script

PLATFORM_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PLATFORM_DIR/backend"
FRONTEND_DIR="$PLATFORM_DIR/frontend"

echo "=============================================="
echo "  神农股票分析平台 - 启动脚本"
echo "=============================================="

# Check Python dependencies
echo "[1/3] 检查 Python 依赖..."
python3 -c "import fastapi, uvicorn, sqlalchemy, aiosqlite, pydantic" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "  安装 Python 依赖..."
    pip3 install fastapi uvicorn sqlalchemy aiosqlite pydantic --quiet
fi
echo "  OK"

# Check Node dependencies
echo "[2/3] 检查 Node 依赖..."
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "  安装 Node 依赖..."
    cd "$FRONTEND_DIR" && npm install --silent
fi
echo "  OK"

# Build frontend if needed
echo "[3/3] 检查前端构建..."
if [ ! -d "$FRONTEND_DIR/dist" ]; then
    echo "  构建前端..."
    cd "$FRONTEND_DIR" && npm run build 2>&1 | tail -3
fi
echo "  OK"

# Start backend
echo ""
echo "启动后端服务 (端口 8000)..."
cd "$BACKEND_DIR"
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
