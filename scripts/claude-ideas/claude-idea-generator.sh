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

export CLAUDE_CONFIG_DIR="$HOME/.claude-account-$ACCOUNT"
mkdir -p "$OUTPUT_DIR"

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

# ── Build graveyard exclusion list ──────────────────────────────────────
GRAVEYARD_FILE="/opt/claude-ideas/graveyard.jsonl"
GRAVEYARD_LIST=""
if [[ -f "$GRAVEYARD_FILE" ]]; then
    GRAVEYARD_LIST=$(python3 - <<'PYEOF'
import json, sys
items = []
try:
    with open("/opt/claude-ideas/graveyard.jsonl") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            name = d.get("name","").strip()
            tagline = d.get("tagline","").strip()
            if name:
                items.append(f"- {name}" + (f": {tagline}" if tagline else ""))
except Exception as e:
    pass
print("\n".join(items[-80:]))  # cap at 80 entries
PYEOF
)
fi

GRAVEYARD_SECTION=""
if [[ -n "$GRAVEYARD_LIST" ]]; then
    GRAVEYARD_SECTION="
PREVIOUSLY REJECTED OR BUILT IDEAS — DO NOT REPEAT THESE:
The following ideas have already been generated, built, or discarded. Do not produce any idea that is the same as or substantially similar to any of these:
$GRAVEYARD_LIST
"
fi

PROMPT="You are a senior software engineer, startup founder, technical recruiter, and product researcher.
Your task is to generate exactly ONE strong software project idea for a recent computer science bachelor's graduate who wants to stand out in job applications.

DIFFICULTY LEVEL: $DIFFICULTY
$DIFFICULTY_DETAIL

DOMAIN FOCUS: $DOMAIN_HINT
$GRAVEYARD_SECTION

First, think about real user pain points people complain about in everyday software: scheduling friction, file chaos, email overload, personal finance confusion, travel planning headaches, task coordination, note-taking, document handling, local business workflows, communication friction, repetitive digital tasks, information overload, and search/discovery problems.

IMPORTANT PROJECT DIRECTION:
- I do NOT want generic clone apps (no Uber, Spotify, Netflix, Twitter clones)
- I do NOT want boring backend-only projects or pure pipelines
- I do NOT want DevOps, CI/CD, infrastructure automation, or invisible internal tooling
- I do NOT want SaaS-style subscription platforms, multi-tenant admin dashboards, or anything that reads like "Stripe for X" or "Notion for Y" — these look like undifferentiated clones to recruiters
- I do NOT want projects whose main selling point is the business model (usage tiers, billing, teams) rather than the actual UI and interaction
- I want something visual, interactive, portfolio-friendly, and easy to demo live to a recruiter
- The project must have a strong UI where the interface IS the product — a recruiter should be impressed by what they see on screen, not by the architecture description
- Prefer tools that solve a specific, concrete, personal or professional problem in a creative way — not a generic platform that could serve "any business"
- The wow factor must come from what the app does and shows, not from its market positioning

STRONG BIAS TOWARD THESE TYPES OF PROJECTS:
- Visual document tools (editors, annotators, template builders)
- Map-based or spatial tools with real interactivity
- Personal scheduling, planning, and calendar interfaces with clever UX
- Workflow tools for a specific niche (musicians, designers, researchers, athletes, writers)
- Data visualization dashboards tied to a specific, interesting dataset or personal data source
- Annotation, review, and comparison interfaces
- Timeline and history-based interfaces
- Drag-and-drop builders for a specific artifact (itineraries, meal plans, workout programs, reading lists)
- Rich search/filter/explore experiences over an interesting domain
- Tools with charts, maps, boards, or interactive canvases that feel native to the problem

RULES:
- Must solve a specific, concrete problem — not a broad market category
- Must be realistic for one person to build (at the given difficulty level)
- Must be visually demonstrable in a portfolio or interview — if you can't show something impressive on screen in 30 seconds, it fails
- Must feel opinionated and specific, not like a generic platform waiting to be filled in
- The core value must come from the UI and interaction design, not from the business model or multi-tenancy
- Auth and data modeling should serve the product — not BE the product (avoid ideas where "auth + CRUD + billing" is most of the work)
- Ask yourself: would a recruiter lean forward when they see this demoed, or would they think "oh, another task manager"?

Return ONLY valid JSON — no markdown, no explanation, no code blocks. Just the raw JSON object:

{
  \"name\": \"Project Name\",
  \"tagline\": \"One sentence description\",
  \"difficulty\": \"$DIFFICULTY\",
  \"problem\": \"The real-world problem it solves (2-3 sentences)\",
  \"target_users\": \"Who would use this\",
  \"resume_value\": \"Why it stands out for a recent CS grad (2-3 sentences)\",
  \"why_this_was_chosen\": \"Why this idea is stronger than generic alternatives (1-2 sentences)\",
  \"visual_hook\": \"What makes this visually compelling in a portfolio demo (1 sentence)\",
  \"mvp_features\": [\"feature 1\", \"feature 2\", \"feature 3\", \"feature 4\"],
  \"advanced_features\": [\"advanced 1\", \"advanced 2\", \"advanced 3\"],
  \"tech_stack\": {
    \"frontend\": \"...\",
    \"backend\": \"...\",
    \"database\": \"...\",
    \"infrastructure\": \"...\"
  },
  \"technical_challenges\": [\"challenge 1\", \"challenge 2\", \"challenge 3\"],
  \"build_prompt\": \"A detailed, actionable prompt that could be given directly to an AI coding assistant (like Claude Code) to scaffold and build this project. Include: project structure, key files to create, what the MVP should implement first, and what commands to run to get it running locally. Be specific about file names, routes, and data models.\",
  \"production_ready_checklist\": [\"item 1\", \"item 2\", \"item 3\"],
  \"tags\": [\"tag1\", \"tag2\", \"tag3\"]
}"

RESPONSE=$(claude -p "$PROMPT" --model haiku --no-session-persistence 2>>"$LOG_FILE") || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Account $ACCOUNT - ERROR: Claude command failed" >> "$LOG_FILE"
    exit 1
}

# Strip markdown code fences if Claude wrapped it anyway
CLEAN=$(echo "$RESPONSE" | sed 's/^```json//;s/^```//;s/```$//' | tr -d '\r')

# Validate it's JSON, then wrap with metadata and append as a single JSONL line
python3 - <<PYEOF
import json, sys
from datetime import datetime

raw = """$CLEAN"""
try:
    idea = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"JSON parse error: {e}", file=sys.stderr)
    sys.exit(1)

# Ensure required fields exist
idea.setdefault("difficulty", "$DIFFICULTY")
idea.setdefault("build_prompt", "")

record = {
    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "account": "$ACCOUNT",
    **idea
}

with open("$OUTPUT_FILE", "a") as f:
    f.write(json.dumps(record) + "\n")

print("OK")
PYEOF

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Account $ACCOUNT - Done. Appended to $OUTPUT_FILE" >> "$LOG_FILE"
