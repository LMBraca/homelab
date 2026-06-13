#!/bin/bash
# ============================================================
# build-watcher.sh
# Runs continuously on the HOST. Watches /opt/claude-ideas/builds/
# for *.job.json files dropped by the dashboard API, then fires
# run-build.sh for each one.
# ============================================================

BUILDS_DIR="/opt/claude-ideas/builds"
RUNNER="$(dirname "$(readlink -f "$0")")/run-build.sh"
# Read POLL_INTERVAL from /opt/claude-ideas/settings.json on each iteration so
# the dashboard /settings page can retune the watcher without a restart.
SETTINGS_FILE="${SETTINGS_FILE:-/opt/claude-ideas/settings.json}"
_read_poll() {
    python3 - "$SETTINGS_FILE" <<'PYEOF' 2>/dev/null || echo 5
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(int(json.load(f).get("generator", {}).get("watcher_poll_sec") or 5))
except Exception:
    print(5)
PYEOF
}

mkdir -p "$BUILDS_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "build-watcher started. Watching $BUILDS_DIR for *.job.json"
log "Runner: $RUNNER"

while true; do
    # ── Cancellation requests (dashboard POST /api/claude/build/<id>/cancel) ──
    # Process before job files so a cancel that arrives at the same tick as a
    # rebuild can't be undone by a new job for the same slug.
    for cancel_file in "$BUILDS_DIR"/*.cancel; do
        [[ -f "$cancel_file" ]] || continue

        CANCEL_BUILD_ID=$(basename "$cancel_file" .cancel)
        log "Cancel requested for build $CANCEL_BUILD_ID"

        # Read the slug from the status file BEFORE removing it so we can
        # clean up the project directory too.
        CANCEL_STATUS_JSON="$BUILDS_DIR/${CANCEL_BUILD_ID}.json"
        CANCEL_SLUG=""
        if [[ -f "$CANCEL_STATUS_JSON" ]]; then
            CANCEL_SLUG=$(python3 -c "import json; print(json.load(open('$CANCEL_STATUS_JSON')).get('project_slug',''))" 2>/dev/null || true)
        fi
        # Defence-in-depth: keep only [a-zA-Z0-9-], cap length
        CANCEL_SLUG="${CANCEL_SLUG//[^a-zA-Z0-9-]/}"
        CANCEL_SLUG="${CANCEL_SLUG:0:64}"

        # Stop the per-build systemd unit (kills the entire cgroup —
        # claude, npm run dev, tsx watch, node --watch, everything).
        # No-op if the unit doesn't exist (stuck status file with no process).
        systemctl --user stop "claude-build-${CANCEL_BUILD_ID}.service" 2>/dev/null || true

        # Remove all build artifacts so the slug can be rebuilt cleanly
        rm -f "$CANCEL_STATUS_JSON" \
              "$BUILDS_DIR/${CANCEL_BUILD_ID}.log" \
              "$BUILDS_DIR/${CANCEL_BUILD_ID}.prompt.txt" \
              "$BUILDS_DIR/${CANCEL_BUILD_ID}.zip" \
              "$BUILDS_DIR/${CANCEL_BUILD_ID}.job.json"

        # Remove the built project directory if we recovered a slug
        if [[ -n "$CANCEL_SLUG" ]]; then
            rm -rf "$HOME/claude-builds/$CANCEL_SLUG"
            log "Removed project dir $HOME/claude-builds/$CANCEL_SLUG"
        fi

        rm -f "$cancel_file"
        log "Cancelled and cleaned up build $CANCEL_BUILD_ID"
    done

    for job_file in "$BUILDS_DIR"/*.job.json; do
        [[ -f "$job_file" ]] || continue

        log "Found job file: $job_file"

        # Parse each field separately — avoids heredoc/read quoting issues
        BUILD_ID=$(python3  -c "import json; d=json.load(open('$job_file')); print(d['build_id'])")
        ACCOUNT=$(python3   -c "import json; d=json.load(open('$job_file')); print(d['account'])")
        MODEL=$(python3     -c "import json; d=json.load(open('$job_file')); print(d['model'])")
        SLUG=$(python3      -c "import json; d=json.load(open('$job_file')); print(d['slug'])")
        PROMPT_FILE=$(python3 -c "import json; d=json.load(open('$job_file')); print(d['prompt_file'])")

        if [[ -z "$BUILD_ID" ]]; then
            log "ERROR: could not parse job file $job_file — skipping"
            mv "$job_file" "${job_file}.bad"
            continue
        fi

        log "Picked up job: $BUILD_ID (slug=$SLUG account=$ACCOUNT model=$MODEL)"

        # Remove the job file immediately so we don't re-process it
        rm -f "$job_file"

        # Spawn the build inside its own transient systemd --user service so
        # the entire cgroup (Claude + anything it spawns via the Bash tool,
        # e.g. `npm run dev`, `tsx watch`, `node --watch`) is reaped when the
        # service stops. RuntimeMaxSec is a hard ceiling: if run-build.sh's
        # internal `timeout` somehow misses, systemd will still kill the unit.
        # systemd-run returns immediately — no `&` needed.
        BUILD_LOG="/opt/claude-ideas/builds/${BUILD_ID}.log"
        : > "$BUILD_LOG"
        chmod 0664 "$BUILD_LOG" 2>/dev/null || true

        systemd-run --user \
            --unit="claude-build-${BUILD_ID}" \
            --slice=claude-builds.slice \
            --quiet --collect \
            -p Type=exec \
            -p KillMode=control-group \
            -p TimeoutStopSec=30 \
            -p RuntimeMaxSec=1900 \
            -p "StandardOutput=append:${BUILD_LOG}" \
            -p "StandardError=append:${BUILD_LOG}" \
            bash "$RUNNER" "$BUILD_ID" "$ACCOUNT" "$MODEL" "$SLUG" "$PROMPT_FILE" \
            || log "ERROR: systemd-run failed for $BUILD_ID"

        log "Spawned build unit claude-build-${BUILD_ID}.service for $BUILD_ID"
    done

    sleep "$(_read_poll)"
done
