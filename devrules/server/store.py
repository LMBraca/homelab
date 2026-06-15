"""Storage for devrules: one markdown file per project, on the homelab.

Layout under DEVRULES_DATA (default /data):

    rules.md                   global rules, prepended to every read
    projects/<key>/context.md  the whole context for one project

Deliberately dumb: a project is a folder, its context is a single markdown file
Claude reads whole and appends to. No taxonomy, no database.
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("DEVRULES_DATA", "/data"))
PROJECTS_DIR = DATA_DIR / "projects"
RULES_FILE = DATA_DIR / "rules.md"
CONTEXT_FILE = "context.md"

# Keys become directory names — no separators or traversal. The hook slugifies
# git remotes / folder names before they get here; this is the safety guard.
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

DEFAULT_RULES = """# devrules — global rules

Injected at the start of every session, for every project, across all accounts
and machines. Keep it short. Project-specific facts (stack, commands,
architecture) belong in that project's context, NOT here.

## Don't be a yes-man
- Tell the user when they're wrong, and why — before doing the thing, not after.
- Push back on flawed plans, risky shortcuts, wrong assumptions, and
  worse-than-available alternatives, even when unasked. Recommend the better
  option plainly.
- Default to the right outcome over agreement. Approval is not the goal.
- Don't abandon a correct position just because the user pushed back — defend it,
  or say what actually changed your mind. Never fake agreement to be agreeable.

## Keep a decision journal
- Log every non-trivial decision in the project context AS you make it, via
  `context_append`: what was decided, the alternatives considered and rejected,
  and the *why*.
- Also record: constraints discovered, assumptions made, dead ends hit, and
  anything a future account would otherwise re-derive or accidentally undo.
- It's append-only and timestamped — a running journal, not a summary you
  overwrite. Treat it as the project's long-term memory.

## Plan before non-trivial work
- Multi-file, unfamiliar, or ambiguous? Explore and write a short plan before
  editing. One-sentence diff? Just do it.

## Verify — don't assert
- Nothing is "done" without a check that passes: tests, build, lint, or
  type-check. Show the command and its output as evidence.
- Fix root causes; never suppress an error to make a check pass.
- For a bug, write a failing test that reproduces it first, then fix.

## Match the codebase
- Read neighboring code first; follow its patterns, naming, and structure.
- Reuse what's there — don't add a dependency or invent a pattern when one
  exists. Smallest change that works; no speculative abstraction.
- Touch only what the task needs; note adjacent issues in the journal, don't fix
  them silently.

## Repo etiquette
- Follow the project's branch/PR/commit conventions. Don't commit or push unless
  asked. Never commit secrets or rewrite shared history.

## Be honest
- Report faithfully: failing tests, skipped steps, and unverified claims get said
  out loud. Confirm before irreversible or outward-facing actions.

## Security
- Never hardcode credentials; reference where secrets live, never the values.
  Validate external input; flag anything touching auth, crypto, or user data.

## Context discipline (this makes devrules work)
- You're picking up cold from another account — read the injected context fully
  before acting.
- Before finishing, append: what changed, current state, exact next steps, new
  gotchas — for a different account on a different machine.
- Record the project's build/test/lint/run commands the first time you learn
  them. Keep the context current; prune what's stale.
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def ensure_layout() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    if not RULES_FILE.exists():
        RULES_FILE.write_text(DEFAULT_RULES)


def sanitize_key(project: str) -> str:
    key = (project or "").strip()
    if "/" in key or "\\" in key or ".." in key or not KEY_RE.match(key):
        raise ValueError(f"invalid project key: {project!r}")
    return key


def _context_path(project: str) -> Path:
    return PROJECTS_DIR / sanitize_key(project) / CONTEXT_FILE


def read_rules() -> str:
    ensure_layout()
    return RULES_FILE.read_text()


def write_rules(content: str) -> None:
    ensure_layout()
    RULES_FILE.write_text(content.rstrip() + "\n")


def read_context(project: str) -> str:
    p = _context_path(project)
    return p.read_text() if p.exists() else ""


def write_context(project: str, content: str) -> None:
    p = _context_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.rstrip() + "\n")


def append_context(project: str, note: str) -> None:
    p = _context_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(f"\n## {_now()}\n\n{note.rstrip()}\n")


def payload(project: str) -> str:
    """Global rules + this project's context — the full 'catch me up' read."""
    key = sanitize_key(project)
    ctx = read_context(project).strip()
    body = ctx if ctx else "_No saved context for this project yet._"
    return (
        read_rules().rstrip()
        + f"\n\n---\n\n# devrules context for `{key}`\n\n"
        + body
        + "\n"
    )


def list_projects() -> list[dict]:
    ensure_layout()
    out = []
    for d in PROJECTS_DIR.iterdir():
        if not d.is_dir():
            continue
        f = d / CONTEXT_FILE
        if f.exists():
            st = f.stat()
            out.append(
                {
                    "project": d.name,
                    "updated": datetime.fromtimestamp(
                        st.st_mtime, timezone.utc
                    ).strftime("%Y-%m-%d %H:%M UTC"),
                    "bytes": st.st_size,
                }
            )
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out
