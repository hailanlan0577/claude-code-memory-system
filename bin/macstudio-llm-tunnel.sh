#!/bin/bash
# Mac Studio LLM SSH Tunnel - 智能切换局域网/Cloudflare
# 用途: localhost:8082 → macstudio:8081 (mlx_lm.server Qwen3.6-35B-A3B BF16)
# 供 Graphiti 实体提取/关系提取调用

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="/Users/YOUR_USERNAME"

LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"
SSH_OPTS="-o ServerAliveInterval=60 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new -o BatchMode=yes"

# 尝试局域网直连 (优先)
if ssh -o ConnectTimeout=3 -o BatchMode=yes macstudio-lan "echo ok" >/dev/null 2>&1; then
    echo "$LOG_PREFIX 局域网直连可用,使用 macstudio-lan (YOUR_MACSTUDIO_LAN_IP)"
    exec /usr/bin/ssh -N -L 8082:localhost:8081 macstudio-lan $SSH_OPTS
elif ssh -o ConnectTimeout=3 -o BatchMode=yes macstudio "echo ok" >/dev/null 2>&1; then
    echo "$LOG_PREFIX 默认 macstudio 别名可用 (含 SSH config 自动切换)"
    exec /usr/bin/ssh -N -L 8082:localhost:8081 macstudio $SSH_OPTS
else
    echo "$LOG_PREFIX 全部不可达,等 5s 重试"
    sleep 5
    exit 1
fi
