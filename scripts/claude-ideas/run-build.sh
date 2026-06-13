#!/bin/bash
# ============================================================
# run-build.sh
# Triggered by the dashboard API to build a project using Claude Code.
# Runs on the HOST (not inside Docker).
#
# Usage: ./run-build.sh <build-id> <account> <model> <project-slug> <prompt-file>
#
# Writes status to /opt/claude-ideas/builds/<build-id>.json
# Outputs project to ~/claude-builds/<project-slug>/
# Zips result to /opt/claude-ideas/builds/<build-id>.zip
# ============================================================

set -euo pipefail

BUILD_ID="${1:-}"
ACCOUNT="${2:-1}"
MODEL="${3:-claude-sonnet-4-6}"
PROJECT_SLUG="${4:-project}"
PROMPT_FILE="${5:-}"

BUILDS_DIR="/opt/claude-ideas/builds"
STATUS_FILE="$BUILDS_DIR/${BUILD_ID}.json"
LOG_FILE="$BUILDS_DIR/${BUILD_ID}.log"
BUILD_ROOT="$HOME/claude-builds"
PROJECT_DIR="$BUILD_ROOT/$PROJECT_SLUG"

if [[ -z "$BUILD_ID" || -z "$PROMPT_FILE" || ! -f "$PROMPT_FILE" ]]; then
    echo "Usage: $0 <build-id> <account> <model> <project-slug> <prompt-file>"
    exit 1
fi

mkdir -p "$BUILDS_DIR" "$BUILD_ROOT"

write_status() {
    local status="$1"
    local message="$2"
    local extra="${3:-}"
    cat > "$STATUS_FILE" <<EOF
{
  "build_id": "$BUILD_ID",
  "account": "$ACCOUNT",
  "model": "$MODEL",
  "project_slug": "$PROJECT_SLUG",
  "status": "$status",
  "message": "$message",
  "started_at": "$STARTED_AT",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "project_dir": "$PROJECT_DIR",
  "zip_path": "$BUILDS_DIR/${BUILD_ID}.zip"
  $extra
}
EOF
}

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
write_status "running" "Setting up project directory…"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Build $BUILD_ID starting (account=$ACCOUNT model=$MODEL slug=$PROJECT_SLUG)" >> "$LOG_FILE"

# ── Set up project directory ───────────────────────────────────────────
if [[ -d "$PROJECT_DIR" ]]; then
    mv "$PROJECT_DIR" "${PROJECT_DIR}_backup_$(date +%s)"
fi
mkdir -p "$PROJECT_DIR"

export CLAUDE_CONFIG_DIR="$HOME/.claude-account-$ACCOUNT"

write_status "running" "Claude Code is scaffolding the project…"

# ── Run Claude Code ────────────────────────────────────────────────────
# Wrap in `timeout` so a hung dev-server invocation (npm run dev, tsx watch,
# etc.) cannot pin the build at "running" forever. The enclosing systemd
# scope (set up by build-watcher.sh) will reap any leftover children once
# this script exits.
PROMPT_CONTENT="$(cat "$PROMPT_FILE")"
# Tunable via /api/settings (builds.timeout_minutes). Default = 10min.
SETTINGS_FILE="${SETTINGS_FILE:-/opt/claude-ideas/settings.json}"
BUILD_TIMEOUT_MIN=$(python3 - "$SETTINGS_FILE" <<'PYEOF' 2>/dev/null || echo 10
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(int(json.load(f).get("builds", {}).get("timeout_minutes") or 10))
except Exception:
    print(10)
PYEOF
)
BUILD_TIMEOUT_SEC=$(( BUILD_TIMEOUT_MIN * 60 ))

cd "$PROJECT_DIR"

LOG_SIZE_BEFORE=$(stat -c '%s' "$LOG_FILE" 2>/dev/null || echo 0)

CLAUDE_EXIT=0
timeout --signal=TERM --kill-after=30s "$BUILD_TIMEOUT_SEC" \
    claude -p "$PROMPT_CONTENT" \
        --model "$MODEL" \
        --no-session-persistence \
        --allowedTools "Bash,Edit,Write,Read,Glob,Grep" \
        >> "$LOG_FILE" 2>&1 || CLAUDE_EXIT=$?

if [[ $CLAUDE_EXIT -ne 0 ]]; then
    LOG_SIZE_AFTER=$(stat -c '%s' "$LOG_FILE" 2>/dev/null || echo 0)
    LOG_GREW=$((LOG_SIZE_AFTER - LOG_SIZE_BEFORE))

    if [[ $CLAUDE_EXIT -eq 124 || $CLAUDE_EXIT -eq 137 ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Claude timed out after ${BUILD_TIMEOUT_SEC}s" >> "$LOG_FILE"
        write_status "error" "Build timed out after $((BUILD_TIMEOUT_SEC / 60))m — likely hung on a long-running command"
    elif [[ $LOG_GREW -lt 32 ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Claude produced no output before exit $CLAUDE_EXIT — likely API hang" >> "$LOG_FILE"
        write_status "error" "Claude produced no output (exit $CLAUDE_EXIT) — likely an API/network hang, try rebuilding"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Claude command failed (exit $CLAUDE_EXIT)" >> "$LOG_FILE"
        write_status "error" "Claude Code failed (exit $CLAUDE_EXIT) — check the log for details"
    fi
    rm -f "$PROMPT_FILE"
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Claude Code finished. Zipping..." >> "$LOG_FILE"
write_status "zipping" "Build complete — creating zip…"

# ── Zip the project ────────────────────────────────────────────────────
ZIP_FILE="$BUILDS_DIR/${BUILD_ID}.zip"
cd "$BUILD_ROOT"

python3 - "$PROJECT_SLUG" "$ZIP_FILE" <<'PYEOF' >> "$LOG_FILE" 2>&1
import sys, os, zipfile
slug    = sys.argv[1]
out     = sys.argv[2]
EXCLUDE = {'.git', 'node_modules', '__pycache__', '.next', 'venv', '.venv', 'dist', 'build'}
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(slug):
        dirs[:] = [d for d in dirs if d not in EXCLUDE]
        for fname in files:
            fpath = os.path.join(root, fname)
            zf.write(fpath)
print(f"Zip created: {out}")
PYEOF

ZIP_SIZE=$(du -sh "$ZIP_FILE" 2>/dev/null | cut -f1 || echo "?")
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Zip created: $ZIP_FILE ($ZIP_SIZE)" >> "$LOG_FILE"

rm -f "$PROMPT_FILE"

write_status "done" "Project ready — $ZIP_SIZE zip" ", \"zip_size\": \"$ZIP_SIZE\""

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Build $BUILD_ID complete." >> "$LOG_FILE"
