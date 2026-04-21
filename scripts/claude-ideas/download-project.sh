#!/bin/bash
# ============================================================
# download-project.sh
# Downloads a built Claude project from the homelab server to
# your local machine via rsync over Tailscale/SSH.
#
# Run this on your LOCAL machine (not the server).
#
# Usage:
#   ./download-project.sh                  # interactive — lists & lets you pick
#   ./download-project.sh <slug>           # download specific project slug
#   ./download-project.sh <slug> ~/dest/   # download to specific local path
#
# Environment overrides:
#   HOMELAB_HOST     Tailscale IP or hostname (default: 100.87.156.88)
#   HOMELAB_USER     SSH user                 (default: luis)
#   HOMELAB_SSH_KEY  Path to SSH private key  (default: ~/.ssh/id_ed25519)
# ============================================================

set -euo pipefail

SERVER_HOST="${HOMELAB_HOST:-100.87.156.88}"
SERVER_USER="${HOMELAB_USER:-luis}"
SSH_KEY="${HOMELAB_SSH_KEY:-$HOME/.ssh/id_ed25519}"
BUILD_DIR="/home/$SERVER_USER/claude-builds"
LOCAL_BASE="${3:-$HOME/Downloads/claude-projects}"

SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=8 $SERVER_USER@$SERVER_HOST"

# ── Helpers ────────────────────────────────────────────────────────────

echo ""
echo "  Claude Project Downloader"
echo "  Server: $SERVER_USER@$SERVER_HOST"
echo ""

# Test connection
if ! $SSH_CMD "echo ok" &>/dev/null; then
  echo "  ERROR: Cannot connect to $SERVER_USER@$SERVER_HOST"
  echo "  Make sure Tailscale is up and SSH key is correct."
  echo "  Test with: ssh -i $SSH_KEY $SERVER_USER@$SERVER_HOST 'echo ok'"
  exit 1
fi

# ── List available projects ────────────────────────────────────────────

PROJECTS=$($SSH_CMD "ls -1t $BUILD_DIR 2>/dev/null" || echo "")

if [[ -z "$PROJECTS" ]]; then
  echo "  No built projects found at $BUILD_DIR on the server."
  echo "  Trigger a build from the dashboard first."
  exit 1
fi

# ── Select project ─────────────────────────────────────────────────────

SLUG="${1:-}"

if [[ -z "$SLUG" ]]; then
  echo "  Available projects (newest first):"
  echo ""
  i=1
  while IFS= read -r proj; do
    # Get size and last modified from server
    INFO=$($SSH_CMD "du -sh $BUILD_DIR/$proj 2>/dev/null | cut -f1" || echo "?")
    printf "    [%2d]  %-35s  %s\n" "$i" "$proj" "$INFO"
    i=$((i+1))
  done <<< "$PROJECTS"

  echo ""
  read -rp "  Pick a number (or type a slug directly): " CHOICE

  if [[ "$CHOICE" =~ ^[0-9]+$ ]]; then
    SLUG=$(echo "$PROJECTS" | sed -n "${CHOICE}p")
    if [[ -z "$SLUG" ]]; then
      echo "  Invalid selection."
      exit 1
    fi
  else
    SLUG="$CHOICE"
  fi
fi

# Validate slug exists on server
if ! $SSH_CMD "test -d $BUILD_DIR/$SLUG" 2>/dev/null; then
  echo "  ERROR: Project '$SLUG' not found at $BUILD_DIR/$SLUG on server."
  exit 1
fi

LOCAL_DEST="${2:-$LOCAL_BASE}"
mkdir -p "$LOCAL_DEST"

echo ""
echo "  Downloading: $SLUG"
echo "  From:        $SERVER_USER@$SERVER_HOST:$BUILD_DIR/$SLUG"
echo "  To:          $LOCAL_DEST/$SLUG"
echo ""

# ── Rsync ──────────────────────────────────────────────────────────────

rsync -avz --progress \
  --exclude='node_modules/' \
  --exclude='.next/' \
  --exclude='__pycache__/' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='dist/' \
  --exclude='build/' \
  --exclude='.git/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  "$SERVER_USER@$SERVER_HOST:$BUILD_DIR/$SLUG" \
  "$LOCAL_DEST/"

FINAL="$LOCAL_DEST/$SLUG"

echo ""
echo "  Done. Saved to: $FINAL"
echo ""

# ── Open in editor / show tree ─────────────────────────────────────────

if command -v code &>/dev/null; then
  read -rp "  Open in VS Code? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] && code "$FINAL"
fi

if command -v tree &>/dev/null; then
  echo ""
  tree -L 2 "$FINAL" 2>/dev/null || true
else
  echo ""
  find "$FINAL" -maxdepth 2 -not -path '*/.git/*' 2>/dev/null | sort \
    | sed "s|$FINAL||" | sed 's|^/||' | grep -v '^$' || true
fi
