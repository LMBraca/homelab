#!/bin/bash
# ============================================================
# Claude Project Idea Generator
# Outputs structured JSONL to /opt/claude-ideas/project-ideas.jsonl
#
# Usage: ./claude-idea-generator.sh <account-number>
#   account-number: 1, 2, or 3
#
# Each account gets a rotated difficulty tier so ideas vary:
#   Account 1 → beginner-friendly / junior portfolio pieces
#   Account 2 → intermediate / mid-level full-stack projects
#   Account 3 → advanced / senior-level or startup-scale projects
# The tier also rotates by hour-of-day so the 4hr cadence cycles through all levels.
# ============================================================

set -euo pipefail

ACCOUNT="${1:-}"
OUTPUT_DIR="/opt/claude-ideas"
OUTPUT_FILE="$OUTPUT_DIR/project-ideas.jsonl"
LOG_FILE="$OUTPUT_DIR/generator.log"

if [[ -z "$ACCOUNT" || ! "$ACCOUNT" =~ ^[1-3]$ ]]; then
    echo "Usage: $0 <account-number> (1, 2, or 3)"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# Authenticate via the subscription OAuth flow in .credentials.json (the same
# path your interactive `claude` sessions use). This is what opens the 5-hour
# session window on api.claude.ai — long-lived `sk-ant-oat01-` tokens billed
# to the account go to a separate bucket that the /oauth/usage endpoint
# doesn't report, so they don't keep the timer warm.
export CLAUDE_CONFIG_DIR="$HOME/.claude-account-$ACCOUNT"
CREDS_PATH="$CLAUDE_CONFIG_DIR/.credentials.json"

if [[ ! -f "$CREDS_PATH" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Account $ACCOUNT - ERROR: $CREDS_PATH missing. Run: CLAUDE_CONFIG_DIR=$CLAUDE_CONFIG_DIR claude /login" >> "$LOG_FILE"
    exit 1
fi

# Strip any auth-overriding env vars so we deterministically use the
# subscription creds. CLAUDE_CODE_OAUTH_TOKEN in particular would route
# through the API/Console billing path and skip the 5h window.
unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN \
      CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX CLAUDE_CODE_USE_FOUNDRY

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Account $ACCOUNT - Starting idea generation..." >> "$LOG_FILE"

# ── Difficulty rotation ─────────────────────────────────────────────────
# Rotate difficulty + domain focus based on account + current hour bucket
HOUR=$(date +%H)
HOUR_BUCKET=$(( (10#$HOUR / 4) % 3 ))   # 0, 1, or 2 every 4 hours
SLOT=$(( ($ACCOUNT + $HOUR_BUCKET) % 3 ))

case $SLOT in
  0) DIFFICULTY="beginner-friendly"
     DIFFICULTY_DETAIL="Targeted at a junior developer fresh out of college. The project should be completable solo in 2-4 weeks, use widely-known technologies, and be polished enough to anchor a portfolio."
     ;;
  1) DIFFICULTY="intermediate"
     DIFFICULTY_DETAIL="Targeted at a mid-level developer (1-3 years). The project should involve integrations, real auth flows, background jobs, or multi-step workflows. Should take 4-8 weeks solo."
     ;;
  2) DIFFICULTY="advanced"
     DIFFICULTY_DETAIL="Targeted at a senior developer or ambitious side-project builder. The project should involve real-time features, distributed data, ML inference, or complex multi-user state. Should take 8-16 weeks but have a shippable MVP at 4 weeks."
     ;;
esac

# ── Domain bias rotation (prevents network/infra clustering) ────────────
DOMAIN_SLOT=$(( ($ACCOUNT * 2 + $HOUR_BUCKET + 1) % 6 ))
case $DOMAIN_SLOT in
  0) DOMAIN_HINT="Lean toward consumer productivity: personal finance, task management, scheduling, planning interfaces, or calendar tools." ;;
  1) DOMAIN_HINT="Lean toward document and content tools: rich-text editors, annotation systems, PDF workflows, report generators, or template builders." ;;
  2) DOMAIN_HINT="Lean toward social or collaborative tools: lightweight team tools, async communication, feedback systems, review/approval workflows." ;;
  3) DOMAIN_HINT="Lean toward map/location/spatial tools: local discovery, route planning, geography-based dashboards, geofencing, or map-based analytics." ;;
  4) DOMAIN_HINT="Lean toward media and creative tools: image organizers, video clip tools, portfolio builders, design-to-code utilities, or asset management." ;;
  5) DOMAIN_HINT="Lean toward local business and service tools: booking/appointment systems, customer portals, invoice generators, or small business ops dashboards." ;;
