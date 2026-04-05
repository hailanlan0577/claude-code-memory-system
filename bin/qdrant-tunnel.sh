#!/bin/bash
# OpenClaw Remote Search SSH Tunnel - 智能切换局域网/Cloudflare
# 用途：localhost:26333 → macmini:6333，供 search_openclaw_memory 按需搜索 Mac Mini Qdrant
# 本地 Qdrant 已运行在 Docker localhost:6333，此隧道仅用于远程搜索

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="/Users/YOUR_USERNAME"

LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"
SSH_OPTS="-o ServerAliveInterval=60 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new -o BatchMode=yes"

# 尝试局域网直连
if ssh -o ConnectTimeout=3 -o BatchMode=yes macmini "echo ok" >/dev/null 2>&1; then
    echo "$LOG_PREFIX 局域网直连可用，使用 macmini (LAN)"
    exec /usr/bin/ssh -N -L 26333:localhost:6333 macmini $SSH_OPTS
else
    echo "$LOG_PREFIX 局域网不可达，使用 macmini-remote (Cloudflare Tunnel)"
    exec /usr/bin/ssh -N -L 26333:localhost:6333 macmini-remote $SSH_OPTS
fi
