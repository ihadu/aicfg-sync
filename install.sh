#!/bin/bash
# aicfg-sync 安装脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/aicfg-sync"
BIN_DIR="$HOME/.local/bin"

echo "=========================================="
echo "  aicfg-sync 安装程序"
echo "  AI 编程工具配置同步工具"
echo "=========================================="
echo ""

# 检查 Python 版本
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &> /dev/null; then
        VERSION=$($cmd -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null || echo "0")
        MAJOR=$(echo "$VERSION" | cut -d. -f1)
        MINOR=$(echo "$VERSION" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 9 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "❌ 错误: 需要 Python 3.9 或更高版本"
    echo "   请安装 Python 3.9+ 后重试"
    exit 1
fi

echo "✅ Python 版本: $($PYTHON_CMD --version)"

# 检查 iCloud Drive
ICLOUD_PATH="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
if [ ! -d "$ICLOUD_PATH" ]; then
    echo "⚠️  警告: iCloud Drive 路径不存在"
    echo "   请确保已登录 iCloud 并启用 iCloud Drive"
    echo "   路径: $ICLOUD_PATH"
else
    echo "✅ iCloud Drive 已就绪"
fi

# 创建安装目录
echo ""
echo "📁 安装目录: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

# 复制文件
echo "📦 复制文件..."
cp "$SCRIPT_DIR"/*.py "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/templates" "$INSTALL_DIR/"

# 创建启动脚本
cat > "$BIN_DIR/aicfg-sync" << 'EOF'
#!/bin/bash
# aicfg-sync 启动脚本

INSTALL_DIR="$HOME/.local/share/aicfg-sync"
exec python3 "$INSTALL_DIR/cli.py" "$@"
EOF

chmod +x "$BIN_DIR/aicfg-sync"

# 检查 PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo ""
    echo "⚠️  警告: $BIN_DIR 不在 PATH 中"
    echo "   请添加以下行到你的 ~/.zshrc 或 ~/.bash_profile:"
    echo "   export PATH=\"$BIN_DIR:\$PATH\""
fi

echo ""
echo "✅ 安装完成!"
echo ""
echo "使用方法:"
echo "  aicfg-sync init       # 初始化配置"
echo "  aicfg-sync push       # 推送配置到 iCloud"
echo "  aicfg-sync pull       # 从 iCloud 拉取配置"
echo "  aicfg-sync status     # 查看同步状态"
echo ""
echo "如果命令找不到，请运行:"
echo "  export PATH=\"$BIN_DIR:\$PATH\""
echo ""

# 尝试初始化
if [ -d "$ICLOUD_PATH" ]; then
    echo "🚀 正在初始化配置..."
    "$BIN_DIR/aicfg-sync" init || true
fi

echo "=========================================="
