# Claude Project Idea Generator

Automated cron job that runs Claude Code (Haiku) every 4 hours across 3 accounts to generate resume-worthy project ideas for CS graduates.

## Deployment Steps

### 1. Push files to server

```bash
cd ~/path-to/homelab-server
./push-to-server.sh
```

### 2. SSH into the server

```bash
ssh luis@100.87.156.88
```

### 3. Run the setup script (one time)

```bash
chmod +x /opt/homelab/scripts/claude-ideas/setup-claude-accounts.sh
chmod +x /opt/homelab/scripts/claude-ideas/claude-idea-generator.sh
/opt/homelab/scripts/claude-ideas/setup-claude-accounts.sh
```

This will:
- Install Claude Code if needed
- Create `/opt/claude-ideas/` output directory
- Create 3 separate config dirs (`~/.claude-account-1`, `-2`, `-3`)
- Walk you through `claude /login` for each account (opens browser via Tailscale) — populates `~/.claude-account-N/.credentials.json`, which is the single auth source for the generator, fetcher, and keepalive

> The `claude setup-token` step in `setup-claude-accounts.sh` is no longer required. Long-lived `sk-ant-oat01-` tokens auth correctly but bypass the 5h subscription session window, so we don't use them.

### 4. Test each account

```bash
unset CLAUDE_CODE_OAUTH_TOKEN
for i in 1 2 3; do
  echo "=== acct $i ==="
  CLAUDE_CONFIG_DIR=$HOME/.claude-account-$i \
    claude -p "hello" --model haiku --no-session-persistence
done
```

All three should return a normal greeting. If one says "Not logged in", re-run
`CLAUDE_CONFIG_DIR=$HOME/.claude-account-N claude /login` for that account.

### 5. Install the cron jobs

