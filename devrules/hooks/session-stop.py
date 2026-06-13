#!/usr/bin/env python3
"""devrules Stop hook — forces the write.

When Claude tries to end a turn, this checks whether the session did real work
and hasn't yet saved its context. If so, it blocks ONCE and tells Claude to
append a handoff note to devrules first. The block-once guard (stop_hook_active)
plus the "already saved?" transcript check guarantee it can't loop and won't nag
when there's nothing to save.

Fails open: any error allows the stop.
"""

import json
import os
import re
import subprocess
import sys

SAVED_RE = re.compile(r"context_append|context_write")
WORK_RE = re.compile(r'"name"\s*:\s*"(Edit|Write|MultiEdit|NotebookEdit)"')


def slugify(value: str) -> str:
    value = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", value)
    value = re.sub(r"^[^@/]+@", "", value)
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


def allow():
    sys.exit(0)


def block(reason: str):
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        allow()

    # Already continuing because of this hook — never block twice.
    if data.get("stop_hook_active"):
        allow()

    transcript = data.get("transcript_path") or ""
    try:
        text = open(transcript, encoding="utf-8", errors="replace").read()
    except Exception:
        allow()  # can't inspect → don't nag

    saved = bool(SAVED_RE.search(text))
    did_work = bool(WORK_RE.search(text))

    if saved or not did_work:
        allow()

    key = project_key(data.get("cwd") or os.getcwd())
    block(
        f"Before ending: this session changed things but hasn't saved its devrules "
        f"context. Call the `context_append` tool with project key `{key}` and a "
        f"short handoff note — what changed, the current state, and the exact next "
        f"steps — written for a different account picking up cold. If genuinely "
        f"nothing worth handing off happened, you may stop without saving."
    )


if __name__ == "__main__":
    main()
