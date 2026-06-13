# devrules

A shared **project-context server** for the homelab. Every Claude account and
machine reads/writes the same per-project context, so switching accounts when a
limit runs out — or moving between your Mac and desktop — never loses context.
**Nothing is stored in your repos** (not committed, not gitignored) — it all
lives on the homelab.

Part of the homelab stack: deploys via `../push-to-server.sh`, runs as its own
container on `:8799`, stores data at `/opt/devrules`.

## How it works

```
Any Claude account / machine                Homelab :8799 (one ASGI process)
┌──────────────────────────┐                ┌──────────────────────────────┐
│ SessionStart hook ────────┼─ GET /context ─▶  REST (for the hooks)        │
│   forces the READ         │                │                              │
│ Stop hook ────────────────┼─ blocks until ─▶  MCP /mcp  (read/append/     │
│   forces the WRITE        │   Claude saves │     write tools for Claude)  │
│ Claude (MCP client) ──────┼─ append/write ─▶                              │
│ Browser ──────────────────┼─ GET / ────────▶  view-only web explorer      │
└──────────────────────────┘                │                              │
                                            │  /opt/devrules/              │
                                            │    rules.md                  │
                                            │    projects/<key>/context.md │
                                            └──────────────────────────────┘
```

- **Project key** = a slug of the git remote (stable across machines), or the
  folder name if there's no remote. Computed by the hooks; same repo → same key →
  same context everywhere.
- **Read is forced** by the SessionStart hook — it injects the saved context the
  instant a session opens. No prompting, no cooperation needed.
- **Write is forced** by the Stop hook — if a session did real work and didn't
  save, it blocks once and makes Claude append a handoff note before stopping.
- **Storage is one `context.md` per project** — Claude reads it whole and appends
  to it. Plus a global `rules.md` prepended to every read.

## MCP tools

| Tool | Purpose |
|---|---|
| `context_read(project)` | Global rules + this project's full context |
| `context_append(project, note)` | Add a timestamped handoff note |
| `context_write(project, content)` | Replace the whole context document |

REST: `GET /context?project=<key>`, `GET /health`, `GET /` (UI),
`GET /api/projects`, `GET /api/project?key=<key>`, `GET /api/rules`.

## Deploy (from your Mac, like the rest of the homelab)

One-time — create the data dir (needs sudo, so do it interactively):

```bash
ssh luis@100.87.156.88 'sudo mkdir -p /opt/devrules && sudo chown -R "$(id -un):$(id -gn)" /opt/devrules'
```

Then, now and on every change:

```bash
cd ~/Documents/personal/homelab-server
./push-to-server.sh devrules
ssh luis@100.87.156.88 'cd /opt/homelab/devrules && docker compose up -d --build'
curl http://100.87.156.88:8799/health      # {"ok":true,"service":"devrules"}
```

Browse the store at <http://100.87.156.88:8799/>.

## Set up each device (run once per device)

```bash
cd ~/Documents/personal/homelab-server/devrules
./install/register-mcp.sh     # point Claude Code at the MCP (user scope)
./install/install-hooks.sh    # install the read + write hooks
```

Then open a fresh Claude Code session in any project — its context is injected at
the top, and finishing a session prompts a save. Do the same two installs on your
desktop and the same projects share context across both.

## Editing the rules

Global rules ("what to document, what to check") live in `/opt/devrules/rules.md`
on the server — edit that file and every account/machine picks it up next session.

## Local dev

```bash
cd server
pip install -r requirements.txt
DEVRULES_DATA=../_data DEVRULES_PORT=8799 python server.py
# UI at http://localhost:8799/ ; curl 'http://localhost:8799/context?project=test'
```
