# House 3D Model Guide

Four paths depending on how much time you want to invest.
All four end at the same place: a `.glb` file with named room meshes sitting at
`digitaltwin/frontend/public/models/house.glb`.

---

## Path D — Revit → GLB (recommended if you have floor plans)

This is the best option if you already have floor plans and someone who knows
Revit. Revit is professional architectural software — the geometry will be clean,
accurate, and scale-correct out of the box.

### Brief to give the Revit person

Copy and paste this:

> "I need a 3D model of the house exported as a `.glb` file for a web-based
> 3D viewer. Requirements:
> - Each room must be a **separate named object** in the export, named exactly
>   as listed below (lowercase, underscores)
> - Architectural shell only — walls, floors, ceilings, doors, windows
> - No furniture, no landscaping, no interior details
> - Medium-low polygon count is fine — this is for a browser viewer, not a render
> - Target file size: under 20MB
> - Preferred export format: FBX or IFC (we'll convert to GLB)"

Then give them your room ID list — these must match your API `room_id` values exactly:
```
living_room
kitchen
bedroom
master_bedroom
bathroom
hallway
garage
office
```
(adjust to your actual rooms)

---

### The Revit Room Tool (tell them to use this)

In Revit there is a **Room** tool (Architecture tab → Room & Area → Room).
If the Revit person places a Room object in each space and names it using
your `room_id` list, those names survive the IFC export automatically.
This is the cleanest workflow — it means almost no renaming work in Blender.

Tell them: "Please use the Revit Room tool and name each room as follows:
`Living Room`, `Kitchen`, `Bedroom`, etc. — I'll handle the underscore
conversion."

---

### Export routes out of Revit

Revit does not export `.glb` natively. Use one of these:

#### Route 1 — FBX → Blender → GLB (easiest, most common)

**In Revit:**
1. `File → Export → FBX`
2. Options dialog:
   - Export: 3D View (not sheets)
   - Include: Rooms ✓
   - Cameras/Lights: not needed
3. Save as `house.fbx`

**In Blender:**
1. `File → Import → FBX` → select `house.fbx`
2. The house appears. Each Revit category (Walls, Floors, Ceilings) comes in
   as a separate object collection
3. Check the Outliner — if rooms were named in Revit, you may see them already
4. Rename mesh objects in the Outliner to your `room_id` values (see Naming
   section below)
5. Add **Decimate modifier** (ratio `0.3`) — Revit geometry is already clean
   so you don't need to go very low
6. `File → Export → glTF 2.0 → Binary (.glb)`

#### Route 2 — IFC → Blender → GLB (preserves room names automatically)

IFC (Industry Foundation Classes) is an open format that carries room metadata.
If rooms were placed using the Revit Room tool, their names survive the export.

**In Revit:**
1. `File → Export → IFC`
2. IFC version: IFC 2x3 or IFC 4 (either works)
3. Export as: `house.ifc`

**In Blender:**
1. Install the **BlenderBIM** add-on (free): [blenderbim.org/download](https://blenderbim.org/download)
   - Download the zip → Blender Preferences → Add-ons → Install → select zip
2. `File → Import → IFC` → select `house.ifc`
3. Rooms come in as named objects matching their Revit Room names
4. In the Outliner, verify names → rename any that don't match your `room_id` list
5. Decimate + Export as GLB (same as Route 1)

#### Route 3 — Direct GLB via Enscape or Twinmotion (zero Blender work)

If the Revit person has either of these plugins (very common in architecture firms):

**Enscape** (Revit plugin):
- Enscape toolbar → Export → `Export as glTF` → saves `.glb` directly
- No Blender needed

**Twinmotion** (standalone, free for Architects):
- Open Revit model in Twinmotion via the Datasmith plugin
- `File → Export → glTF 2.0`
- Clean GLB, proper scale, textures included

Ask the Revit person: *"Do you have Enscape or Twinmotion? If so, you can export
GLB directly."* This saves the most time.

---

### Naming meshes in Blender (if not already named from IFC)

After importing FBX into Blender, objects are often named by Revit category
(`Walls`, `Floors`, `Generic Models`, etc.) rather than by room. You need to
separate and rename them.

**Option A — If Revit geometry is separated by room already:**
1. Open Outliner → look for objects named after rooms
2. Double-click each → rename to `room_id` format:
   - `Living Room` → `living_room`
   - `Master Bedroom` → `master_bedroom`

**Option B — If everything came in as one mesh:**
1. Select the mesh → Tab → Edit Mode → Face Select (press 3)
2. Click a face in one room → Select Linked (L key) to select connected geometry
3. Press P → Selection → separates it into its own object
4. Tab out → rename the new object in Outliner
5. Repeat per room

**Multi-floor naming convention:**
```
floor1_living_room      ← Floor 1, room_id: living_room
floor1_kitchen          ← Floor 1, room_id: kitchen
floor2_master_bedroom   ← Floor 2, room_id: master_bedroom
floor2_office           ← Floor 2, room_id: office
```
The viewer JavaScript strips the `floor1_`/`floor2_` prefix when matching to the API.

---

### Validating the GLB before using it

1. [gltf.report](https://gltf.report) — drop your `.glb` here
   - Confirm mesh names match your `room_id` list
   - Check polygon count (target: under 100k total)
   - Check file size (target: under 20MB)

2. [sandbox.babylonjs.com](https://sandbox.babylonjs.com) — drag and drop to
   preview visually and orbit around it

3. Scale check: in the Babylon sandbox, a standard door should be ~2m tall.
   If your house looks the size of a postage stamp or a stadium, the scale is
   wrong. Fix in Blender: select all (A) → S → type scale factor → Enter.

---

## Path A — Sketchfab Template (30 minutes, start today)

Use this while the Revit model is being prepared. Replace it later.

1. Go to [sketchfab.com/search](https://sketchfab.com/search)
2. Search: `low poly house interior`
3. Filters: **Downloadable** ✓ + **Creative Commons** ✓ + **glTF** ✓
4. Download → unzip → get `.glb` or `.gltf`+`.bin`
5. If `.gltf`, open Blender → Import glTF → Export as **glTF Binary (.glb)**
6. Rename meshes in Outliner to your `room_id` values
7. Drop at `digitaltwin/frontend/public/models/house.glb`

---

## Path B — Planner 5D → Blender (2–4 hours, draw your own layout)

1. [planner5d.com](https://planner5d.com) → draw walls room by room → export **OBJ**
2. Import OBJ into Blender → `P` → **Separate by Loose Parts**
3. Rename each mesh in Outliner to its `room_id`
4. Add **Decimate modifier** (ratio `0.1`) to reduce polygon count
5. Export → **glTF Binary (.glb)**

---

## Path C — iPhone LiDAR Scan (most accurate geometry)

Requires iPhone 12 Pro or later.

1. **Polycam** app → LiDAR mode → scan each room slowly (~60 sec/room)
2. Export as OBJ or GLB
3. Import into Blender, align rooms, name meshes
4. Apply heavy Decimate (ratio `0.05`) — LiDAR meshes are very dense
5. Export as `.glb`

---

## Quick Blender Cheatsheet

| Action | Shortcut |
|---|---|
| Orbit viewport | Middle mouse + drag |
| Pan viewport | Shift + middle mouse + drag |
| Top-down view | Numpad 7 |
| Select all | A |
| Enter edit mode | Tab |
| Face select mode | 3 |
| Select linked faces | L (hover over face) |
| Separate selection | P → Selection |
| Grab/move | G |
| Scale | S |
| Open side panel | N |
| Apply all transforms | Ctrl + A → All Transforms |

---

## Recommended Order

1. **Today**: Send the Revit brief to whoever is making the model. Give them
   the room list and ask them to use the Revit Room tool.

2. **While waiting**: Download a Sketchfab GLB as a placeholder so you can
   start building and testing the viewer immediately.

3. **When Revit model arrives**: Drop it into Blender, verify/fix room names,
   export as GLB, replace the placeholder. The viewer code doesn't change.
