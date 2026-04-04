# bracas homelab

Personal homelab running on Ubuntu 22.04 at `100.87.156.88`, accessed via Tailscale.

## Stack

| Service | Location | Port | Description |
|---|---|---|---|
| Home Assistant | `digitaltwin/` | 8123 | IoT hub + digital twin entities |
| Mosquitto MQTT | `digitaltwin/` | 1883 | IoT message broker |
| Zigbee2MQTT | `digitaltwin/` | 8080 | Zigbee bridge (disabled — dongle pending) |
| Digital Twin API | `digitaltwin/api/` | 8000 | REST API for 3D house model frontend |
| Homepage | `homelab-dashboard/` | 3000 | Internal service dashboard |
| Glances | `homelab-dashboard/` | 61208 | Server monitoring |
| Dashboard API | `homelab-dashboard/api/` | 8787 | Custom Flask API — backup status, Glances proxy, Tailscale peers, HA control |
| Caddy | `caddy/` | 8088 | Reverse proxy (HTTP basic auth) |
| Nextcloud | snap-managed | 80 | File storage |

## Dashboard API (`homelab-dashboard/api/`)

Flask app served at `:8787`. Runs inside Docker. Exposes:

| Endpoint | Method | Description |
|---|---|---|
| `GET /` | GET | Serves `dashboard.html` — the main homelab dashboard UI |
| `/api/glances/<server>` | GET | Proxies Glances stats for `main` or `backup` server |
| `/api/tailscale/peers` | GET | Tailscale peer list with online status |
| `/api/backup/status` | GET | Last backup result from backup server (`backup-last.json`) |
| `/api/backup/live` | GET | Live backup progress from backup server (`backup-live.json`) |
| `/api/backup/running` | GET | Whether a backup is currently running (Flask flag on backup server) |
| `/api/backup/trigger` | POST | Triggers a manual backup on the backup server |
| `/api/ha/devices` | GET | All Home Assistant entity states |
| `/api/ha/control` | POST | Toggle/control a HA entity |
| `/api/nextcloud-disk-fields` | GET | Nextcloud data directory disk usage |
| `/api/backup-disk-fields` | GET | Backup server root disk usage (via Glances) |

The dashboard polls `/api/backup/live` every 4 seconds while a backup is running, showing
live step, elapsed time, rsync speed, ETA, progress bar, and current file. Falls back to
the last backup summary when idle.

## Backup Server (`bracasbck` — `100.90.102.52`)

Managed separately in the `homelab-backup` repo. The main dashboard talks to it over Tailscale.

| Endpoint | Port | Description |
|---|---|---|
| `/run-backup` (POST) | 8081 | Triggers `backup-nextcloud.sh` |
| `/backup-status` (GET) | 8081 | `{"running": true/false}` from Flask memory |
| `/backup-live.json` (GET) | 8081 | Written by `backup-nextcloud.sh` while running |
| `/backup-last.json` (GET) | 8081 | Written by `backup-nextcloud.sh` on completion |

The backup server runs `homelab-dashboard/api/server.py` (Flask) via the
`backup-live-http.service` systemd unit at `/etc/systemd/system/backup-live-http.service`.
Files are deployed to `/home/luis/backup-dashboard/` on the backup server.

## Secrets (NOT in this repo)

- `digitaltwin/api/.env` — `HA_TOKEN`
- `homelab-dashboard/api/dashboard-api.env` — `HA_TOKEN`, `NEXTCLOUD_DATA_DIR`

Create these manually on a fresh server. See each service for required vars.

## Restore on a new server

```bash
git clone git@github.com:luisbracamontes/homelab.git /opt/homelab
cd /opt/homelab/digitaltwin && docker compose up -d
cd /opt/homelab/homelab-dashboard && docker compose up -d
sudo cp caddy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

## Sync workflow

Changes are made locally (Mac) and pushed to the server via rsync:

```bash
# Push main server files
cd ~/Documents/personal/homelab-server
./push-to-server.sh

# Push backup server files
cd ~/Documents/personal/homelab-backup
./push-to-backup-server.sh

# Restart dashboard after API changes
ssh luis@100.87.156.88 "cd /opt/homelab/homelab-dashboard && docker compose restart"

# Restart backup Flask server after changes
ssh luis@100.90.102.52 "sudo systemctl restart backup-live-http.service"
```

## Daily automation

Tailscale device list regenerates every 30 min via cron:
```
*/30 * * * * /opt/homelab/homelab-dashboard/build_services.sh
```

Nextcloud backup runs daily at 10:50am on the backup server:
```
50 10 * * * /opt/homelab-backup/backup-nextcloud.sh
```
