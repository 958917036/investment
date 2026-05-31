#!/bin/bash
# =============================================================================
# 🌾 神农系统 — 统一入口脚本
# 用法: ./shennong-run.sh [--mode full|L1|L2|L3|L4|L5] [--pool full|index800] [--cache yes|no] [--help]
# =============================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAIN_SCRIPT="$PROJECT_DIR/main/shennong.py"
VENV_PYTHON="/Users/guchuang/.hermes/hermes-agent/venv/bin/python3"

# 默认参数
MODE="full"
POOL="full"

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --pool|-p)
            POOL="$2"
            shift 2
            ;;
        --help|-h)
            echo "🌾 神农系统 — 选股全链路入口"
            echo ""
            echo "用法:"
            echo "  ./shennong-run.sh [--mode MODE] [--pool full|index800]"
            echo ""
            echo "模式:"
            echo "  full  全链路 L1→L2→L3→L4→汇总 (默认)"
            echo "  L1    仅初筛筛选"
            echo "  L2    仅数据获取（需L1结果）"
            echo "  L3    仅量化分析（需L1+L2结果）"
            echo "  L4    仅裁判决策（需L1+L2+L3结果）"
            echo "  L5    复盘分析"
            echo ""
            echo "扫描范围:"
            echo "  full     全市场5300只粗筛 (默认)"
            echo "  index800 沪深300+中证500(800只)"
            echo ""
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            echo "使用 --help 查看帮助"
            exit 1
            ;;
    esac
done

POOL_LABEL="全市场" && [[ "$POOL" == "index800" ]] && POOL_LABEL="沪深300+中证500"
echo "🌾 神农系统启动 — 模式: $MODE | 范围: $POOL_LABEL"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"

# 加载API密钥（供人格轨MiniMax调用）
set -a && source "$HOME/.hermes/.env" 2>/dev/null; set +a

# 执行调度器
"$VENV_PYTHON" "$MAIN_SCRIPT" --mode "$MODE" --pool "$POOL"

EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ 神农 [$MODE] 完成 — $(date '+%H:%M:%S')"
else
    echo ""
    echo "❌ 神农 [$MODE] 失败 (exit=$EXIT_CODE)"
fi

exit $EXIT_CODE
