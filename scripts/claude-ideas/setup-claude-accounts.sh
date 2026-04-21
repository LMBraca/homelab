#!/bin/bash
# ============================================================
# Setup script for 3 Claude Code accounts on the homelab server
# Run this ONCE on the server to install Claude Code and
# configure 3 separate authentication profiles.
# ============================================================

set -e

echo "============================================"
echo "  Claude Code Multi-Account Setup"
echo "============================================"
echo ""

# Step 1: Install Claude Code (if not installed)
if ! command -v claude &> /dev/null; then
    echo "[1/4] Installing Claude Code via npm..."
    # Ensure Node.js is available
    if ! command -v node &> /dev/null; then
        echo "ERROR: Node.js is not installed."
        echo "Install it first: sudo apt install -y nodejs npm"
        echo "Or use nvm: https://github.com/nvm-sh/nvm"
        exit 1
    fi
    npm install -g @anthropic-ai/claude-code
    echo "Claude Code installed successfully."
else
    echo "[1/4] Claude Code already installed: $(claude --version)"
fi

# Step 2: Create output directory
echo "[2/4] Creating output directory..."
sudo mkdir -p /opt/claude-ideas
sudo chown "$(whoami):$(whoami)" /opt/claude-ideas

# Step 3: Create separate config directories for each account
echo "[3/4] Creating config directories for 3 accounts..."
mkdir -p ~/.claude-account-1
mkdir -p ~/.claude-account-2
mkdir -p ~/.claude-account-3

# Step 4: Authenticate each account
echo "[4/4] Time to authenticate each account."
echo ""
echo "You need to log in 3 times, once per account."
echo "Each login will open a browser window."
echo ""

for i in 1 2 3; do
    echo "============================================"
    echo "  Authenticating Account $i of 3"
    echo "============================================"
    echo "Use your account #$i credentials when the browser opens."
    echo ""
    read -p "Press Enter when ready to authenticate account $i..."

    # Set the config directory for this account and authenticate
    CLAUDE_CONFIG_DIR=~/.claude-account-$i claude login

    echo ""
    echo "Account $i authenticated successfully!"
    echo ""
done

echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Copy claude-idea-generator.sh to the server"
echo "  2. Install the crontab entries from crontab-entries.txt"
echo "  3. Test with: CLAUDE_CONFIG_DIR=~/.claude-account-1 claude -p 'hello' --model haiku"
echo ""
