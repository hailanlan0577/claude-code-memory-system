#!/bin/bash
# graphiti-core qwen-plus 兼容性补丁自动应用脚本
# 用途：pip upgrade graphiti-core 后重新打补丁
# 用法：cd ~/graphiti-local/patches && ./apply-patches.sh

set -e

SITE_PACKAGES="$HOME/graphiti-local/mcp_server/venv/lib/python3.11/site-packages/graphiti_core"
PATCH_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$SITE_PACKAGES" ]; then
    echo "❌ graphiti_core 未找到: $SITE_PACKAGES"
    exit 1
fi

echo "=== 应用 qwen-plus 兼容补丁 ==="
echo "目标: $SITE_PACKAGES"
echo ""

# 清除 pyc 缓存
find "$SITE_PACKAGES" -name "*.pyc" -delete
echo "✅ 已清除 pyc 缓存"

# 应用补丁（--dry-run 先测试）
for patch_file in prompts.patch maintenance.patch llm_client.patch; do
    if [ -f "$PATCH_DIR/$patch_file" ]; then
        echo ""
        echo "--- 应用 $patch_file ---"
        if patch -p0 --dry-run -d / < "$PATCH_DIR/$patch_file" > /dev/null 2>&1; then
            patch -p0 -d / < "$PATCH_DIR/$patch_file"
            echo "✅ $patch_file 成功"
        else
            echo "⚠️  $patch_file 无法直接应用（可能版本已变化），尝试 --fuzz..."
            if patch -p0 --fuzz=3 -d / < "$PATCH_DIR/$patch_file"; then
                echo "✅ $patch_file 模糊匹配成功"
            else
                echo "❌ $patch_file 失败，需要手动检查"
            fi
        fi
    fi
done

# 再次清除 pyc 确保新代码生效
find "$SITE_PACKAGES" -name "*.pyc" -delete

echo ""
echo "=== 完成 ==="
echo "请重启 Graphiti MCP: launchctl kickstart -k gui/\$(id -u)/com.graphiti.tunnel"
