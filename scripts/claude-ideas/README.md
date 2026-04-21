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
- Walk you through logging in to each account (opens browser via Tailscale)

### 4. Test each account

```bash
CLAUDE_CONFIG_DIR=~/.claude-account-1 claude -p "hello" --model haiku --no-session-persistence
CLAUDE_CONFIG_DIR=~/.claude-account-2 claude -p "hello" --model haiku --no-session-persistence
CLAUDE_CONFIG_DIR=~/.claude-account-3 claude -p "hello" --model haiku --no-session-persistence
```

### 5. Install the cron jobs

```bash
crontab -e
```

Paste the contents of `crontab-entries.txt` (keep any existing cron entries).

### 6. Verify cron is running

```bash
crontab -l
# After the first run:
cat /opt/claude-ideas/generator.log
cat /opt/claude-ideas/project-ideas.txt
```

## Schedule

| Account | Schedule (every 4 hours starting at) |
|---------|--------------------------------------|
| 1       | 4am, 8am, 12pm, 4pm, 8pm, 12am     |
| 2       | 5am, 9am, 1pm, 5pm, 9pm, 1am       |
| 3       | 6am, 10am, 2pm, 6pm, 10pm, 2am     |

**Total: 18 idea generations per day** across 3 accounts.

## Files

| File | Purpose |
|------|---------|
| `setup-claude-accounts.sh` | One-time install & auth setup |
| `claude-idea-generator.sh` | The script cron calls |
| `crontab-entries.txt` | Cron entries to paste |

## Output

All responses append to: `/opt/claude-ideas/project-ideas.txt`
Logs at: `/opt/claude-ideas/generator.log`

## Notes

- The `CLAUDE_CONFIG_DIR` env var tells Claude Code which account to use
- `--no-session-persistence` keeps it stateless (no leftover sessions)
- Each run counts against that account's usage quota
- If an account's session expires, re-run: `CLAUDE_CONFIG_DIR=~/.claude-account-N claude login`
