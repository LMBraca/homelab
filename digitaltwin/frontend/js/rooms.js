// rooms.js — Room definitions and procedural layout data
// Phase 1: hardcoded to match seed.py exactly.
// Phase 2: this data will be fetched from GET /api/v1/rooms

export const ROOMS = [
  // Floor 1
  { id: 'living_room',       name: 'Living Room',       floor: 1, color: '#6366f1', devices: 3 },
  { id: 'kitchen',           name: 'Kitchen',           floor: 1, color: '#f59e0b', devices: 2 },
  { id: 'front_door',        name: 'Front Door',        floor: 1, color: '#22c55e', devices: 2 },
  { id: 'staircase',         name: 'Staircase',         floor: 1, color: '#94a3b8', devices: 2 },
  { id: 'estancia',          name: 'Estancia',          floor: 1, color: '#06b6d4', devices: 2 },
  { id: 'bathroom_1',        name: 'Bathroom 1',        floor: 1, color: '#3b82f6', devices: 2 },
  // Floor 2
  { id: 'bedroom_principal', name: 'Bedroom Principal', floor: 2, color: '#8b5cf6', devices: 2 },
  { id: 'bedroom_guest',     name: 'Bedroom Guest',     floor: 2, color: '#ec4899', devices: 2 },
  { id: 'bathroom_2',        name: 'Bathroom 2',        floor: 2, color: '#3b82f6', devices: 2 },
  { id: 'bathroom_3',        name: 'Bathroom 3',        floor: 2, color: '#3b82f6', devices: 2 },
];

// Procedural layout: center X/Z and width/depth for each room (meters)
// Replace with named GLB meshes when the Revit model arrives.
// X = east (+) / west (-), Z = south (+) / north (-)
export const ROOM_LAYOUT = {
  // ── Floor 1 ────────────────────────────────────────────────
  living_room:       { cx:  0,    cz:  0,    w: 5.5, d: 4.5 },
  kitchen:           { cx:  5,    cz: -0.5,  w: 4,   d: 3.5 },
  estancia:          { cx: -5.5,  cz:  0,    w: 4.5, d: 4.5 },
  bathroom_1:        { cx: -2,    cz:  4.5,  w: 2.5, d: 2.5 },
  staircase:         { cx:  0.5,  cz:  4.5,  w: 2,   d: 2.5 },
  front_door:        { cx:  4,    cz:  4.5,  w: 3,   d: 2   },
  // ── Floor 2 ────────────────────────────────────────────────
  bedroom_principal: { cx: -1.5,  cz:  0,    w: 5.5, d: 5   },
  bedroom_guest:     { cx:  4,    cz:  0.5,  w: 4,   d: 4.5 },
  bathroom_2:        { cx: -1.5,  cz: -4,    w: 3,   d: 2.5 },
  bathroom_3:        { cx:  4,    cz: -4,    w: 3,   d: 2.5 },
};

export const FLOOR_Y      = { 1: 0, 2: 4.0 };  // Y position of each floor's ground
export const WALL_HEIGHT  = 2.6;
export const FLOOR_SLAB   = 0.12;               // thickness of the floor slab
export const WALL_THICK   = 0.10;
