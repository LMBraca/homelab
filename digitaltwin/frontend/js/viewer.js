// viewer.js — Three.js scene, procedural rooms, device markers, dynamic lighting

import * as THREE from 'three';
import { OrbitControls }              from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader }                 from 'three/addons/loaders/GLTFLoader.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { ROOMS, ROOM_LAYOUT, FLOOR_Y, WALL_HEIGHT, FLOOR_SLAB, WALL_THICK } from './rooms.js';

// ── Constants ─────────────────────────────────────────────────────────────────
const C = {
  bg:          0x0a0c14,
  ground:      0x0d1018,
  gridPrimary: 0x151926,
  roomHover:   0xfbbf24,
  roomSelect:  0x6366f1,
  wallAlpha:   0.18,
  dimOpacity:  0.08,
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function _meshNameToRoomId(rawName) {
  return rawName
    .toLowerCase()
    .replace(/^floor\d+[-_\s]*/,  '')
    .replace(/[-\s]+/g,           '_')
    .replace(/[^a-z0-9_]/g,       '')
    .replace(/_+/g,               '_')
    .replace(/^_+|_+$/g,          '');
}

function _deviceColor(device) {
  const s  = device.live?.state;
  const dc = device.live?.device_class;
  if (device.domain === 'light') {
    if (s !== 'on') return 0x2a2d3a;
    const t = (device.live?.brightness_pct ?? 80) / 100;
    const r = Math.round(0xb0 + t * (0xfd - 0xb0));
    const g = Math.round(0x80 + t * (0xe6 - 0x80));
    const b = Math.round(0x10 + t * (0x8a - 0x10));
    return (r << 16) | (g << 8) | b;
  }
  switch (device.domain) {
    case 'binary_sensor':
      if (dc === 'door')   return s === 'on' ? 0xef4444 : 0x22c55e;
      if (dc === 'motion') return s === 'on' ? 0x818cf8 : 0x1a1d2b;
      return 0x374151;
    case 'lock':    return s === 'locked' ? 0x22c55e : 0xf59e0b;
    case 'sensor':  return 0x06b6d4;
    default:        return 0x374151;
  }
}

function _deviceEmissive(device) {
  const s  = device.live?.state;
  const dc = device.live?.device_class;
  if (device.domain === 'light') {
    if (s !== 'on') return { hex: 0x000000, intensity: 0 };
    const t = (device.live?.brightness_pct ?? 80) / 100;
    return { hex: 0xfde68a, intensity: 0.15 + t * 0.75 };
  }
  switch (device.domain) {
    case 'binary_sensor':
      if (dc === 'motion' && s === 'on') return { hex: 0x6366f1, intensity: 0.6 };
      if (dc === 'door'   && s === 'on') return { hex: 0xef4444, intensity: 0.4 };
      if (dc === 'door'   && s !== 'on') return { hex: 0x22c55e, intensity: 0.15 };
      return { hex: 0x000000, intensity: 0 };
    case 'lock':
      return s === 'unlocked' ? { hex: 0xf59e0b, intensity: 0.5 } : { hex: 0x22c55e, intensity: 0.2 };
    case 'sensor':
      return { hex: 0x06b6d4, intensity: 0.25 };
    default:
      return { hex: 0x000000, intensity: 0 };
  }
}

function _stateLabel(device) {
  const s  = device.live?.state ?? '—';
  const bv = device.live?.brightness_pct;
  if (device.domain === 'light' && s === 'on' && bv != null) return `on · ${bv}%`;
  if (device.domain === 'sensor') return `${s}${device.live?.unit ?? ''}`;
  return s;
}

// ── Viewer ────────────────────────────────────────────────────────────────────
export class Viewer {
  constructor(canvasEl, labelsEl) {
    this.canvasEl  = canvasEl;
    this.labelsEl  = labelsEl;

    this.roomMeshes    = new Map();
    this.roomGroups    = new Map();
    this.floorGroups   = new Map();
    this.hitTargets    = [];

    this.deviceMarkers = new Map();
    this.deviceSpheres = [];

    this._pulseTime       = 0;
    this._pulsingEntities = new Set();

    this.hoveredRoomId = null;
    this.hoveredEntity = null;
    this.selectedId    = null;
    this.mouse         = new THREE.Vector2(-9, -9);
    this._tween        = null;
    this._usingGLB     = false;

    this._activeFloor  = 0;
    this._roomFloorMap = new Map();

    this._sunElevation = 0;

    // ── Tap detection state ─────────────────────────────────────────────────
    // On mobile, click fires AFTER pointerleave (which resets mouse to -9,-9).
    // We instead use pointerdown/pointerup with explicit movement threshold.
    // _tapDown: recorded position/time at pointerdown (null when no touch)
    // _hasDragged: set to true when pointer moves >8px from down position
    // _isTouching: true while a pointer is actively on screen (suppresses hover)
    this._tapDown    = null;
    this._hasDragged = false;
    this._isTouching = false;

    this.onRoomClick   = null;
    this.onRoomHover   = null;
    this.onDeviceClick = null;
    this.onDeviceHover = null;
    this.onModelLoaded = null;

    this._initScene();
    this._initLights();
    this._initControls();
    this._initRaycaster();
    this._initResizeObserver();
    this._initPointerListeners();
    this._tryLoadGLB();
    this._animate();
  }

  // ── Scene ──────────────────────────────────────────────────────────────────
  _initScene() {
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(C.bg);
    this.scene.fog = new THREE.FogExp2(C.bg, 0.018);

    const w = this.canvasEl.parentElement.clientWidth;
    const h = this.canvasEl.parentElement.clientHeight;

    this.camera = new THREE.PerspectiveCamera(48, w / h, 0.1, 200);
    this.camera.position.set(0, 14, 18);

    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvasEl, antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type    = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping       = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;

    this.labelRenderer = new CSS2DRenderer({ element: this.labelsEl });
    this.labelRenderer.setSize(w, h);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(80, 80),
      new THREE.MeshStandardMaterial({ color: C.ground, roughness: 1 })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.02;
    ground.receiveShadow = true;
    this.scene.add(ground);
    this._ground = ground;

    this._grid = new THREE.GridHelper(60, 60, C.gridPrimary, C.gridPrimary);
    this.scene.add(this._grid);
  }

  _initLights() {
    this.ambient = new THREE.AmbientLight(0xffffff, 0.35);
    this.scene.add(this.ambient);

    this.sun = new THREE.DirectionalLight(0xfff5e0, 1.2);
    this.sun.position.set(10, 18, 12);
    this.sun.castShadow = true;
    Object.assign(this.sun.shadow.mapSize, { width: 2048, height: 2048 });
    Object.assign(this.sun.shadow.camera,  { near: 0.5, far: 80, left: -24, right: 24, top: 24, bottom: -24 });
    this.scene.add(this.sun);
    this.scene.add(this.sun.target);

    this.fill = new THREE.DirectionalLight(0x6688cc, 0.25);
    this.fill.position.set(-8, 10, -8);
    this.scene.add(this.fill);

    this.moon = new THREE.DirectionalLight(0x334466, 0.0);
    this.moon.position.set(-10, 12, -6);
    this.scene.add(this.moon);

    this.setSunTime(12);
  }

  _initControls() {
    this.controls = new OrbitControls(this.camera, this.labelsEl);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.minDistance   = 3;
    this.controls.maxDistance   = 40;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.04;
    this.controls.target.set(0, 1.2, 0);
    this.controls.update();
  }

  _initRaycaster() {
    this.raycaster = new THREE.Raycaster();
  }

  _initResizeObserver() {
    new ResizeObserver(() => this._resize()).observe(this.canvasEl.parentElement);
  }

  // ── Pointer listeners ──────────────────────────────────────────────────────
  // We do NOT use the 'click' event because on touch devices:
  //   - 'pointerleave' fires before 'click' when lifting a finger,
  //     resetting this.mouse to (-9,-9) so the pick always misses.
  //   - 'click' fires even after a drag (rotation), selecting rooms
  //     unintentionally.
  //
  // Instead: pointerdown records the tap start position; pointerup checks
  // whether movement stayed under 8px and time under 400ms — if so, it's a
  // tap and we pick using the DOWN position (unaffected by subsequent events).
  _initPointerListeners() {
    const el = this.labelsEl;

    // Track mouse position for desktop hover
    el.addEventListener('pointermove', e => {
      const r = el.getBoundingClientRect();
      this.mouse.set(
         ((e.clientX - r.left) / r.width)  * 2 - 1,
        -((e.clientY - r.top)  / r.height) * 2 + 1
      );
      // Detect drag: if pointer moved >8px from down, it's a drag not a tap
      if (this._tapDown) {
        const dx = e.clientX - this._tapDown.x;
        const dy = e.clientY - this._tapDown.y;
        if (Math.hypot(dx, dy) > 8) this._hasDragged = true;
      }
    });

    el.addEventListener('pointerdown', e => {
      const r  = el.getBoundingClientRect();
      const mx = ((e.clientX - r.left) / r.width)  * 2 - 1;
      const my = -((e.clientY - r.top)  / r.height) * 2 + 1;

      // Update mouse immediately so hover state is current
      this.mouse.set(mx, my);

      // Record tap start
      this._tapDown    = { x: e.clientX, y: e.clientY, t: Date.now(), mx, my };
      this._hasDragged = false;
      this._isTouching = e.pointerType === 'touch' || e.pointerType === 'pen';
    });

    el.addEventListener('pointerup', e => {
      if (!this._tapDown) return;

      const dx   = e.clientX - this._tapDown.x;
      const dy   = e.clientY - this._tapDown.y;
      const dist = Math.hypot(dx, dy);
      const dt   = Date.now() - this._tapDown.t;

      // Tap = moved <8px AND held <400ms AND didn't drag during pointermove
      const isTap = dist < 8 && dt < 400 && !this._hasDragged;

      if (isTap) {
        // Always pick at the pointerDOWN position — it's the intentional target.
        // The mouse may have been reset by pointerleave before this fires on touch.
        this.mouse.set(this._tapDown.mx, this._tapDown.my);
        const result = this._pick();

        if      (result?.type === 'device') this.onDeviceClick?.(result.entityId);
        else if (result?.type === 'room')   this.onRoomClick?.(result.roomId);
        else                                this.onRoomClick?.(null);
      }

      this._tapDown    = null;
      this._isTouching = false;
    });

    // Only reset mouse on non-touch leave — on touch, finger lift fires
    // pointerleave then pointerup, so we must NOT reset here for touch
    el.addEventListener('pointerleave', e => {
      if (e.pointerType !== 'touch' && e.pointerType !== 'pen') {
        this.mouse.set(-9, -9);
      }
    });

    el.addEventListener('pointercancel', () => {
      this._tapDown    = null;
      this._hasDragged = false;
      this._isTouching = false;
    });
  }

  // ── GLB ────────────────────────────────────────────────────────────────────
  _tryLoadGLB() {
    new GLTFLoader().load(
      '/public/models/house.glb',
      gltf  => this._onGLBLoaded(gltf),
      undefined,
      _err  => this._buildProceduralRooms()
    );
  }

  _onGLBLoaded(gltf) {
    this._usingGLB = true;
    const model = gltf.scene;

    const box   = new THREE.Box3().setFromObject(model);
    const size  = box.getSize(new THREE.Vector3());
    const scale = 14 / Math.max(size.x, size.z);
    model.scale.setScalar(scale);
    const box2 = new THREE.Box3().setFromObject(model);
    const ctr2 = box2.getCenter(new THREE.Vector3());
    model.position.sub(ctr2);
    const box3 = new THREE.Box3().setFromObject(model);
    model.position.y -= box3.min.y;
    this.scene.add(model);

    model.traverse(node => {
      if (!node.isMesh || !node.name) return;
      const roomId = _meshNameToRoomId(node.name);
      if (!roomId) return;
      node.userData.roomId = roomId;
      node.castShadow = node.receiveShadow = true;
      if (Array.isArray(node.material)) {
        node.material = node.material.map(m => { const c = m.clone(); c.transparent = true; c.opacity = 1; return c; });
      } else if (node.material) {
        node.material = node.material.clone();
        node.material.transparent = true;
        node.material.opacity = 1;
      }
      if (!this.roomMeshes.has(roomId)) this.roomMeshes.set(roomId, []);
      this.roomMeshes.get(roomId).push(node);
      this.hitTargets.push(node);
    });

    for (const [roomId, meshes] of this.roomMeshes) {
      const rBox = new THREE.Box3();
      for (const m of meshes) rBox.expandByObject(m);
      const top  = rBox.getCenter(new THREE.Vector3());
      top.y = rBox.max.y + 0.4;
      const pretty = roomId.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
      const div = document.createElement('div');
      div.className  = 'room-label';
      div.dataset.id = roomId;
      div.innerHTML  = `<span class="rl-name" id="rl-name-${roomId}">${pretty}</span><span class="rl-count" id="rl-count-${roomId}">0</span>`;
      const obj = new CSS2DObject(div);
      obj.position.copy(top);
      this.scene.add(obj);
    }

    this._updateStatus(`Model loaded ✓ — ${this.roomMeshes.size} rooms`);
    this.onModelLoaded?.();
  }

  // ── Procedural rooms ───────────────────────────────────────────────────────
  _buildProceduralRooms() {
    this._usingGLB = false;
    this._updateStatus('Procedural layout — drop house.glb to use real model');

    const f1 = new THREE.Group(); this.floorGroups.set(1, f1);
    const f2 = new THREE.Group(); this.floorGroups.set(2, f2);
    this.scene.add(f1, f2);

    for (const room of ROOMS) {
      const layout = ROOM_LAYOUT[room.id];
      if (!layout) continue;

      const floorY = FLOOR_Y[room.floor];
      const col    = new THREE.Color(room.color);
      const group  = new THREE.Group();
      group.name   = room.id;
      group.position.set(layout.cx, floorY, layout.cz);
      const meshes = [];

      const floorMesh = new THREE.Mesh(
        new THREE.BoxGeometry(layout.w, FLOOR_SLAB, layout.d),
        new THREE.MeshStandardMaterial({ color: col, roughness: 0.65, metalness: 0.08, transparent: true, opacity: 1.0 })
      );
      floorMesh.position.y = FLOOR_SLAB / 2;
      floorMesh.castShadow = floorMesh.receiveShadow = true;
      floorMesh.userData.roomId  = room.id;
      floorMesh.userData.isFloor = true;
      group.add(floorMesh);
      meshes.push(floorMesh);
      this.hitTargets.push(floorMesh);

      const wallY = FLOOR_SLAB + WALL_HEIGHT / 2;
      for (const [sx, sy, sz, px, py, pz] of [
        [layout.w, WALL_HEIGHT, WALL_THICK,  0,            wallY, -layout.d / 2],
        [layout.w, WALL_HEIGHT, WALL_THICK,  0,            wallY,  layout.d / 2],
        [WALL_THICK, WALL_HEIGHT, layout.d, -layout.w / 2, wallY,  0           ],
        [WALL_THICK, WALL_HEIGHT, layout.d,  layout.w / 2, wallY,  0           ],
      ]) {
        const wall = new THREE.Mesh(
          new THREE.BoxGeometry(sx, sy, sz),
          new THREE.MeshStandardMaterial({ color: col, transparent: true, opacity: C.wallAlpha, roughness: 0.5, side: THREE.DoubleSide, depthWrite: false })
        );
        wall.position.set(px, py, pz);
        wall.userData.roomId = room.id;
        group.add(wall);
        meshes.push(wall);
        this.hitTargets.push(wall);
      }

      if (room.floor === 2) {
        const badge = document.createElement('div');
        badge.className = 'floor-badge';
        badge.textContent = 'F2';
        const obj = new CSS2DObject(badge);
        obj.position.set(layout.w / 2 - 0.3, FLOOR_SLAB + 0.1, -layout.d / 2 + 0.3);
        group.add(obj);
      }

      const div = document.createElement('div');
      div.className  = 'room-label';
      div.dataset.id = room.id;
      div.innerHTML  = `<span class="rl-name" id="rl-name-${room.id}">${room.name}</span><span class="rl-count" id="rl-count-${room.id}">${room.devices}</span>`;
      const labelObj = new CSS2DObject(div);
      labelObj.position.set(0, WALL_HEIGHT + FLOOR_SLAB + 0.6, 0);
      group.add(labelObj);

      this.roomMeshes.set(room.id, meshes);
      this.roomGroups.set(room.id, group);
      this.floorGroups.get(room.floor).add(group);
    }

    this.onModelLoaded?.();
  }

  // ── Room bounds ────────────────────────────────────────────────────────────
  getRoomBounds(roomId) {
    if (this._usingGLB) {
      const meshes = this.roomMeshes.get(roomId);
      if (!meshes?.length) return null;
      const box = new THREE.Box3();
      for (const m of meshes) box.expandByObject(m);
      const size = box.getSize(new THREE.Vector3());
      const ctr  = box.getCenter(new THREE.Vector3());
      return { cx: ctr.x, cy: box.min.y, cz: ctr.z, w: size.x, d: size.z, h: Math.min(size.y, WALL_HEIGHT + 0.5) };
    }
    const layout = ROOM_LAYOUT[roomId];
    if (!layout) return null;
    const floor = this._roomFloorMap.get(roomId) ?? 1;
    const cy    = FLOOR_Y[floor] ?? 0;
    return { cx: layout.cx, cy, cz: layout.cz, w: layout.w, d: layout.d, h: WALL_HEIGHT };
  }

  // ── Device markers ─────────────────────────────────────────────────────────
  placeDeviceMarkers(devices, rooms) {
    this.clearDeviceMarkers();
    for (const [, device] of devices) {
      if (!device.position_3d || !device.room_id) continue;
      const bounds = this.getRoomBounds(device.room_id);
      if (!bounds) continue;
      const room  = rooms.get(device.room_id);
      const floor = room?.floor ?? this._roomFloorMap.get(device.room_id) ?? 1;
      const pos = new THREE.Vector3(
        bounds.cx + device.position_3d.x,
        bounds.cy + device.position_3d.y,
        bounds.cz + device.position_3d.z
      );
      this._createMarker(device, pos, floor);
    }
  }

  _createMarker(device, worldPos, floor = 1) {
    const emissive = _deviceEmissive(device);
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(0.14, 14, 10),
      new THREE.MeshStandardMaterial({
        color:             _deviceColor(device),
        emissive:          new THREE.Color(emissive.hex),
        emissiveIntensity: emissive.intensity,
        roughness: 0.3,
        metalness: 0.4,
      })
    );
    sphere.position.copy(worldPos);
    sphere.userData.entityId = device.entity_id;
    sphere.userData.type     = 'device';
    sphere.userData.floor    = floor;
    this.scene.add(sphere);

    const divEl = document.createElement('div');
    divEl.className = 'device-tooltip';
    divEl.innerHTML = `<span class="dt-name">${device.name}</span><span class="dt-state">${_stateLabel(device)}</span>`;
    const labelObj = new CSS2DObject(divEl);
    labelObj.position.set(0, 0.3, 0);
    sphere.add(labelObj);

    let pointLight = null;
    if (device.domain === 'light') {
      const isOn = device.live?.state === 'on';
      const bPct = device.live?.brightness_pct ?? 80;
      pointLight = new THREE.PointLight(0xffdd88, isOn ? _bulbIntensity(bPct) : 0, 18, 1.2);
      pointLight.position.copy(worldPos);
      this.scene.add(pointLight);
    }

    this.deviceMarkers.set(device.entity_id, { sphere, labelObj, divEl, pointLight, floor });
    this.deviceSpheres.push(sphere);

    if (device.domain === 'binary_sensor'
     && device.live?.device_class === 'motion'
     && device.live?.state === 'on') {
      this._pulsingEntities.add(device.entity_id);
    }
  }

  refreshDeviceMarkers(devices) {
    for (const [, device] of devices) {
      const marker = this.deviceMarkers.get(device.entity_id);
      if (!marker) continue;

      const emissive = _deviceEmissive(device);
      marker.sphere.material.color.setHex(_deviceColor(device));
      marker.sphere.material.emissive.setHex(emissive.hex);
      marker.sphere.material.emissiveIntensity = emissive.intensity;

      const stateEl = marker.divEl.querySelector('.dt-state');
      if (stateEl) stateEl.textContent = _stateLabel(device);

      if (marker.pointLight) {
        const isOn = device.live?.state === 'on';
        const bPct = device.live?.brightness_pct ?? 80;
        marker.pointLight.intensity = isOn ? _bulbIntensity(bPct) : 0;
      }

      const shouldPulse = device.domain === 'binary_sensor'
        && device.live?.device_class === 'motion'
        && device.live?.state === 'on';
      if (shouldPulse) this._pulsingEntities.add(device.entity_id);
      else             this._pulsingEntities.delete(device.entity_id);
    }
  }

  moveDeviceMarker(entityId, worldPos) {
    const marker = this.deviceMarkers.get(entityId);
    if (!marker) return;
    marker.sphere.position.copy(worldPos);
    if (marker.pointLight) marker.pointLight.position.copy(worldPos);
  }

  clearDeviceMarkers() {
    for (const { sphere, pointLight } of this.deviceMarkers.values()) {
      this.scene.remove(sphere);
      if (pointLight) this.scene.remove(pointLight);
    }
    this.deviceMarkers.clear();
    this.deviceSpheres.length = 0;
    this._pulsingEntities.clear();
  }

  // ── Floor filter ───────────────────────────────────────────────────────────
  setFloor(floor) {
    this._activeFloor = floor;
    this.floorGroups.forEach((grp, f) => { grp.visible = (floor === 0 || f === floor); });
    if (this._usingGLB) {
      for (const [roomId, meshes] of this.roomMeshes) {
        const roomFloor = this._roomFloorMap.get(roomId) ?? 1;
        const show      = floor === 0 || roomFloor === floor;
        for (const m of meshes) m.visible = show;
        const labelEl = document.querySelector(`.room-label[data-id="${roomId}"]`);
        if (labelEl) labelEl.style.visibility = show ? '' : 'hidden';
      }
    }
    for (const { sphere, pointLight, floor: devFloor } of this.deviceMarkers.values()) {
      const show = floor === 0 || devFloor === floor;
      sphere.visible = show;
      if (pointLight) pointLight.visible = show;
    }
  }

  // ── Room dimming ───────────────────────────────────────────────────────────
  _dimOtherRooms(selectedRoomId) {
    for (const [roomId, meshes] of this.roomMeshes) {
      const isDim = !!selectedRoomId && roomId !== selectedRoomId;
      for (const m of meshes) {
        const mats = Array.isArray(m.material) ? m.material : [m.material];
        for (const mat of mats) {
          if (!mat) continue;
          mat.transparent = true;
          if (m.userData.isFloor || this._usingGLB) mat.opacity = isDim ? C.dimOpacity : 1.0;
          else mat.opacity = isDim ? 0.03 : C.wallAlpha;
        }
      }
    }
  }

  // ── Room highlight ─────────────────────────────────────────────────────────
  _setRoomHighlight(roomId, mode) {
    const meshes = this.roomMeshes.get(roomId);
    if (!meshes) return;
    const { hex, intensity } = {
      none:     { hex: 0x000000, intensity: 0    },
      hover:    { hex: C.roomHover,  intensity: 0.28 },
      selected: { hex: C.roomSelect, intensity: 0.45 },
    }[mode] ?? { hex: 0x000000, intensity: 0 };
    for (const m of meshes) {
      const mats = Array.isArray(m.material) ? m.material : [m.material];
      for (const mat of mats) {
        if (mat?.emissive) { mat.emissive.setHex(hex); mat.emissiveIntensity = intensity; }
      }
    }
    const labelEl = document.querySelector(`.room-label[data-id="${roomId}"]`);
    if (labelEl) {
      labelEl.classList.toggle('hover',    mode === 'hover');
      labelEl.classList.toggle('selected', mode === 'selected');
    }
  }

  _showDeviceTooltip(entityId, visible) {
    this.deviceMarkers.get(entityId)?.divEl.classList.toggle('visible', visible);
  }

  // ── Public select ──────────────────────────────────────────────────────────
  selectRoom(roomId) {
    if (this.selectedId) this._setRoomHighlight(this.selectedId, 'none');
    const isNew = roomId !== this.selectedId;
    this.selectedId = roomId;
    if (roomId) {
      this._setRoomHighlight(roomId, 'selected');
      if (isNew) this._zoomTo(roomId);
    }
    this._dimOtherRooms(roomId);
  }

  frameSelected() { if (this.selectedId) this._zoomTo(this.selectedId); }

  resetCamera() {
    this._tween = {
      fromPos:    this.camera.position.clone(),
      fromTarget: this.controls.target.clone(),
      toPos:      new THREE.Vector3(0, 14, 18),
      toTarget:   new THREE.Vector3(0, 1.2, 0),
      t: 0,
    };
  }

  // ── Camera tween ───────────────────────────────────────────────────────────
  _zoomTo(roomId) {
    const meshes = this.roomMeshes.get(roomId);
    if (!meshes?.length) return;
    const box = new THREE.Box3();
    for (const m of meshes) box.expandByObject(m);
    if (box.isEmpty()) return;
    const centre = box.getCenter(new THREE.Vector3());
    const size   = box.getSize(new THREE.Vector3());
    const dist   = Math.max(size.x, size.z) * 1.3 + 3;
    this._tween = {
      fromPos:    this.camera.position.clone(),
      fromTarget: this.controls.target.clone(),
      toPos:      centre.clone().add(new THREE.Vector3(0, dist * 0.65, dist * 0.85)),
      toTarget:   centre.clone(),
      t: 0,
    };
  }

  _stepTween() {
    if (!this._tween) return;
    this._tween.t = Math.min(this._tween.t + 0.035, 1);
    const t = _ease(this._tween.t);
    this.camera.position.lerpVectors(this._tween.fromPos, this._tween.toPos, t);
    this.controls.target.lerpVectors(this._tween.fromTarget, this._tween.toTarget, t);
    if (this._tween.t >= 1) this._tween = null;
  }

  // ── Raycasting ─────────────────────────────────────────────────────────────
  _pick() {
    this.raycaster.setFromCamera(this.mouse, this.camera);
    if (this.deviceSpheres.length) {
      const vis  = this.deviceSpheres.filter(s => s.visible);
      const hits = this.raycaster.intersectObjects(vis, false);
      if (hits.length) return { type: 'device', entityId: hits[0].object.userData.entityId };
    }
    const roomTargets = this._activeFloor === 0
      ? this.hitTargets
      : this.hitTargets.filter(m => (this._roomFloorMap.get(m.userData.roomId) ?? 1) === this._activeFloor);
    const hits = this.raycaster.intersectObjects(roomTargets, false);
    if (hits.length) return { type: 'room', roomId: hits[0].object.userData.roomId };
    return null;
  }

  // ── Hover tick ─────────────────────────────────────────────────────────────
  // Suppressed entirely while a touch pointer is active — hover has no meaning
  // on touch and causes confusing visual flicker during pan/rotate.
  _tickHover() {
    if (this._isTouching) return;

    const result = this._pick();

    const newDeviceHover = result?.type === 'device' ? result.entityId : null;
    if (newDeviceHover !== this.hoveredEntity) {
      if (this.hoveredEntity) this._showDeviceTooltip(this.hoveredEntity, false);
      this.hoveredEntity = newDeviceHover;
      if (newDeviceHover) this._showDeviceTooltip(newDeviceHover, true);
      this.onDeviceHover?.(newDeviceHover);
    }

    const newRoomHover = result?.type === 'room' ? result.roomId : null;
    if (newRoomHover !== this.hoveredRoomId) {
      if (this.hoveredRoomId && this.hoveredRoomId !== this.selectedId)
        this._setRoomHighlight(this.hoveredRoomId, 'none');
      this.hoveredRoomId = newRoomHover;
      if (newRoomHover && newRoomHover !== this.selectedId)
        this._setRoomHighlight(newRoomHover, 'hover');
      this.onRoomHover?.(newRoomHover);
    }

    this.labelsEl.style.cursor = result ? 'pointer' : 'default';
  }

  // ── Pulse (motion sensors) ─────────────────────────────────────────────────
  _tickPulse() {
    if (!this._pulsingEntities.size) return;
    this._pulseTime += 0.04;
    const factor = 0.5 + 0.5 * Math.sin(this._pulseTime * 3);
    for (const entityId of this._pulsingEntities) {
      const marker = this.deviceMarkers.get(entityId);
      if (marker) marker.sphere.material.emissiveIntensity = 0.3 + factor * 0.5;
    }
  }

  // ── Resize ─────────────────────────────────────────────────────────────────
  _resize() {
    const el = this.canvasEl.parentElement;
    const w  = el.clientWidth;
    const h  = el.clientHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.labelRenderer.setSize(w, h);
  }

  // ── Label helpers ──────────────────────────────────────────────────────────
  setRoomFloorMap(rooms) {
    this._roomFloorMap.clear();
    for (const [roomId, room] of rooms) this._roomFloorMap.set(roomId, room.floor ?? 1);
  }
  updateRoomLabelName(roomId, name)   { const el = document.getElementById(`rl-name-${roomId}`);  if (el) el.textContent = name;  }
  updateRoomLabelCount(roomId, count) { const el = document.getElementById(`rl-count-${roomId}`); if (el) el.textContent = count; }
  _updateStatus(msg) { const el = document.getElementById('status-msg'); if (el) el.textContent = msg; }

  // ── Day / Night ────────────────────────────────────────────────────────────
  setSunTime(hours) {
    const h24 = ((hours % 24) + 24) % 24;
    const { elevation: _el, azimuth, above } = _mexicaliSun(hours);
    const elevation = above ? Math.max(0, Math.sin(_el)) : 0;
    const horizon   = above ? Math.max(0, 1 - Math.abs(_el / (Math.PI / 4) - 1) * 3) : 0;

    const DIST = 20;
    const sunX =  Math.cos(_el) * Math.sin(azimuth) * DIST;
    const sunY =  Math.sin(_el) * DIST;
    const sunZ = -Math.cos(_el) * Math.cos(azimuth) * DIST;

    this.sun.position.set(above ? sunX : 0, above ? sunY : -10, above ? sunZ : -8);
    this.sun.target.position.set(0, 0, 0);
    this.sun.target.updateMatrixWorld();

    this._sunElevation = elevation;

    if (above && elevation > 0.01) {
      const g = Math.min(1, 0.68 + elevation * 0.29);
      const b = Math.min(1, 0.28 + elevation * 0.62);
      this.sun.color.setRGB(1.0, g, b);
    }

    this.sun.intensity         = above ? 0.12 + elevation * 1.28 + horizon * 0.2 : 0;
    this.ambient.intensity     = 0.04 + elevation * 0.40;
    this.ambient.color.setRGB(0.90 + elevation * 0.10, 0.92 + elevation * 0.08, 1.00);
    this.fill.intensity        = 0.05 + elevation * 0.20;
    this.fill.color.setHex(elevation > 0.1 ? 0x7799cc : 0x223355);
    this.moon.intensity        = above ? 0 : 0.06;

    const { bg, fogC, fogD } = _skyAt(h24);
    this.scene.background.setRGB(...bg);
    if (this.scene.fog) {
      this.scene.fog.color.setRGB(...fogC);
      this.scene.fog.density = fogD;
    }
  }

  // ── Render loop ────────────────────────────────────────────────────────────
  _animate() {
    requestAnimationFrame(() => this._animate());
    this._tickHover();
    this._stepTween();
    this._tickPulse();
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.labelRenderer.render(this.scene, this.camera);
  }
}

