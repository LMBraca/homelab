#!/usr/bin/env bash
# devrules installer for macOS / Linux.
# Wires the devrules MCP + read/write hooks into EVERY Claude config dir on this
# machine (so all your accounts get it, not just the default). Run once per
# machine; re-run any time to update.
#
#   ./install.sh                       # auto-detect ~/.claude and ~/.claude-*
#   ./install.sh ~/.claude-account1 …  # or target specific config dirs
#
# Override the server with DEVRULES_URL=http://host:port
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARE="$HOME/.devrules/hooks"
BASE="${DEVRULES_URL:-http://100.87.156.88:8799}"
URL="${BASE%/}/mcp"

PYBIN="$(command -v python3 || command -v python || true)"
[ -z "$PYBIN" ] && { echo "ERROR: python3 (or python) not found on PATH."; exit 1; }
CLAUDE_BIN="$(command -v claude || true)"
[ -z "$CLAUDE_BIN" ] && { echo "ERROR: claude CLI not found on PATH."; exit 1; }

# 1. Install the hook scripts to a shared location (not tied to one account).
mkdir -p "$SHARE"
cp "$SCRIPT_DIR/../hooks/session-start.py" "$SHARE/devrules-session-start.py"
cp "$SCRIPT_DIR/../hooks/session-stop.py"  "$SHARE/devrules-session-stop.py"
chmod +x "$SHARE"/devrules-session-*.py
START="$PYBIN $SHARE/devrules-session-start.py"
STOP="$PYBIN $SHARE/devrules-session-stop.py"
echo "Hooks installed -> $SHARE"

# 2. Pick the config dirs to wire.
if [ "$#" -gt 0 ]; then
  DIRS=("$@")
else
  DIRS=()
  for d in "$HOME/.claude" "$HOME"/.claude-*; do
    [ -d "$d" ] && DIRS+=("$d")
  done
fi
[ "${#DIRS[@]}" -eq 0 ] && DIRS=("$HOME/.claude")

echo "Wiring ${#DIRS[@]} config dir(s) -> $URL"
for d in "${DIRS[@]}"; do
  echo "== $d =="
  mkdir -p "$d"
  if [ "$d" = "$HOME/.claude" ]; then
    # Default config dir: user-scope MCP lives in ~/.claude.json (home), which
    # Claude reads only when CLAUDE_CONFIG_DIR is UNSET — that's what a bare
    # `claude` and the VSCode extension use. Setting CLAUDE_CONFIG_DIR=~/.claude
    # would wrongly write the nested ~/.claude/.claude.json that nothing reads.
    env -u CLAUDE_CONFIG_DIR "$CLAUDE_BIN" mcp remove devrules --scope user >/dev/null 2>&1 || true
    env -u CLAUDE_CONFIG_DIR "$CLAUDE_BIN" mcp add --transport http devrules "$URL" --scope user >/dev/null
  else
    CLAUDE_CONFIG_DIR="$d" "$CLAUDE_BIN" mcp remove devrules --scope user >/dev/null 2>&1 || true
    CLAUDE_CONFIG_DIR="$d" "$CLAUDE_BIN" mcp add --transport http devrules "$URL" --scope user >/dev/null
  fi
  echo "  MCP registered"
  "$PYBIN" "$SCRIPT_DIR/apply_settings.py" "$d/settings.json" "$START" "$STOP"
done

echo ""
echo "Done. Start a fresh session in any account — context auto-loads, and"
echo "finishing a session prompts a save. Verify with: claude mcp list"