As `luis` on the host (NOT inside any container — the cron MUST run on the host because that's the only context that can write `.credentials.json`):

```bash
( crontab -l 2>/dev/null; cat /opt/homelab/scripts/claude-ideas/crontab-entries.txt ) | crontab -
crontab -l | grep claude   # sanity check
```

### 6. Install the dashboard "Refresh now" trigger watcher

The dashboard container cannot write `.credentials.json` (its bind mount is `:ro`, by design — single-writer rule). So the "Refresh now" button now drops a trigger file at `/opt/claude-ideas/.refresh-requested`, and a host-side systemd path unit runs `fetch-claude-limits.sh` as `luis` when it appears.

Install the path + service units once:

```bash
sudo cp /opt/homelab/scripts/claude-ideas/claude-limits-refresh.path    /etc/systemd/system/
sudo cp /opt/homelab/scripts/claude-ideas/claude-limits-refresh.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now claude-limits-refresh.path
systemctl status claude-limits-refresh.path
```

Smoke-test the trigger:

```bash
touch /opt/claude-ideas/.refresh-requested
sleep 3
journalctl -u claude-limits-refresh.service -n 30 --no-pager
cat /opt/claude-ideas/limits.json | python3 -m json.tool | head -20
```

### 7. Install the build watcher (dashboard "Build" button)

The build watcher picks up dashboard-submitted build jobs and runs Claude
Code inside a **per-build transient systemd unit**, so any dev servers Claude
spawns via the Bash tool (`npm run dev`, `tsx watch`, `node --watch`) are
contained in their own cgroup and reaped when the build finishes, fails, or
hits `RuntimeMaxSec`. The watcher itself runs as a `--user` service so it can
call `systemd-run --user`.

One-time setup as `luis`:

```bash
# Enable user-systemd persistence (so the watcher and its child units run
# even when nobody is logged in)
sudo loginctl enable-linger luis

# If the old SYSTEM-level service exists, take it down first
sudo systemctl disable --now claude-build-watcher 2>/dev/null || true
sudo rm -f /etc/systemd/system/claude-build-watcher.service
sudo systemctl daemon-reload

# Install the user-level unit + slice
mkdir -p ~/.config/systemd/user
cp /opt/homelab/scripts/claude-ideas/claude-build-watcher.service ~/.config/systemd/user/
cp /opt/homelab/scripts/claude-ideas/claude-builds.slice          ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now claude-build-watcher
systemctl --user status claude-build-watcher
```

Smoke-test from the dashboard ("Build" any project) and confirm the
transient unit shows up:

```bash
systemctl --user list-units 'claude-build-*'
journalctl --user -u 'claude-build-*' -n 50 --no-pager
```

When you need to nuke every leftover build process (e.g. after a code
change, or to clean up zombies):

```bash
systemctl --user stop 'claude-build-*.service'   # kills the cgroups, not the watcher
# or, full reset:
systemctl --user restart claude-build-watcher
```

### 8. Verify cron is running

```bash
crontab -l
# After the first run:
cat /opt/claude-ideas/generator.log
cat /opt/claude-ideas/project-ideas.jsonl | tail -1 | python3 -m json.tool | head -20
```

## Schedule

Every 4.5 hours, starting at 4am/5am/6am for accounts 1/2/3. The pattern resets at 4am each day (any run that would land after the next day's 4am cutoff is dropped).

| Account | Times (UTC)                          |
|---------|--------------------------------------|
| 1       | 04:00, 08:30, 13:00, 17:30, 22:00    |
| 2       | 05:00, 09:30, 14:00, 18:30, 23:00    |
| 3       | 06:00, 10:30, 15:00, 19:30, 00:00    |

**Total: 15 idea generations per day** across 3 accounts.

Limits are fetched hourly by `fetch-claude-limits.sh`.

## Files

| File | Purpose |
|------|---------|
| `setup-claude-accounts.sh` | One-time install & per-account `claude /login`. The `setup-token` step it offers is no longer needed — leave it skipped |
| `claude-idea-generator.sh` | Generates one idea (called by cron). Authenticates via `~/.claude-account-N/.credentials.json` under an exclusive `flock` |
| `fetch-claude-limits.sh` | Hourly: fetches usage limits + refreshes short-lived access tokens. Holds an exclusive flock on `.credentials.json` so it can't race with the keep-alive or generator scripts. Falls back to last-known-good with `stale: true` when refresh fails so the dashboard degrades gracefully |
| `keepalive-claude-tokens.sh` | Daily: forces a `refresh_token` rotation on every account so refresh tokens don't expire from idleness |
| `alert-claude-limits.sh` | Hourly: alerts if any account stays in error state for 2+ consecutive checks. Edit `notify()` to wire to ntfy/Home Assistant |
| `build-watcher.sh` | user-systemd-managed: picks up build jobs from the dashboard and spawns each in its own transient `claude-build-<id>.service` cgroup |
| `run-build.sh` | Runs `claude -p` for one build under `timeout 1800`. Status flows queued → running → zipping → done/error |
| `claude-build-watcher.service` | The watcher itself — install into `~/.config/systemd/user/` (linger required) |
| `claude-builds.slice` | Resource ceilings shared across all concurrent builds (Memory, Tasks, CPUWeight) |
| `claude-limits-refresh.path` + `.service` | systemd path watcher: host-side runs `fetch-claude-limits.sh` as `luis` when the dashboard drops `/opt/claude-ideas/.refresh-requested` |
| `crontab-entries.txt` | Cron entries to paste |

## Authentication architecture

All three scripts (`claude-idea-generator.sh`, `fetch-claude-limits.sh`,
`keepalive-claude-tokens.sh`) authenticate through the **subscription OAuth
flow** in `~/.claude-account-N/.credentials.json` — the same path your
interactive `claude` sessions use.

We tried switching the generator to long-lived `sk-ant-oat01-` tokens (via
`claude setup-token`) after the 2026-04-21 outage to dodge the refresh-token
race. That worked for auth but failed the bigger goal: long-lived tokens
route through a separate billing bucket that `api.anthropic.com/api/oauth/usage`
doesn't report, so they don't open the 5-hour subscription session window —
which was the whole point of running ideas every 4.5 hours. Reverted.

### `flock`-based serialization on `.credentials.json`

All three writers acquire an **exclusive POSIX `flock`** on the per-account
`.credentials.json` before mutating it:

- `fetch-claude-limits.sh` — Python `fcntl.flock(LOCK_EX)` while reading +
  refreshing the access token
- `keepalive-claude-tokens.sh` — same, daily forced refresh
- `claude-idea-generator.sh` — bash `flock -x` held across the entire
  `claude -p` invocation, since the CLI itself may rotate the refresh token
  mid-call

Bash `flock` and Python `fcntl.flock` use the same kernel primitive, so the
three serialize cleanly. The dashboard API container is bind-mounted `:ro` on
the creds files, so it can never become a fourth writer.

If `.credentials.json` ever does get bricked (browser tab killed mid-rotation,
disk full, etc.), recover with:

```bash
CLAUDE_CONFIG_DIR=$HOME/.claude-account-N claude /login
```

## Output

All responses append to: `/opt/claude-ideas/project-ideas.txt`
Logs at: `/opt/claude-ideas/generator.log`

## Notes

- The `CLAUDE_CONFIG_DIR` env var tells Claude Code which account to use
- `--no-session-persistence` keeps it stateless (no leftover sessions)
- Each run counts against that account's usage quota
- If an account's session expires, re-run: `CLAUDE_CONFIG_DIR=~/.claude-account-N claude login`