// ── Sky colour keyframes ──────────────────────────────────────────────────────
function _skyAt(h) {
  const K = [
    [  0,  0.018, 0.021, 0.045,  0.015, 0.018, 0.040,  0.030 ],
    [  4,  0.022, 0.026, 0.060,  0.018, 0.022, 0.055,  0.028 ],
    [  5,  0.058, 0.060, 0.095,  0.065, 0.068, 0.105,  0.025 ],
    [  6,  0.310, 0.195, 0.072,  0.350, 0.225, 0.090,  0.018 ],
    [  7,  0.420, 0.340, 0.120,  0.460, 0.380, 0.150,  0.013 ],
    [  8,  0.320, 0.470, 0.720,  0.400, 0.550, 0.800,  0.010 ],
    [ 10,  0.200, 0.420, 0.750,  0.280, 0.510, 0.840,  0.008 ],
    [ 12,  0.180, 0.400, 0.740,  0.260, 0.490, 0.830,  0.007 ],
    [ 15,  0.210, 0.420, 0.740,  0.290, 0.510, 0.830,  0.008 ],
    [ 17,  0.470, 0.340, 0.120,  0.530, 0.390, 0.150,  0.012 ],
    [ 18,  0.440, 0.185, 0.058,  0.500, 0.225, 0.078,  0.017 ],
    [ 19,  0.058, 0.068, 0.118,  0.052, 0.062, 0.108,  0.024 ],
    [ 20,  0.028, 0.033, 0.068,  0.024, 0.028, 0.060,  0.028 ],
    [ 24,  0.018, 0.021, 0.045,  0.015, 0.018, 0.040,  0.030 ],
  ];
  let lo = K[0], hi = K[K.length - 1];
  for (let i = 0; i < K.length - 1; i++) {
    if (h >= K[i][0] && h <= K[i + 1][0]) { lo = K[i]; hi = K[i + 1]; break; }
  }
  const t  = lo[0] === hi[0] ? 0 : (h - lo[0]) / (hi[0] - lo[0]);
  const lp = i => lo[i] + (hi[i] - lo[i]) * t;
  return { bg: [lp(1), lp(2), lp(3)], fogC: [lp(4), lp(5), lp(6)], fogD: lp(7) };
}

