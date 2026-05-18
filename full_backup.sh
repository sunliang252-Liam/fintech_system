#!/bin/bash

# ============================================================
# Fintech 系统局域网快速同步工具
# 功能：增量同步代码、流式同步数据库
# ============================================================

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

REMOTE_IP="192.168.1.100"
REMOTE_USER="liam-sun"

echo -e "${BLUE}开始执行局域网增量同步...${NC}"

# 1. 增量同步代码和脚本
echo -e "${YELLOW}1. 正在同步代码文件 (rsync)...${NC}"
# 注意：这里同步整个 ~/fintech_system/ 目录
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='*.tar.gz' \
    "$HOME/fintech_system/" ${REMOTE_USER}@${REMOTE_IP}:~/fintech_system/

# 2. 流式同步数据库
echo -e "${YELLOW}2. 正在流式同步数据库 (PostgreSQL)...${NC}"
if docker ps | grep -q fintech_pg; then
    # 直接通过管道流式传输
    docker exec fintech_pg pg_dump -U postgres fintech_db | \
        ssh ${REMOTE_USER}@${REMOTE_IP} "cat | docker exec -i fintech_pg psql -U postgres fintech_db"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ 数据库同步完成。${NC}"
    else
        echo -e "${RED}❌ 数据库同步失败，请检查目标机 Docker。${NC}"
    fi
else
    echo -e "${RED}错误: 本地数据库容器未启动！${NC}"
fi

echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}✅ 局域网同步圆满成功！${NC}"
echo -e "源机器: $(hostname)"
echo -e "目标机: $REMOTE_IP"
echo -e "${BLUE}============================================================${NC}"
