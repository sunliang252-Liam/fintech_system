#!/bin/bash

# ============================================================
# Fintech 系统全量备份工具 (Liam 专用)
# 功能：备份数据库数据、代码脚本、环境配置
# ============================================================

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 定义变量
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="fintech_full_backup_$TIMESTAMP"
BACKUP_DIR="$HOME/$BACKUP_NAME"
TARGET_FILE="$HOME/${BACKUP_NAME}.tar.gz"

echo -e "${BLUE}开始执行系统全量备份...${NC}"

# 1. 创建临时备份目录
mkdir -p "$BACKUP_DIR"

# 2. 导出 PostgreSQL 数据库 (最核心的数据)
echo -e "${YELLOW}正在导出数据库 (PostgreSQL)...${NC}"
if docker ps | grep -q fintech_pg; then
    docker exec fintech_pg pg_dump -U postgres fintech_db > "$BACKUP_DIR/database_dump.sql"
    echo -e "${GREEN}-> 数据库导出成功。${NC}"
else
    echo -e "${RED}错误: 数据库容器未启动，无法导出数据！${NC}"
fi

# 3. 导出 Conda 环境依赖列表
echo -e "${YELLOW}正在导出 Python 环境配置 (Conda)...${NC}"
conda env export -n fintech > "$BACKUP_DIR/environment.yml"
echo -e "${GREEN}-> 环境配置导出成功。${NC}"

# 4. 拷贝所有代码和管理脚本
echo -e "${YELLOW}正在归档代码文件...${NC}"
cp -r "$HOME/fintech_system/"* "$BACKUP_DIR/"
# 移除可能存在的旧备份文件，避免循环嵌套
rm -f "$BACKUP_DIR"/*.tar.gz

# 5. 压缩成一个文件
echo -e "${YELLOW}正在创建最终压缩包...${NC}"
tar -czvf "$TARGET_FILE" -C "$HOME" "$BACKUP_NAME" > /dev/null

# 6. 清理临时目录
rm -rf "$BACKUP_DIR"

echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}✅ 备份圆满完成！${NC}"
echo -e "备份文件路径: ${YELLOW}$TARGET_FILE${NC}"
echo -e "文件大小: $(du -h "$TARGET_FILE" | cut -f1)"
echo -e "${BLUE}------------------------------------------------------------${NC}"
echo -e "你可以通过以下方式将此文件传输到笔记本："
echo -e "1. 使用 U 盘拷贝。"
echo -e "2. 使用 scp 命令 (如果网络相通)。"
echo -e "3. 使用网盘或即时通讯工具。"
echo -e "${BLUE}============================================================${NC}"
