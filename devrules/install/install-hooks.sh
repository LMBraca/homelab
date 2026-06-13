#!/usr/bin/env bash
# Installs the devrules SessionStart (read) + Stop (write) hooks for the current
# user. Run once per device. Idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_SRC="$SCRIPT_DIR/../hooks"
HOOKS_DST="$HOME/.claude/hooks"
SETTINGS="$HOME/.claude/settings.json"

mkdir -p "$HOOKS_DST"
cp "$HOOKS_SRC/session-start.py" "$HOOKS_DST/devrules-session-start.py"
cp "$HOOKS_SRC/session-stop.py"  "$HOOKS_DST/devrules-session-stop.py"
chmod +x "$HOOKS_DST/devrules-session-start.py" "$HOOKS_DST/devrules-session-stop.py"
echo "Installed hooks -> $HOOKS_DST"

python3 - "$SETTINGS" "$HOOKS_DST" <<'PY'
import json, os, sys

settings_path, hooks_dst = sys.argv[1], sys.argv[2]
wanted = {
    "SessionStart": f"python3 {hooks_dst}/devrules-session-start.py",
    "Stop":         f"python3 {hooks_dst}/devrules-session-stop.py",
}

try:
    with open(settings_path) as f:
        cfg = json.load(f)
except FileNotFoundError:
    cfg = {}
except json.JSONDecodeError:
    sys.exit(f"ERROR: {settings_path} is not valid JSON; refusing to touch it.")

hooks = cfg.setdefault("hooks", {})
changed = False
for event, command in wanted.items():
    entries = hooks.setdefault(event, [])
    marker = command.split()[-1]  # the script path
    present = any(
        marker in h.get("command", "")
        for entry in entries
        for h in entry.get("hooks", [])
    )
    if present:
        print(f"{event} hook already registered.")
    else:
        entries.append({"hooks": [{"type": "command", "command": command}]})
        changed = True
        print(f"Registered {event} hook.")

if changed:
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print(f"Updated {settings_path}")
PY

echo "Done. New sessions auto-load context; finishing a session prompts a save."
