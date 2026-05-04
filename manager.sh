#!/bin/bash

# ============================================================
# Fintech System 综合管理控制台 (Liam 专用完整版)
# ============================================================

# Color definitions
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

# Clear screen and show header
clear
echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}              Fintech 系统综合管理控制台 (AMD 版)           ${NC}"
echo -e "${BLUE}============================================================${NC}"

# Menu function
show_menu() {
    echo -e "\n${CYAN}[ 基础管理 ]${NC}"
    echo -e " 1) 🚀 运行系统自检 (Check)       - 验证驱动、数据库及环境"
    echo -e " 2) ▶️  启动数据库容器 (Start)      - 开启 PostgreSQL 服务"
    echo -e " 3) 🛑 停止数据库容器 (Stop)       - 安全关闭服务"
    
    echo -e "\n${CYAN}[ 数据与量化 ]${NC}"
    echo -e " 4) 📈 执行数据流测试 (Verify)     - 抓取实时行情并入库"
    echo -e " 5) 💾 数据库命令行 (psql)        - 直接查询数据库表"
    echo -e " 6) 📊 运行股票分析示例 (Analyze)  - 计算涨跌幅排行榜"
    
    echo -e "\n${CYAN}[ AI 辅助 ]${NC}"
    echo -e " 7) 🤖 启动本地 AI (Qwen)         - 使用 Ollama 进行对话"
    echo -e " 8) 📂 开启 Claude Code           - AI 辅助编程与策略优化"
    
    echo -e "\n${CYAN}[ 其他 ]${NC}"
    echo -e " m) 监控显卡状态 (AMD GPU)        - 查看 RX 7600 负载"
    echo -e " q) 退出系统 (Exit)"
    echo -e "${BLUE}------------------------------------------------------------${NC}"
    echo -ne "${YELLOW}请选择操作序号: ${NC}"
}

# Main loop
while true; do
    show_menu
    read -r opt
    case $opt in
        1)
            if [ -f "./check_config.sh" ]; then
                ./check_config.sh
            else
                echo -e "${RED}错误: 未找到 check_config.sh${NC}"
            fi
            ;;
        2)
            docker start fintech_pg && echo -e "${GREEN}数据库已启动${NC}"
            ;;
        3)
            docker stop fintech_pg && echo -e "${YELLOW}数据库已停止${NC}"
            ;;
        4)
            conda run -n fintech python verify_data_flow.py
            ;;
        5)
            echo -e "${GREEN}提示: 输入 \dt 查看表，输入 \q 退出${NC}"
            docker exec -it fintech_pg psql -U postgres -d fintech_db
            ;;
        6)
            if [ -f "./stock_analyzer.py" ]; then
                conda run -n fintech python stock_analyzer.py
            else
                echo -e "${RED}错误: 请先创建 stock_analyzer.py 文件${NC}"
            fi
            ;;
        7)
            ollama run qwen2.5:7b
            ;;
        8)
            claude
            ;;
        m)
            if command -v rocm-smi &>/dev/null; then
                rocm-smi
            else
                echo -e "${YELLOW}尝试通过内核接口读取 GPU 负载...${NC}"
                watch -n 1 cat /sys/class/drm/card0/device/gpu_busy_percent
            fi
            ;;
        q)
            echo -e "${GREEN}祝你交易顺利，再见！${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}无效选项，请重新输入。${NC}"
            ;;
    esac
    
    echo -e "\n${BLUE}操作完成。按任意键返回菜单...${NC}"
    read -n 1
    clear
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${BLUE}              Fintech 系统综合管理控制台 (AMD 版)           ${NC}"
    echo -e "${BLUE}============================================================${NC}"
done