esac

# ── Build full exclusion list ───────────────────────────────────────────
# The generator must not repeat anything that is:
#   (1) currently sitting in the dashboard (project-ideas.jsonl) — even if
#       the user hasn't deleted or built it yet, recommending it again is just
#       noise.
#   (2) already built (~/claude-builds/<slug>/) — these slugs survive deletion
#       only via the graveyard, but live builds also need to be excluded.
#   (3) deleted/rejected (graveyard.jsonl).
# All three sources are merged + de-duped before being injected into the prompt.
EXCLUSION_LIST=$(python3 - <<'PYEOF'
import json, os, re

def slug(s):
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9-]+', '-', (s or '').lower())).strip('-')

seen_slugs = set()
items = []  # ordered: live ideas first, then built, then graveyard
sources = [
    ("/opt/claude-ideas/project-ideas.jsonl", "live"),
    ("/opt/claude-ideas/graveyard.jsonl",     "graveyard"),
]
for path, _kind in sources:
    if not os.path.exists(path):
        continue
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                name = (d.get("name") or "").strip()
                tagline = (d.get("tagline") or "").strip()
                if not name:
                    continue
                key = slug(name)
                if key in seen_slugs:
                    continue
                seen_slugs.add(key)
                items.append(f"- {name}" + (f": {tagline}" if tagline else ""))
    except Exception:
        pass

# Built project directory names (these are slugs derived from the original
# idea name — recover a display form by title-casing the words).
builds_dir = "/home/luis/claude-builds"
try:
    if os.path.isdir(builds_dir):
        for entry in sorted(os.listdir(builds_dir)):
            full = os.path.join(builds_dir, entry)
            if not os.path.isdir(full):
                continue
            key = slug(entry)
            if key in seen_slugs:
                continue
            seen_slugs.add(key)
            items.append(f"- {entry.replace('-', ' ').title()} (already built)")
except Exception:
    pass

# Cap so the prompt stays bounded; keep the most recent 120 entries (which
# in JSONL means the END of the list — graveyard/live both append).
print("\n".join(items[-120:]))
PYEOF
)

EXCLUSION_SECTION=""
if [[ -n "$EXCLUSION_LIST" ]]; then
    EXCLUSION_SECTION="
PREVIOUSLY GENERATED, BUILT, OR REJECTED IDEAS — DO NOT REPEAT OR ECHO ANY OF THESE:
The list below covers ideas already shown to the user (whether deleted, built, or still pending review). Do not produce any idea that is the same as, substantially similar to, a thin variation of, or covers the same core problem space as any of these. If your candidate idea overlaps in name, target user, problem statement, or core feature with anything below, pick a different idea entirely.
$EXCLUSION_LIST
"
fi

# ── Portfolio context (lmbraca on GitHub) ───────────────────────────────
# Fetch the user's public repos so the model can target *gaps* in their
# portfolio — what's already shipped vs. what types of projects are missing.
# Cached for 24h to stay well under GitHub's unauth rate limit (60/hr) since
# this script runs every ~4h across 3 accounts.
GH_CACHE="$OUTPUT_DIR/github-portfolio.txt"
GH_RAW_CACHE="$OUTPUT_DIR/github-portfolio.json"
# Read settings.json (with defaults) so the dashboard /settings page actually
# controls behavior here. Failure to read = stick with hardcoded defaults.
SETTINGS_FILE="${SETTINGS_FILE:-/opt/claude-ideas/settings.json}"
_read_setting() {
    # _read_setting <section> <key> <default>
    python3 - "$SETTINGS_FILE" "$1" "$2" "$3" <<'PYEOF' 2>/dev/null || echo "$3"
import json, sys
path, section, key, default = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
try:
    with open(path) as f:
        d = json.load(f)
    v = d.get(section, {}).get(key)
    print(v if v not in (None, "") else default)
except Exception:
    print(default)
PYEOF
}
GH_USER="$(_read_setting generator github_user lmbraca)"
GH_TTL=$(( $(_read_setting generator github_cache_hours 24) * 3600 ))
GH_TIMEOUT="$(_read_setting generator github_fetch_timeout_sec 10)"

_gh_cache_stale=true
if [[ -f "$GH_CACHE" ]]; then
    age=$(( $(date +%s) - $(stat -c %Y "$GH_CACHE" 2>/dev/null || echo 0) ))
    if (( age < GH_TTL )); then
        _gh_cache_stale=false
    fi
fi

