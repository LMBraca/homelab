# Digital Twin Frontend — Build Plan

## Current State

The backend is complete and production-ready:

- **`digitaltwin/api/`** — Flask REST API on port 8000
- **Rooms** — CRUD with floor number, color, notes
- **Devices** — registered from HA, stored with `room_id` and `position_3d: {x, y, z}`
- **`/api/v1/discover`** — all HA entities, grouped by domain, with registered flag
- **`/api/v1/twin/devices`** — registered devices with live HA state
- **`/api/v1/rooms/<id>`** — room detail with all devices inside it
- **Control** — `POST /api/v1/devices/<entity_id>/control` supports all HA service calls
- **Capabilities** — each device reports what it can do (`on_off`, `brightness`, `color`, `color_temp`, `read_only`, etc.)
- **3D positions** — stored as `{x, y, z}` per device in SQLite, ready to be consumed

The frontend doesn't exist yet. Everything below is what needs to be built.

---

## Getting a 3D House Model

Since you don't have a 3D model of your house yet, here are your options in order of effort:

### Option A — Free template (fastest, start building now)
Use a pre-made house template from Sketchfab or Poly Haven as a placeholder. Good ones to search:
- **Sketchfab**: search "house interior low poly free" — filter by License: CC
- Download as `.glb` or `.gltf` (Three.js native format)
- Good starting point: ["Stylized House"](https://sketchfab.com/search?q=low+poly+house+interior&type=models&features=downloadable&license=licenseCC)

Steps:
1. Go to sketchfab.com → filter: Free, Downloadable, glTF/GLB format
2. Download a 2-3 room house with interior visible
3. Drop the `.glb` into `digitaltwin/frontend/public/models/house.glb`
4. The viewer will load it immediately

### Option B — Model your actual house (recommended long term)
Use **Planner 5D** (free web app, planner5d.com):
1. Sign up free → New Project → draw your floorplan room by room
2. Add walls, doors, windows to match your house
3. Export → 3D View → Export as OBJ or use their API
4. Import OBJ into **Blender** (free), clean it up, export as `.glb`

Or use **Sweet Home 3D** (desktop app, free):
1. Draw floorplan → export to OBJ → import to Blender → export GLB

### Option C — iPhone LiDAR scan (most accurate)
If you have an iPhone 12 Pro or later:
1. Download **Polycam** (free tier) or **Scaniverse** (free)
2. Walk through each room in LiDAR mode — takes ~5 min per room
3. Export as `.glb` or `.obj`
4. Clean up in Blender (decimate mesh to reduce file size)
5. Result: a photorealistic mesh of your actual house

### Model Requirements for the Viewer
Whatever model you get, it needs to:
- Be in **`.glb` format** (single binary file — easiest to serve)
- Have **named meshes** per room (e.g. `Mesh_LivingRoom`, `Mesh_Bedroom`) — this is what enables room highlighting
- Be under **~20MB** for comfortable loading (use Blender's Decimate modifier to reduce if needed)
- Have a **reasonable coordinate scale** — Three.js defaults to 1 unit = 1 meter

In Blender, you can rename mesh objects in the Outliner panel. Name them to match your `room_id` values in the API (e.g. `living_room`, `bedroom`, `kitchen`).

---

## Frontend Architecture

### Tech Stack
- **Three.js** (r160+) — 3D rendering, model loading, camera control
- **Vanilla JS + HTML** — no framework, keeps it simple and deployable as static files
- **GLTFLoader** — loads `.glb` models
- **OrbitControls** — mouse navigation
- Served as static files from a new `digitaltwin/frontend/` directory
- Proxied through Caddy alongside the API

### File Structure
```
digitaltwin/frontend/
├── index.html              # entry point
├── js/
│   ├── main.js             # boot, scene setup, render loop
│   ├── viewer.js           # Three.js scene, model loading, camera
│   ├── rooms.js            # room highlighting, floor switching, selection
│   ├── devices.js          # device markers, popups, controls
│   ├── api.js              # all calls to /api/v1/*
│   ├── ui.js               # sidebar, panels, search, toasts
│   └── store.js            # client-side state (selected room, devices cache)
├── css/
│   └── style.css           # dark theme matching homelab-dashboard
└── public/
    └── models/
        └── house.glb       # your house model goes here
```

---

## UI Layout

```
┌─────────────────────────────────────────────────────────┐
│  HEADER: bracas digital twin    [Floor 1][Floor 2]  🔍  │
├──────────────────┬──────────────────────────────────────┤
│                  │                                      │
│   SIDEBAR        │         3D VIEWPORT                  │
│                  │                                      │
│  Rooms           │    [Orbit/Pan/Zoom with mouse]        │
│  ─────           │                                      │
│  Living Room (4) │    House model renders here          │
│  Bedroom (2)     │    Rooms highlight on hover          │
│  Kitchen (1)     │    Device icons float in 3D space    │
│  Hallway (0)     │                                      │
│                  │                                      │
│  + Add Room      │                                      │
│                  ├──────────────────────────────────────┤
│  ─────           │   DEVICE PANEL (slides up on click)  │
│  All Devices     │                                      │
│  Unassigned (3)  │   💡 Living Room Lamp                │
│                  │   State: ON  Brightness: 70%         │
│  ─────           │   [Turn Off] [──●────] brightness    │
│  + Add Device    │   Room: Living Room  [change]        │
└──────────────────┴──────────────────────────────────────┘
```

---

## Build Phases

### Phase 1 — Static Viewer (no IoT yet)
**Goal:** Load the house model, navigate it, click rooms.

1. Set up `digitaltwin/frontend/` directory and serve it via a simple static server
2. Boot Three.js scene: renderer, camera, lights, OrbitControls
3. Load `house.glb` with GLTFLoader, center and scale it automatically
4. Add ambient + directional lighting (warm interior feel)
5. Raycasting on click/hover — detect which mesh was clicked
6. Room highlight: on hover, highlight mesh yellow; on click, highlight blue
7. Floor switcher: show/hide meshes by floor (using mesh naming convention)
8. Camera: clicking a room zooms the camera smoothly into it (TWEEN.js)
9. Fallback: if no model loaded, render a procedural box-room placeholder

Deliverable: you can load the viewer, orbit around the house, hover over rooms to see them highlight, click to select them.

---

### Phase 2 — Room + Device Data Layer
**Goal:** Connect the 3D viewer to the API.

1. `api.js` — fetch wrappers for all `/api/v1/*` endpoints
2. On load: fetch all rooms (`GET /api/v1/rooms`), all twin devices (`GET /api/v1/twin/devices`)
3. Store in `store.js` — reactive simple object with room map and device map
4. Sidebar renders room list from API data with device counts
5. Clicking a room in the sidebar also selects it in the 3D view (and vice versa)
6. Device markers: for each registered device with a `position_3d`, place a 3D icon (sphere or billboard) at that position in the scene
7. Device icons are colored by state (green = on, grey = off, blue = sensor)
8. Hovering a device icon shows a tooltip with name + state
9. Poll `/api/v1/twin/devices` every 5s to keep live state in sync

Deliverable: rooms shown in sidebar with counts, device dots visible in 3D space, live state polling.

---

### Phase 3 — Device Control Panel
**Goal:** Click a device, control it.

1. Clicking a device marker (or a device in the sidebar) opens a slide-up panel
2. Panel reads `capabilities` from the API response to know what controls to render:
   - `on_off` → toggle button
   - `brightness` → slider (0–100%)
   - `color_temp` → warm/cool slider
   - `color` → color wheel (use a simple HSL picker)
   - `read_only` → just shows value, no controls
3. All control actions call `POST /api/v1/devices/<entity_id>/control`
4. After action, re-fetch device state and update marker color
5. Panel has a "Move to room" dropdown — calls `PUT /api/v1/twin/devices/<entity_id>`
6. Panel has a "Set position in 3D" button — enters placement mode (click in 3D to drop device at that point)

Deliverable: full device control from the 3D view.

---

### Phase 4 — Device Registration Flow
**Goal:** Add new devices from the UI.

1. "Add Device" button opens a modal
2. Calls `GET /api/v1/discover?unregistered=true` to list unregistered HA devices
3. Shows list grouped by domain with a search box
4. Select a device → optional: assign room, set display name, add notes
5. Submit → `POST /api/v1/twin/devices`
6. Device appears in the 3D view immediately (needs 3D position placement)
7. 3D placement mode: after adding a device, prompt "click in the 3D view to place this device"
8. On click, raycasting against the house mesh gets the 3D point → stored via `PUT /api/v1/twin/devices`

Deliverable: complete onboarding flow for new devices.


### Phase 5 — Polish
- Loading screen while model and API data fetch
- Toast notifications for control actions (success/failure)
- Keyboard shortcuts: `Esc` to deselect, `F` to frame selected room, `1`/`2` for floors
- Mobile-friendly: collapse sidebar, bottom sheet for device panel
- Dark theme matching `homelab-dashboard` CSS variables
- Connection status indicator (HA online/offline)
- Search: `Ctrl+K` opens command palette to search rooms and devices
- Switching floors: hides/shows meshes based on floor number (meshes need floor metadata — either from naming convention or from the rooms API)

---

## Serving the Frontend

Add to `digitaltwin/docker-compose.yml`:
```yaml
  frontend:
    image: nginx:alpine
    container_name: digital-twin-frontend
    ports:
      - "8090:80"
    volumes:
      - ./frontend:/usr/share/nginx/html:ro
    restart: unless-stopped
```

Add to Caddyfile:
```
digital-twin.bracas.internal {
    reverse_proxy /api/* localhost:8000
    file_server {
        root /path/to/frontend
    }
}
```

Or more simply, have the digital-twin-api Flask app also serve the frontend static files (already possible since it uses `send_from_directory`).

---

## Data Flow Summary

```
HA (8123)
   ↕ REST (token auth)
digital-twin-api (8000)  ←→  SQLite (rooms, positions, metadata)
   ↕ REST
Frontend (browser)
   - Three.js renders GLB model
   - Fetches rooms + devices from API
   - Polls /api/v1/twin/devices every 5s for live state
   - Sends control commands to API → forwarded to HA
```

---

## What to Build First

Start with Phase 1. You can do this right now even without your real house model by using a placeholder GLB from Sketchfab. The 3D viewer, navigation, and room selection don't require any API connectivity — you can build and test them completely offline.

Once Phase 1 is solid, Phase 2 brings the API in and everything else follows naturally.

Recommended first session: get `index.html` + `main.js` + `viewer.js` running locally with any GLB model, OrbitControls working, and a room highlight on click.
