# bracas homelab

Personal homelab running on Ubuntu 22.04 at 100.87.156.88, accessed via Tailscale.

## Stack

| Service | Location | Port | Description |
|---|---|---|---|
| Home Assistant | digitaltwin/ | 8123 | IoT hub + digital twin entities |
| Mosquitto MQTT | digitaltwin/ | 1883 | IoT message broker |
| Zigbee2MQTT | digitaltwin/ | 8080 | Zigbee bridge (disabled — dongle pending) |
| Digital Twin API | digitaltwin/api/ | 8000 | REST API for 3D house model frontend |
| Homepage | homelab-dashboard/ | 3000 | Internal dashboard |
| Glances | homelab-dashboard/ | 61208 | Server monitoring |
| Dashboard API | homelab-dashboard/api/ | 8787 | Custom Flask API for Homepage widgets |
| Caddy | caddy/ | 8088 | Reverse proxy (HTTP basic auth) |
| Nextcloud | snap-managed | 80 | File storage |

## Secrets (NOT in this repo)
- `digitaltwin/api/.env` — HA_TOKEN
- `homelab-dashboard/api/dashboard-api.env` — HA_TOKEN, NEXTCLOUD_DATA_DIR

Create these manually on a fresh server. See each service README for required vars.

## Restore on a new server
```bash
git clone git@github.com:luisbracamontes/homelab.git /opt/homelab
cd /opt/homelab/digitaltwin && docker compose up -d
cd /opt/homelab/homelab-dashboard && docker compose up -d
sudo cp caddy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

## Daily automation
Tailscale device list regenerates every 30 min via cron:
`*/30 * * * * /opt/homelab/homelab-dashboard/build_services.sh`