if $_gh_cache_stale; then
    # Tunable wall clock (generator.github_fetch_timeout_sec). If GitHub is
    # slow or rate-limiting us, don't block idea generation. Failure is
    # non-fatal; we just fall back to the last cached file (or skip entirely).
    if curl -fsS --connect-timeout 5 --max-time "$GH_TIMEOUT" \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/users/$GH_USER/repos?per_page=100&sort=updated" \
        -o "$GH_RAW_CACHE.tmp" 2>>"$LOG_FILE"; then
        mv "$GH_RAW_CACHE.tmp" "$GH_RAW_CACHE"
        python3 - "$GH_RAW_CACHE" "$GH_CACHE" 2>>"$LOG_FILE" <<'PYEOF' || true
import json, sys
src, dst = sys.argv[1], sys.argv[2]
try:
    with open(src) as f:
        repos = json.load(f)
except Exception as e:
    print(f"gh cache parse error: {e}", file=sys.stderr)
    sys.exit(1)
if not isinstance(repos, list):
    print("gh cache: unexpected shape (rate limited?)", file=sys.stderr)
    sys.exit(1)
lines = []
for r in repos:
    if r.get("fork") or r.get("archived"):
        continue
    name = r.get("name", "")
    desc = (r.get("description") or "").strip()
    lang = r.get("language") or ""
    topics = r.get("topics") or []
    bits = [name]
    if lang:    bits.append(f"[{lang}]")
    if desc:    bits.append(f"— {desc}")
    if topics:  bits.append(f"({', '.join(topics[:4])})")
    lines.append("- " + " ".join(bits))
with open(dst, "w") as f:
    f.write("\n".join(lines[:60]))
PYEOF
        rm -f "$GH_RAW_CACHE.tmp"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] gh portfolio fetch failed — using stale cache if present" >> "$LOG_FILE"
    fi
fi

PORTFOLIO_SECTION=""
if [[ -s "$GH_CACHE" ]]; then
    PORTFOLIO_BODY=$(cat "$GH_CACHE")
    PORTFOLIO_SECTION="
EXISTING PORTFOLIO (github.com/$GH_USER) — TARGET THE GAPS:
The list below is everything this developer has already shipped publicly. Treat this as the inventory of their existing portfolio. Your job is to recommend a project that FILLS A GAP, not one that duplicates what is already here. Specifically:
- If their portfolio is light on a category (e.g. no real-time/collaborative work, no spatial/geographic tools, no client-side ML, no signal-processing, no algorithmic visualizers), prefer a project in that gap.
- If their portfolio is heavy on a category (e.g. lots of dashboards or CRUD apps), AVOID adding another one.
- The new project should pair well with the existing portfolio to tell a coherent story to a recruiter: \"this person has range across <X, Y, Z> and now adds depth in <new category>.\"
- Do NOT propose a project whose core problem or tech direction is already represented below.
$PORTFOLIO_BODY
"
fi

