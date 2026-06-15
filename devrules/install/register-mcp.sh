#!/usr/bin/env bash
# Registers the devrules MCP server with Claude Code at user scope.
# Run once per device (or per CLAUDE_CONFIG_DIR if you keep separate ones).
set -euo pipefail

BASE="${DEVRULES_URL:-http://100.87.156.88:8799}"
URL="${BASE%/}/mcp"

claude mcp remove devrules --scope user >/dev/null 2>&1 || true
claude mcp add --transport http devrules "$URL" --scope user

echo "Registered devrules MCP at $URL (user scope)."
claude mcp list || true
