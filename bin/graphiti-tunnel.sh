#!/bin/bash
# Local Graphiti MCP Server
# 用途：启动本地 Graphiti MCP（连接本地 Docker Neo4j），端口 18001
# 迁移后不再需要 SSH 隧道，Graphiti 直接运行在 MacBook Pro

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="/Users/YOUR_USERNAME"

LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"
GRAPHITI_DIR="$HOME/graphiti-local/mcp_server"

cd "$GRAPHITI_DIR" || { echo "$LOG_PREFIX 目录不存在: $GRAPHITI_DIR"; exit 1; }

echo "$LOG_PREFIX 启动本地 Graphiti MCP (port 18001)..."
exec "$GRAPHITI_DIR/venv/bin/python" src/graphiti_mcp_server.py --transport http --port 18001
