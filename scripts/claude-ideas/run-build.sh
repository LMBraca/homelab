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
MODEL="${3:-claude-sonnet-4-5}"
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
PROMPT_CONTENT="$(cat "$PROMPT_FILE")"

cd "$PROJECT_DIR"

claude -p "$PROMPT_CONTENT" \
    --model "$MODEL" \
    --no-session-persistence \
    --allowedTools "Bash,Edit,Write,Read,Glob,Grep" \
    >> "$LOG_FILE" 2>&1 || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Claude command failed" >> "$LOG_FILE"
    write_status "error" "Claude Code failed — check the log for details"
    rm -f "$PROMPT_FILE"
    exit 1
}

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
