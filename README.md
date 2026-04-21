# bracas homelab

Personal homelab running on Ubuntu 22.04 at `100.87.156.88`, accessed via Tailscale.

## Stack

| Service | Location | Port | Description |
|---|---|---|---|
| Home Assistant | `digitaltwin/` | 8123 | IoT hub + digital twin entities |
| Mosquitto MQTT | `digitaltwin/` | 1883 | IoT message broker |
| Zigbee2MQTT | `digitaltwin/` | 8080 | Zigbee bridge (disabled — dongle pending) |
| Digital Twin API | `digitaltwin/api/` | 8000 | REST API for 3D house model |
| Digital Twin Frontend | `digitaltwin/frontend/` | 8090 | Three.js 3D viewer (nginx static + API proxy) |
| Dashboard API | `homelab-dashboard/api/` | 8787 | Flask dashboard — backup, glances, tailscale, HA |
| Homepage | `homelab-dashboard/` | 3000 | Internal service dashboard |
| Glances | `homelab-dashboard/` | 61208 | Server monitoring agent |
| Caddy | `caddy/` | 8088 | Reverse proxy (HTTP basic auth) |
| Nextcloud | snap-managed | 80 | File storage |

---

## Dashboard API (`homelab-dashboard/api/`)

Flask app at `:8787`. `dashboard.html` is baked into the image via `COPY` in the
Dockerfile — changes require `up -d --build dashboard-api`.

| Endpoint | Method | Description |
|---|---|---|
| `GET /` | GET | Serves `dashboard.html` |
| `/api/glances/<server>` | GET | Glances stats for `main` or `backup` |
| `/api/tailscale/peers` | GET | Tailscale peer list with online status |
| `/api/backup/status` | GET | Last backup result (`backup-last.json`) |
| `/api/backup/live` | GET | Live backup progress (`backup-live.json`) |
| `/api/backup/trigger` | POST | Triggers a manual backup on the backup server |
| `/api/ha/devices` | GET | All Home Assistant entity states |
| `/api/ha/control` | POST | Toggle/control a HA entity |
| `/api/nextcloud-disk-fields` | GET | Nextcloud data directory disk usage |
| `/api/backup-disk-fields` | GET | Backup server root disk usage (via Glances) |

## Digital Twin (`digitaltwin/`)

Three.js 3D home viewer integrated into the main dashboard as a tab.

- **Frontend** at `:8090` — nginx serving static files from `frontend/` (volume-mounted)
- **API** at `:8000` — Flask with SQLite for device registry and 3D positions

The frontend proxies `/api/` and `/health` to the API container via nginx.

### Secrets

- `digitaltwin/api/.env` — `HA_TOKEN`, `HA_URL`

## Backup Server (`bracasbck` — `100.90.102.52`)

Managed separately in the `homelab-backup` repo.

| Endpoint | Port | Description |
|---|---|---|
| `/run-backup` | 8081 | POST — triggers `backup-nextcloud.sh` |
| `/backup-status` | 8081 | GET — `{"running": true/false}` |
| `/backup-live.json` | 8081 | GET — written by script while running |
| `/backup-last.json` | 8081 | GET — written by script on completion |

Flask served via `backup-live-http.service` systemd unit.
Files live at `/home/luis/backup-dashboard/` on the backup server.

## Secrets (NOT in this repo)

- `digitaltwin/api/.env` — `HA_TOKEN`, `HA_URL`
- `homelab-dashboard/api/dashboard-api.env` — `HA_TOKEN`, `NEXTCLOUD_DATA_DIR`

Create these manually on a fresh server.

## Restore on a new server

```bash
git clone git@github.com:luisbracamontes/homelab.git /opt/homelab

# Secrets
cp ~/secrets/digitaltwin.env      /opt/homelab/digitaltwin/api/.env
cp ~/secrets/dashboard-api.env    /opt/homelab/homelab-dashboard/api/dashboard-api.env

# Start services
cd /opt/homelab/digitaltwin        && docker compose up -d
cd /opt/homelab/homelab-dashboard  && docker compose up -d --build

# Caddy
sudo cp /opt/homelab/caddy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Daily automation

```
*/30 * * * *  /opt/homelab/homelab-dashboard/build_services.sh   # Tailscale device list
50 10 * * *   /opt/homelab-backup/backup-nextcloud.sh             # Nextcloud backup
```
