#!/usr/bin/env python3
"""devrules SessionStart hook — forces the read.

Runs when any Claude Code session opens. Derives a stable project key from the
working directory (git remote, else folder name), fetches that project's saved
context from the devrules server, and injects it so a fresh account/machine is
caught up with zero prompting. Fails open so it can never block a session.
"""

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("DEVRULES_URL", "http://100.87.156.88:8799").rstrip("/")


def slugify(value: str) -> str:
    value = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", value)  # scheme
    value = re.sub(r"^[^@/]+@", "", value)                     # user@
    value = re.sub(r"\.git$", "", value)
    value = value.strip().strip("/")
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value[:128] or "unknown"


def project_key(cwd: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            return slugify(r.stdout.strip())
    except Exception:
        pass
    return slugify(os.path.basename(os.path.abspath(cwd)))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()
    key = project_key(cwd)

    context = ""
    try:
        url = f"{BASE_URL}/context?project=" + urllib.parse.quote(key)
        with urllib.request.urlopen(url, timeout=4) as resp:
            context = resp.read().decode("utf-8", "replace")
    except Exception:
        context = ""

    header = (
        "# devrules shared context\n\n"
        f"Your **devrules project key** is `{key}`. Use exactly this key for "
        "every devrules MCP tool call. Your context for this project is stored "
        "remotely (not in this repo); read it below and append to it before you "
        "finish.\n\n"
    )
    additional = header + (context.strip() or
        "_No saved context for this project yet (or the server was unreachable). "
        "If real work happens here, call `context_append` before finishing so the "
        "next account picks up cold._")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional + "\n",
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
