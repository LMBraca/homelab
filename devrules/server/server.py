"""devrules — shared project-context server for the homelab.

One small ASGI process serving three surfaces on one port:
  * /mcp           MCP tools Claude calls to read/append/replace context
  * /context, ...  plain REST used by the SessionStart/Stop hooks
  * /              a view-only web file-explorer for the context store
"""

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse

import store

STATIC = Path(__file__).parent / "static"

INSTRUCTIONS = """\
devrules is this user's shared project-context store. Every Claude account and
machine talks to the same store, so work survives account switches and moving
between computers. Nothing is written into the user's repos.

A SessionStart hook injects this project's saved context and tells you the
**devrules project key** (look for "Your devrules project key is `...`"). Use
exactly that key for every tool call here.

- `context_read(project)` — global rules + this project's full context. The hook
  already injects this at session start; call it again if you need a refresh.
- `context_append(project, note)` — add a timestamped note. Before you finish,
  record what changed, the current state, and the exact next steps, written for a
  different account picking up cold.
- `context_write(project, content)` — replace the whole context document. Use
  when reorganizing; prefer append for incremental updates.

Follow the global rules returned by context_read.
"""

mcp = FastMCP(
    "devrules",
    instructions=INSTRUCTIONS,
    host="0.0.0.0",
    port=int(os.environ.get("DEVRULES_PORT", "8799")),
)

store.ensure_layout()


# ── MCP tools (3) ────────────────────────────────────────────────────────────

@mcp.tool()
def context_read(project: str) -> str:
    """Read the global rules plus this project's full saved context."""
    return store.payload(project)


@mcp.tool()
def context_append(project: str, note: str) -> str:
    """Append a timestamped note to this project's context. Use this to record
    progress, decisions, and next steps before finishing."""
    store.append_context(project, note)
    return f"Saved a note to '{project}'."


@mcp.tool()
def context_write(project: str, content: str) -> str:
    """Replace this project's entire context document. Prefer context_append for
    incremental updates; use this only when reorganizing the whole document."""
    store.write_context(project, content)
    return f"Replaced context for '{project}'."


# ── REST for the hooks ───────────────────────────────────────────────────────

@mcp.custom_route("/context", methods=["GET"])
async def context_route(request: Request):
    project = (request.query_params.get("project") or "").strip()
    if not project:
        return PlainTextResponse("missing 'project'", status_code=400)
    try:
        return PlainTextResponse(store.payload(project))
    except ValueError as exc:
        return PlainTextResponse(str(exc), status_code=400)


@mcp.custom_route("/health", methods=["GET"])
async def health_route(request: Request):
    return JSONResponse({"ok": True, "service": "devrules"})


# ── REST for the web UI (view-only) ──────────────────────────────────────────

@mcp.custom_route("/", methods=["GET"])
async def index_route(request: Request):
    return HTMLResponse((STATIC / "index.html").read_text())


@mcp.custom_route("/api/projects", methods=["GET"])
async def api_projects(request: Request):
    return JSONResponse(store.list_projects())


@mcp.custom_route("/api/rules", methods=["GET"])
async def api_rules(request: Request):
    return PlainTextResponse(store.read_rules())


@mcp.custom_route("/api/project", methods=["GET"])
async def api_project(request: Request):
    key = (request.query_params.get("key") or "").strip()
    try:
        return JSONResponse({"project": store.sanitize_key(key), "context": store.read_context(key)})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
