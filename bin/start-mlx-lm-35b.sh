#!/bin/bash
# 启动 mlx_lm.server 加载 Qwen3.6-35B-A3B BF16 给 Graphiti 用
# 端口: 8081

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="/Users/YOUR_MACSTUDIO_USER"

LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"
echo "$LOG_PREFIX 启动 mlx_lm.server (Qwen3.6-35B-A3B-bf16, 8081)"

exec /Users/YOUR_MACSTUDIO_USER/.local/bin/mlx_lm.server \
  --model /Users/YOUR_MACSTUDIO_USER/models/Qwen3.6-35B-A3B-bf16 \
  --host 0.0.0.0 --port 8081
