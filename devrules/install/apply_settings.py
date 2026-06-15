#!/usr/bin/env python3
"""Idempotently register the devrules SessionStart + Stop hooks in one
settings.json. Shared by install.sh (macOS/Linux) and install.ps1 (Windows) so
the JSON-merge logic is identical on every platform.

Usage: apply_settings.py <settings.json> <start_command> <stop_command>
"""

import json
import os
import sys

MARKER = "devrules-session"  # identifies our hook entries by script filename


def main() -> None:
    settings_path, start_cmd, stop_cmd = sys.argv[1], sys.argv[2], sys.argv[3]
    wanted = {"SessionStart": start_cmd, "Stop": stop_cmd}

    try:
        with open(settings_path) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        cfg = {}
    except json.JSONDecodeError:
        sys.exit(f"  ERROR: {settings_path} is not valid JSON; left untouched.")

    hooks = cfg.setdefault("hooks", {})
    for event, command in wanted.items():
        entries = hooks.setdefault(event, [])
        # Drop any prior devrules entries (so re-running updates the path/cmd),
        # then add the current one back.
        for entry in entries:
            entry["hooks"] = [
                h for h in entry.get("hooks", []) if MARKER not in h.get("command", "")
            ]
        entries[:] = [e for e in entries if e.get("hooks")]
        entries.append({"hooks": [{"type": "command", "command": command}]})

    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print(f"  hooks wired -> {settings_path}")


if __name__ == "__main__":
    main()
