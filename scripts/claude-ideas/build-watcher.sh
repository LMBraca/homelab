#!/bin/bash
# ============================================================
# build-watcher.sh
# Runs continuously on the HOST. Watches /opt/claude-ideas/builds/
# for *.job.json files dropped by the dashboard API, then fires
# run-build.sh for each one.
# ============================================================

BUILDS_DIR="/opt/claude-ideas/builds"
RUNNER="$(dirname "$(readlink -f "$0")")/run-build.sh"
POLL_INTERVAL=5

mkdir -p "$BUILDS_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a /opt/claude-ideas/build-watcher.log; }

log "build-watcher started. Watching $BUILDS_DIR for *.job.json"
log "Runner: $RUNNER"

while true; do
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

        # Spawn the build in background so watcher keeps running
        bash "$RUNNER" "$BUILD_ID" "$ACCOUNT" "$MODEL" "$SLUG" "$PROMPT_FILE" \
            >> /opt/claude-ideas/builds/${BUILD_ID}.log 2>&1 &

        log "Spawned build PID=$! for $BUILD_ID"
    done

    sleep "$POLL_INTERVAL"
done
