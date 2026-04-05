"""
Home Assistant REST client.
Normalizes raw HA state into a clean, consistent device model
that the frontend (Three.js) can use directly.
"""
import os
import requests

# Domains we never expose — internal HA plumbing.
#
# input_boolean / input_number / input_select are HA helper primitives.
# In this setup they back the template lights/sensors but are NOT real
# devices — the template entities (light.*, binary_sensor.*, sensor.*,
# lock.*) are what should be registered in the twin.
# Hiding the helpers prevents confusion where a user registers
# "input_boolean.sim_bedroom_light" instead of "light.bedroom".
SKIP_DOMAINS = {
    "persistent_notification", "tts", "zone", "weather", "update",
    "conversation", "stt", "wake_word", "assist_pipeline", "tag",
    "event", "timer", "todo", "media_source", "image", "select",
    # HA helpers — implementation details, not real devices
    "input_boolean", "input_number", "input_select", "input_text",
    "input_datetime", "input_button",
}

# Domains that can be controlled
CONTROLLABLE = {
    "light", "switch", "fan", "cover",
    "climate", "media_player", "lock", "vacuum",
}

class HAError(Exception):
    pass

class HomeAssistantClient:
    def __init__(self):
        url   = os.environ.get("HA_URL", "").rstrip("/")
        token = os.environ.get("HA_TOKEN", "")
        if not url or not token:
            raise HAError("HA_URL and HA_TOKEN env vars are required")
        self.base    = url
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization":  f"Bearer {token}",
            "Content-Type":   "application/json",
        })

    def _get(self, path):
        try:
            r = self.session.get(f"{self.base}/api/{path}", timeout=5)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            raise HAError(f"HA returned {e.response.status_code}: {e.response.text}")
        except requests.RequestException as e:
            raise HAError(f"HA unreachable: {e}")

    def _post(self, path, data):
        try:
            r = self.session.post(f"{self.base}/api/{path}", json=data, timeout=5)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            raise HAError(f"HA returned {e.response.status_code}: {e.response.text}")
        except requests.RequestException as e:
            raise HAError(f"HA unreachable: {e}")

    def ping(self):
        try:
            self._get("")
            return True
        except Exception:
            return False

    def get_states(self):
        return self._get("states")

    def get_state(self, entity_id):
        return self._get(f"states/{entity_id}")

    def call_service(self, domain, service, data):
        return self._post(f"services/{domain}/{service}", data)

    def normalize(self, state, db_meta=None):
        """
        Convert a raw HA state dict into our clean device model.
        db_meta is the row from SQLite (or None if not registered).
        """
        entity_id = state["entity_id"]
        domain    = entity_id.split(".")[0]
        attrs     = state.get("attributes", {})
        supported = attrs.get("supported_features", 0) or 0
        color_modes = attrs.get("supported_color_modes") or []

        # ── Capabilities ───────────────────────────────────────────────
        caps = []
        if domain in CONTROLLABLE:
            caps.append("on_off")

        if domain == "light":
            if "brightness" in color_modes or (supported & 1):
                caps.append("brightness")
            if "color_temp" in color_modes or (supported & 2):
                caps.append("color_temp")
            if any(m in color_modes for m in ["rgb","hs","xy","rgbw","rgbww"]) or (supported & 16):
                caps.append("color")
            if attrs.get("effect_list"):
                caps.append("effects")

        elif domain == "cover":
            if supported & 4:
                caps.append("position")

        elif domain == "climate":
            caps += ["target_temp", "hvac_mode"]

        elif domain == "media_player":
            caps += ["volume", "media_control"]

        elif domain == "fan":
            if supported & 1:
                caps.append("speed")

        elif domain == "sensor":
            caps.append("read_only")

        elif domain == "binary_sensor":
            caps.append("read_only")

        # ── Live state ─────────────────────────────────────────────────
        live = {"state": state["state"]}

        if domain == "light":
            b = attrs.get("brightness")
            live.update({
                "brightness":        b,
                "brightness_pct":    round(b / 255 * 100) if b else None,
                "color_temp_mireds": attrs.get("color_temp"),
                "color_temp_kelvin": attrs.get("color_temp_kelvin"),
                "rgb_color":         attrs.get("rgb_color"),
                "hs_color":          attrs.get("hs_color"),
                "effect":            attrs.get("effect"),
                "effects_list":      attrs.get("effect_list"),
            })

        elif domain == "sensor":
            live.update({
                "value":        state["state"],
                "unit":         attrs.get("unit_of_measurement"),
                "device_class": attrs.get("device_class"),
            })

        elif domain == "binary_sensor":
            live.update({
                "device_class": attrs.get("device_class"),
            })

        elif domain == "climate":
            live.update({
                "hvac_mode":    attrs.get("hvac_mode"),
                "hvac_modes":   attrs.get("hvac_modes"),
                "current_temp": attrs.get("current_temperature"),
                "target_temp":  attrs.get("temperature"),
            })

        elif domain == "cover":
            live.update({
                "position": attrs.get("current_position"),
            })

        elif domain == "media_player":
            live.update({
                "volume": attrs.get("volume_level"),
                "media":  attrs.get("media_title"),
            })

        # strip None values from live
        live = {k: v for k, v in live.items() if v is not None}

        # ── Twin metadata (from SQLite) ─────────────────────────────────
        meta = db_meta or {}

        return {
            "entity_id":     entity_id,
            "domain":        domain,
            "name":          (meta.get("display_name")
                              or attrs.get("friendly_name")
                              or entity_id),
            "ha_name":       attrs.get("friendly_name", entity_id),
            "capabilities":  caps,
            "controllable":  domain in CONTROLLABLE,
            "live":          live,
            "registered":    db_meta is not None,
            "room_id":       meta.get("room_id"),
            "position_3d":   meta.get("position_3d"),
            "notes":         meta.get("notes", ""),
            "registered_at": meta.get("registered_at"),
        }

    def get_discovered_devices(self, domain_filter=None):
        """
        Returns all HA entities grouped by domain,
        skipping internal HA plumbing and raw helpers.
        """
        states = self.get_states()
        result = {}
        for s in states:
            d = s["entity_id"].split(".")[0]
            if d in SKIP_DOMAINS:
                continue
            if domain_filter and d != domain_filter:
                continue
            result.setdefault(d, []).append(s)
        return result
