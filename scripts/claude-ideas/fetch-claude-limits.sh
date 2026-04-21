#!/bin/bash
# ============================================================
# Fetches session + weekly usage limits from api.claude.ai
# for each Claude account and writes to:
#   /opt/claude-ideas/limits.json
#
# Run from host (not Docker) — requires internet access.
# Add to crontab to run every 5 minutes:
#   */5 * * * * /opt/homelab/scripts/claude-ideas/fetch-claude-limits.sh
# ============================================================

OUTPUT="/opt/claude-ideas/limits.json"
mkdir -p /opt/claude-ideas

result="{}"

for ACCT in 1 2 3; do
    CONFIG_DIR="$HOME/.claude-account-$ACCT"
    CREDS="$CONFIG_DIR/.credentials.json"
    CLAUDE_JSON="$CONFIG_DIR/.claude.json"

    if [[ ! -f "$CREDS" ]]; then
        result=$(echo "$result" | python3 -c "
import sys, json
d = json.load(sys.stdin)
d['$ACCT'] = {'error': 'no credentials'}
print(json.dumps(d))")
        continue
    fi

    TOKEN=$(python3 -c "
import json
with open('$CREDS') as f:
    d = json.load(f)
print(d.get('claudeAiOauth', {}).get('accessToken', ''))
" 2>/dev/null)

    if [[ -z "$TOKEN" ]]; then
        result=$(echo "$result" | python3 -c "
import sys, json
d = json.load(sys.stdin)
d['$ACCT'] = {'error': 'no token'}
print(json.dumps(d))")
        continue
    fi

    RESPONSE=$(curl -s --max-time 8 \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -H "User-Agent: claude-code" \
        -H "anthropic-beta: oauth-2025-04-20" \
        "https://api.anthropic.com/api/oauth/usage" 2>/dev/null)

    if [[ -z "$RESPONSE" ]]; then
        result=$(echo "$result" | python3 -c "
import sys, json
d = json.load(sys.stdin)
d['$ACCT'] = {'error': 'empty response'}
print(json.dumps(d))")
        continue
    fi

    result=$(echo "$result" | python3 -c "
import sys, json
d = json.load(sys.stdin)
try:
    payload = json.loads('''$RESPONSE''')
    d['$ACCT'] = {'data': payload, 'fetched_at': __import__('datetime').datetime.now().isoformat()}
except Exception as e:
    d['$ACCT'] = {'error': str(e), 'raw': '''$RESPONSE'''[:300]}
print(json.dumps(d))")

done

echo "$result" > "$OUTPUT"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Limits written to $OUTPUT"
