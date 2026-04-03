# Digital Twin Stack

## Services
| Service        | Port  | URL                            |
|---------------|-------|--------------------------------|
| Home Assistant | 8123  | http://100.87.156.88:8123      |
| Mosquitto MQTT | 1883  | mqtt://100.87.156.88:1883      |
| Mosquitto WS   | 9001  | ws://100.87.156.88:9001        |
| Zigbee2MQTT    | 8080  | http://100.87.156.88:8080 (disabled until dongle arrives) |

## Simulated Entities
| Entity ID            | Type  | Notes                    |
|----------------------|-------|--------------------------|
| light.living_room    | light | Template light, on/off + brightness |
| light.bedroom        | light | Template light, on/off + brightness |
| light.hallway        | light | Template light, on/off + brightness |

## Commands
```
cd /opt/digitaltwin
docker compose up -d            # start all
docker compose ps               # check status
docker restart homeassistant    # after config changes
docker logs homeassistant --tail=100
docker logs mosquitto --tail=100
```

## Token
HA long-lived access token stored in: [your secure location]