# Build prompt via heredoc — double quotes are literal (no escaping needed),
# and variables ($DIFFICULTY, $GRAVEYARD_SECTION, etc.) are still expanded.
PROMPT=$(cat <<PROMPTEOF
You are a senior software engineer, startup founder, technical recruiter, and product researcher.
Your task is to generate exactly ONE strong software project idea for a recent computer science bachelor graduate who wants to stand out in job applications.

DIFFICULTY LEVEL: $DIFFICULTY
$DIFFICULTY_DETAIL

DOMAIN FOCUS: $DOMAIN_HINT
$EXCLUSION_SECTION
$PORTFOLIO_SECTION

First, think about real user pain points people complain about in everyday software: scheduling friction, file chaos, email overload, personal finance confusion, travel planning headaches, task coordination, note-taking, document handling, local business workflows, communication friction, repetitive digital tasks, information overload, and search/discovery problems.

IMPORTANT PROJECT DIRECTION:
- I do NOT want generic clone apps (no Uber, Spotify, Netflix, Twitter clones)
- I do NOT want DevOps, CI/CD, infrastructure automation, or invisible internal tooling
- I do NOT want SaaS-style subscription platforms, multi-tenant admin dashboards, or anything that reads like "Stripe for X" or "Notion for Y" — these look like undifferentiated clones to recruiters
- I do NOT want projects whose main selling point is the business model (usage tiers, billing, teams) rather than the actual UI and interaction
- I do NOT want "nothing-burger" projects — apps where 95% of the work is auth + CRUD + a polished frontend, and the only "engineering" is wiring forms to a database. Examples to AVOID: yet-another habit tracker, yet-another meal planner, yet-another reading-list app, yet-another mood journal, yet-another itinerary builder, yet-another markdown notes app, yet-another expense tracker. If the title pattern is "X tracker", "X planner", "X organizer", or "X dashboard" with no algorithmic, computational, or systems substance underneath, REJECT IT and pick something else.
- I want something visual, interactive, portfolio-friendly, and easy to demo live to a recruiter — AND with real technical substance under the hood that a senior engineer would respect.
- The project must have a strong UI where the interface IS the demo, but the engineering depth IS the differentiator. A recruiter should be impressed by what they see on screen; an interviewer should be impressed by what they hear when you explain how it works.

TECHNICAL SUBSTANCE — REQUIRED:
The project MUST involve at least one (preferably two) of the following non-trivial engineering concerns. "Wired up a third-party API" does not count.
- A real algorithm beyond CRUD: graph traversal, constraint solving, optimization, scheduling, search/ranking, recommendation, parsing, diffing, layout, routing, packing, simulation.
- Real-time or streaming behavior: WebSockets/WebRTC, server-sent events, CRDTs/OT for collaborative editing, live cursors, low-latency sync.
- Client-side computation that is not trivial: WebGL/WebGPU rendering, Canvas2D animation, audio/DSP, video frame processing, on-device ML inference (TF.js / ONNX / Transformers.js), physics, geometry, image processing.
- Custom data structures or storage tricks: spatial indices, tries, bloom filters, vector embeddings + ANN search, time-series storage, append-only logs, MVCC, custom file formats.
- Performance-sensitive work: handling 100k+ items smoothly, virtualized rendering, worker threads, WASM, incremental computation, memoization at scale.
- Distributed or local-first systems: offline-first with sync conflict resolution, peer-to-peer, multi-device state, eventual consistency.
- ML/AI as a first-class building block, not an "add a chatbot" sprinkle: semantic search, custom embeddings, RAG over a non-trivial corpus, vision/audio models doing actual work in the interaction loop.

STRONG BIAS TOWARD THESE TYPES OF PROJECTS:
- Interactive editors/canvases where the engineering challenge is rendering, layout, or collaborative editing (e.g. a node-graph editor, a constraint-based layout tool, a collaborative whiteboard with CRDTs).
- Map/geospatial/3D tools with real spatial algorithms (routing, isochrones, viewshed analysis, packing, terrain visualization, geofencing with hysteresis).
- Time-based or signal-based tools: a DAW-lite, a video annotator with frame-precise scrubbing, a music-theory analyzer, a waveform editor, a beat-detection toy.
- Search/explore experiences over a non-trivial corpus with real ranking or embedding-based retrieval — not just SQL LIKE %x%.
- Game-like simulations with a real model underneath (ecosystem sims, fluid sims, traffic sims, cellular automata explorers, evolution sandboxes).
- Developer tools with computational substance: a regex visualizer with NFA/DFA construction, a SQL EXPLAIN visualizer, a diff viewer with semantic chunking, a code-graph navigator, a pretty-printer/formatter for an obscure format.
- Domain-specific structured editors where the data model itself is interesting (a chess opening-tree explorer, a music theory practice tool, a knitting pattern designer, a circuit playground).

RULES:
- Must solve a specific, concrete problem — not a broad market category.
- Must be realistic for one person to build at the given difficulty level (smaller scope at beginner, bigger at advanced — but technical substance is REQUIRED at all levels; beginner just means smaller surface area, not less engineering).
- Must be visually demonstrable in a portfolio or interview — 30-second demo, real wow factor on screen.
- The "wow" must come from BOTH what the interface does AND what is interesting under the hood. State both clearly.
- Auth, CRUD, payments, and multi-tenancy should be incidental at most — never the headline.
- Before finalizing, ask yourself two questions: (1) "Could a bootcamp grad ship this in a weekend by gluing 3 APIs together?" If yes, REJECT — pick something with real engineering substance. (2) "Does this exist as a free product already, made by a well-known company?" If yes, REJECT — pick something more opinionated or technically novel.

Return ONLY valid JSON — no markdown, no explanation, no code blocks. Just the raw JSON object:

{
  "name": "Project Name",
  "tagline": "One sentence description",
  "difficulty": "$DIFFICULTY",
  "problem": "The real-world problem it solves (2-3 sentences)",
  "target_users": "Who would use this",
  "resume_value": "Why it stands out for a recent CS grad (2-3 sentences)",
  "why_this_was_chosen": "Why this idea is stronger than generic alternatives (1-2 sentences)",
  "visual_hook": "What makes this visually compelling in a portfolio demo (1 sentence)",
  "technical_depth": "The non-trivial engineering substance — name the specific algorithm, data structure, real-time mechanism, or computational technique that makes this more than CRUD (2-3 sentences, concrete enough that a senior engineer would nod)",
  "mvp_features": ["feature 1", "feature 2", "feature 3", "feature 4"],
  "advanced_features": ["advanced 1", "advanced 2", "advanced 3"],
  "tech_stack": {
    "frontend": "...",
    "backend": "...",
    "database": "...",
    "infrastructure": "..."
  },
  "technical_challenges": ["challenge 1", "challenge 2", "challenge 3"],
  "build_prompt": "A detailed, actionable prompt that could be given directly to an AI coding assistant (like Claude Code) to scaffold and build this project. Include: project structure, key files to create, what the MVP should implement first, and what commands to run to get it running locally. Be specific about file names, routes, and data models.",
  "production_ready_checklist": ["item 1", "item 2", "item 3"],
  "tags": ["tag1", "tag2", "tag3"]
}
PROMPTEOF
)

