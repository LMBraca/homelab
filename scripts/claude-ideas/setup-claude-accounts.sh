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
    echo "[1/5] Installing Claude Code via npm..."
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
    echo "[1/5] Claude Code already installed: $(claude --version)"
fi

# Step 2: Create output directory
echo "[2/5] Creating output directory..."
sudo mkdir -p /opt/claude-ideas
sudo chown "$(whoami):$(whoami)" /opt/claude-ideas

# Step 3: Create separate config directories for each account
echo "[3/5] Creating config directories for 3 accounts..."
mkdir -p ~/.claude-account-1
mkdir -p ~/.claude-account-2
mkdir -p ~/.claude-account-3

# Step 4: Subscription login for ~/.claude-account-N/.credentials.json.
# This is needed by fetch-claude-limits.sh to hit api.anthropic.com/api/oauth/usage,
# which requires a short-lived subscription access token (a long-lived
# CLAUDE_CODE_OAUTH_TOKEN does NOT work against that endpoint).
#
# NOTE on Claude Code v2: bare `claude login` no longer performs a login —
# it drops you into an interactive chat session. The correct unattended flow
# in v2 is to let `claude setup-token` drive the browser auth (step [5/5]),
# which implicitly populates .credentials.json for the account it authorizes.
# That means this step is largely a no-op when [5/5] runs successfully for
# each account; we keep it only as a fallback for accounts where you want to
# prime .credentials.json without minting a long-lived token (e.g. skipping
# step [5/5] for an account).
echo "[4/5] (Optional) Prime subscription credentials."
echo ""
echo "In Claude Code v2, step [5/5] below also populates .credentials.json"
echo "as a side effect of 'claude setup-token'. You only need this step if"
echo "you plan to SKIP the long-lived-token step for one or more accounts."
echo ""
read -p "Run the subscription-login step for all 3 accounts? [y/N] " run_login_step
if [[ "$run_login_step" =~ ^[Yy]$ ]]; then
    for i in 1 2 3; do
        echo "============================================"
        echo "  Subscription login: Account $i of 3"
        echo "============================================"
        echo "A browser will open. Log in with account #$i."
        echo "After 'Login successful', close the browser and exit the CLI (Ctrl+C twice)."
        echo ""
        read -p "Press Enter to continue (or type 'skip' to skip this account): " choice
        if [[ "$choice" == "skip" ]]; then
            echo "Skipped account $i."
            continue
        fi

        # `claude /login` invokes the slash-command login flow directly from
        # the shell in v2. If this stops working on a future version, fall
        # back to `claude setup-token` which also writes .credentials.json.
        CLAUDE_CONFIG_DIR=~/.claude-account-$i claude /login || {
            echo "claude /login failed for account $i — will try via setup-token in step [5/5]."
            continue
        }
        echo "Account $i subscription login complete."
        echo ""
    done
else
    echo "Skipping explicit subscription login. Step [5/5] will handle it."
fi

# Step 5: Generate long-lived OAuth tokens for the idea generator.
# These are valid for 1 year, don't rotate on use, and live in
# /opt/claude-ideas/oauth-tokens.env — sourced by claude-idea-generator.sh.
# This is what makes the generator resilient to refresh-token races and
# keepalive outages. Requires a Pro/Max/Team/Enterprise plan per account.
echo "[5/5] Generate long-lived OAuth tokens (one per account)."
echo ""
echo "Each account needs its own long-lived token (valid 1 year)."
echo "'claude setup-token' walks you through OAuth and prints a token."
echo "The token will be copied into /opt/claude-ideas/oauth-tokens.env."
echo ""

TOKENS_FILE="/opt/claude-ideas/oauth-tokens.env"
if [[ -f "$TOKENS_FILE" ]]; then
    echo "NOTE: $TOKENS_FILE already exists. Existing values will be overwritten for any account you re-run below."
    echo ""
fi

# Create/truncate-safely: preserve whatever's there, only replace per-account lines.
touch "$TOKENS_FILE"
chmod 600 "$TOKENS_FILE"

for i in 1 2 3; do
    echo "============================================"
    echo "  Long-lived token: Account $i of 3"
    echo "============================================"
    echo "You'll be prompted to authorize in a browser. The script will capture"
    echo "the printed token automatically — no paste step needed."
    echo ""
    read -p "Press Enter to run 'claude setup-token' for account $i (or type 'skip' to skip): " choice
    if [[ "$choice" == "skip" ]]; then
        echo "Skipped account $i."
        echo ""
        continue
    fi

    # Run setup-token under the account's config dir so the browser flow uses
    # that account's session. Capture stdout+stderr; tee it to the terminal so
    # the browser URL still appears, then extract the sk-ant-oat01- token.
    # The printed token may wrap across multiple terminal lines; we strip CRs
    # and newlines before matching so wrapped output is reassembled correctly.
    tmp_out="$(mktemp)"
    if ! CLAUDE_CONFIG_DIR=~/.claude-account-$i claude setup-token 2>&1 | tee "$tmp_out"; then
        echo "setup-token failed for account $i. You can re-run this script later."
        rm -f "$tmp_out"
        continue
    fi

    # Reassemble the token even if the terminal wrapped it across lines.
    # Strip ANSI color codes, CRs, and newlines, then grep for the first
    # sk-ant-oat01-… substring (valid chars: A-Z a-z 0-9 _ -).
    token="$(
        sed -E 's/\x1b\[[0-9;]*[A-Za-z]//g' "$tmp_out" \
          | tr -d '\r\n' \
          | grep -oE 'sk-ant-oat01-[A-Za-z0-9_-]+' \
          | head -n1
    )"
    rm -f "$tmp_out"

    if [[ -z "$token" || "$token" != sk-ant-oat01-* ]]; then
        echo "WARNING: could not auto-extract token for account $i. Re-run this step,"
        echo "or manually add a line to $TOKENS_FILE of the form:"
        echo "    CLAUDE_TOKEN_${i}=sk-ant-oat01-..."
        echo ""
        continue
    fi

    # Atomic replace of this account's line in the env file.
    tmp="$(mktemp)"
    grep -v "^CLAUDE_TOKEN_${i}=" "$TOKENS_FILE" > "$tmp" || true
    echo "CLAUDE_TOKEN_${i}=${token}" >> "$tmp"
    mv "$tmp" "$TOKENS_FILE"
    chmod 600 "$TOKENS_FILE"
    echo "Stored long-lived token for account $i."
    echo ""
done

echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "Tokens file: $TOKENS_FILE (mode 600)"
echo ""
echo "Next steps:"
echo "  1. Copy claude-idea-generator.sh to the server (push-to-server.sh)"
echo "  2. Install the crontab entries from crontab-entries.txt"
echo "  3. Smoke-test: "
echo "       source $TOKENS_FILE && CLAUDE_CODE_OAUTH_TOKEN=\"\$CLAUDE_TOKEN_1\" \\"
echo "         claude -p 'hello' --model haiku --no-session-persistence"
echo ""
echo "Reminder: long-lived tokens expire after ~1 year. Re-run this script"
echo "(the [5/5] step) to regenerate before they expire."
echo ""