function _bulbIntensity(bPct) {
  return 0.8 + Math.max(0, Math.min(100, bPct)) / 100 * 5.2;
}

// ── Mexicali solar position ────────────────────────────────────────────────────
function _mexicaliSun(hours) {
  const LAT = 32.664 * Math.PI / 180;
  const LON = -115.468;
  const now   = new Date();
  const start = new Date(now.getFullYear(), 0, 0);
  const N     = Math.round((now - start) / 86400000);
  const B_rad = ((360 / 365) * (N - 81)) * Math.PI / 180;
  const dec   = Math.asin(Math.sin(23.45 * Math.PI / 180) * Math.sin(B_rad));
  const B_deg = (360 / 365) * (N - 81);
  const EoT   = 9.87 * Math.sin(2 * B_deg * Math.PI / 180)
              - 7.53 * Math.cos(    B_deg * Math.PI / 180)
              - 1.5  * Math.sin(    B_deg * Math.PI / 180);
  const month  = now.getMonth() + 1;
  const tzOff  = (month >= 4 && month <= 10) ? -7 : -8;
  const stdMer = tzOff * 15;
  const TC         = 4 * (LON - stdMer) + EoT;
  const solarHours = hours + TC / 60;
  const hourAngle  = (solarHours - 12) * 15 * Math.PI / 180;
  const sinEl    = Math.sin(LAT) * Math.sin(dec) + Math.cos(LAT) * Math.cos(dec) * Math.cos(hourAngle);
  const elevation = Math.asin(Math.max(-1, Math.min(1, sinEl)));
  const cosAz  = (Math.sin(dec) - Math.sin(elevation) * Math.sin(LAT))
               / (Math.cos(elevation) * Math.cos(LAT) + 1e-9);
  let azimuth  = Math.acos(Math.max(-1, Math.min(1, cosAz)));
  if (hourAngle > 0) azimuth = 2 * Math.PI - azimuth;
  return { elevation, azimuth, above: elevation > 0 };
}

function _ease(t) { return t * t * (3 - 2 * t); }
