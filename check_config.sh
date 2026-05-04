#!/bin/bash

# ============================================================
# Fintech System 配置自检脚本 (AMD GPU 优化版)
# ============================================================

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0

# 打印标题
echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}           Fintech System 环境配置自检 (AMD 版)            ${NC}"
echo -e "${BLUE}============================================================${NC}"

# 通用检查函数
check() {
    local desc=$1
    local cmd=$2
    printf "正在检查: %-40s" "$desc"
    if eval "$cmd" &>/dev/null; then
        echo -e "[ ${GREEN}通过${NC} ]"
        ((PASS++))
    else
        echo -e "[ ${RED}失败${NC} ]"
        ((FAIL++))
    fi
}

echo -e "\n${YELLOW}[1. 容器与数据库检查]${NC}"
check "Docker 引擎运行状态" "docker info"
check "PostgreSQL 容器运行状态" "docker ps | grep fintech_pg"
check "数据库内部连通性" "docker exec fintech_pg pg_isready -U postgres"

echo -e "\n${YELLOW}[2. Python 与量化环境检查]${NC}"
# 自动定位 Conda 路径
CONDA_BASE=$(conda info --base 2>/dev/null || echo "$HOME/miniconda3")
if [ -d "$CONDA_BASE" ]; then
    check "Conda 环境 (fintech) 存在" "conda env list | grep -q fintech"
    # 使用完整的 conda run 逻辑
    check "Tushare 库导入测试" "conda run -n fintech python -c 'import tushare'"
    check "Akshare 库导入测试" "conda run -n fintech python -c 'import akshare'"
    check "SQLAlchemy 库导入测试" "conda run -n fintech python -c 'import sqlalchemy'"
else
    echo -e "  ${RED}✗${NC} 找不到 Conda 安装目录"
    ((FAIL++))
fi

echo -e "\n${YELLOW}[3. 大模型 (Ollama) 检查]${NC}"
check "Ollama 服务响应" "ollama list"
check "Qwen 2.5 7B 模型已下载" "ollama list | grep -q 'qwen2.5'"

echo -e "\n${YELLOW}[4. AMD GPU 加速检查 (RX 7600)]${NC}"
if [ -e /dev/kfd ]; then
    echo -e "  ${GREEN}✓${NC} 检测到 AMD GPU 内核接口 (/dev/kfd)"
    ((PASS++))
    if command -v rocm-smi &>/dev/null; then
        check "ROCm 管理工具 (rocm-smi)" "rocm-smi"
    fi
else
    echo -e "  ${YELLOW}!${NC} 未发现 AMD GPU 驱动，AI 将在 CPU 模式下运行"
fi

echo -e "\n${YELLOW}[5. 开发辅助工具检查]${NC}"
check "Node.js 环境" "node -v"
check "Claude Code 安装状态" "claude --version"

# 总结报告
echo -e "\n${BLUE}============================================================${NC}"
echo -e "总计检查项: $((PASS + FAIL))"
echo -e "通过: ${GREEN}$PASS${NC}"
echo -e "失败: ${RED}$FAIL${NC}"
echo -e "${BLUE}============================================================${NC}"

if [ $FAIL -gt 0 ]; then
    echo -e "\n${YELLOW}建议操作:${NC}"
    echo -e "1. 若 Python 库失败: ${CYAN}conda run -n fintech pip install tushare akshare sqlalchemy${NC}"
    echo -e "2. 若缺少模型: ${CYAN}ollama pull qwen2.5:7b${NC}"
fi