# Hold an exclusive flock on .credentials.json across the whole `claude`
# invocation. fetch-claude-limits.sh and keepalive-claude-tokens.sh both
# acquire the same POSIX lock on the same file, so the three writers
# serialize cleanly and refresh-token rotations can't race (which is what
# bricked accounts 2 and 3 after the 2026-04-21 outage).
exec 200<"$CREDS_PATH"
flock -x 200
GEN_MODEL="$(_read_setting generator model haiku)"
RESPONSE=$(claude -p "$PROMPT" --model "$GEN_MODEL" --no-session-persistence 2>>"$LOG_FILE")
CLAUDE_EXIT=$?
flock -u 200
exec 200<&-

if [[ $CLAUDE_EXIT -ne 0 ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Account $ACCOUNT - ERROR: Claude command failed (exit $CLAUDE_EXIT)" >> "$LOG_FILE"
    exit 1
fi

# Strip markdown code fences if Claude wrapped it anyway
CLEAN=$(echo "$RESPONSE" | sed 's/^```json//;s/^```//;s/```$//' | tr -d '\r')

# Validate it's JSON, then wrap with metadata and append as a single JSONL line.
# Pass data via env vars + quoted heredoc so special chars in CLEAN can't break
# the Python source, and route stderr to the log so parse errors aren't silent.
PY_EXIT=0
_CLEAN="$CLEAN" _DIFFICULTY="$DIFFICULTY" _ACCOUNT="$ACCOUNT" _OUTPUT="$OUTPUT_FILE" \
python3 2>>"$LOG_FILE" <<'PYEOF' || PY_EXIT=$?
import json, sys, os, re
from datetime import datetime

raw = os.environ["_CLEAN"]
try:
    idea = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"JSON parse error: {e}", file=sys.stderr)
    sys.exit(1)

# Ensure required fields exist
idea.setdefault("difficulty", os.environ["_DIFFICULTY"])
idea.setdefault("build_prompt", "")

def slug(s):
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9-]+', '-', (s or '').lower())).strip('-')

# Post-generation dedup: the in-prompt exclusion list is best-effort — the
# model still ships near-dupes. Reject before append if the slug collides
# with anything already in the pool, graveyard, or built dirs.
new_slug = slug(idea.get("name", ""))
if not new_slug:
    print("idea missing name — skipping", file=sys.stderr)
    sys.exit(1)

existing_slugs = set()
for path in (os.environ["_OUTPUT"], "/opt/claude-ideas/graveyard.jsonl"):
    if not os.path.exists(path):
        continue
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                s = slug(r.get("name", ""))
                if s:
                    existing_slugs.add(s)
    except Exception:
        pass
builds_dir = "/home/luis/claude-builds"
if os.path.isdir(builds_dir):
    try:
        for entry in os.listdir(builds_dir):
            if os.path.isdir(os.path.join(builds_dir, entry)):
                existing_slugs.add(slug(entry))
    except Exception:
        pass

if new_slug in existing_slugs:
    print(f"duplicate idea slug={new_slug} name={idea.get('name','?')!r} — not appending", file=sys.stderr)
    sys.exit(2)

record = {
    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "account": os.environ["_ACCOUNT"],
    **idea
}

with open(os.environ["_OUTPUT"], "a") as f:
    f.write(json.dumps(record) + "\n")

print("OK")
PYEOF

if [[ $PY_EXIT -eq 2 ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Account $ACCOUNT - SKIP: model returned a duplicate (see stderr above)" >> "$LOG_FILE"
    exit 0
elif [[ $PY_EXIT -ne 0 ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Account $ACCOUNT - ERROR: idea write failed (exit $PY_EXIT)" >> "$LOG_FILE"
    exit $PY_EXIT
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Account $ACCOUNT - Done. Appended to $OUTPUT_FILE" >> "$LOG_FILE"
