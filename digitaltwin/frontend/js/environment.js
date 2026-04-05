// environment.js — Background presets, atmospheric sky, clouds, terrain
// Performance budget: clouds = single layer, 3-octave FBM, 160×160 plane.
// City = InstancedMesh (1 draw call). Terrain = 60 segs max.

import * as THREE from 'three';
import { Sky }    from 'three/addons/objects/Sky.js';

// ── Preset catalogue ──────────────────────────────────────────────────────────
export const PRESETS = {
  void: {
    label: 'Void',      icon: '⬛',
    skyAddon: false, clouds: false, terrain: null,        grid: true,
    ground: { color: 0x0a0c14, roughness: 1.0 },
    fixedSky: { bg: [0.039,0.047,0.078], fogC: [0.039,0.047,0.078], fogD: 0.022 },
  },
  studio: {
    label: 'Studio',    icon: '⬜',
    skyAddon: false, clouds: false, terrain: null,        grid: false,
    ground: { color: 0xf0f0f0, roughness: 0.85 },
    fixedSky: { bg: [0.97,0.97,0.97], fogC: [1,1,1], fogD: 0.004 },
  },
  plains: {
    label: 'Plains',    icon: '🌾',
    skyAddon: true,  clouds: true,  terrain: null,        grid: false,
    ground: { color: 0x5c7a40, roughness: 0.97 },
    sky: { turbidity: 1.5, rayleigh: 3.5, mie: 0.003, mieG: 0.75 },
    fixedSky: null,
  },
  mountains: {
    label: 'Mountains', icon: '🏔',
    skyAddon: true,  clouds: true,  terrain: 'mountains', grid: false,
    ground: { color: 0x5a6348, roughness: 0.98 },
    sky: { turbidity: 2.0, rayleigh: 3.0, mie: 0.004, mieG: 0.72 },
    fixedSky: null,
  },
  city: {
    label: 'City',      icon: '🏙',
    skyAddon: true,  clouds: false, terrain: 'city',      grid: false,
    ground: { color: 0x222228, roughness: 0.82 },
    sky: { turbidity: 6.0, rayleigh: 1.5, mie: 0.015, mieG: 0.65 },
    fixedSky: null,
  },
  desert: {
    label: 'Desert',    icon: '🏜',
    skyAddon: true,  clouds: false, terrain: 'dunes',     grid: false,
    ground: { color: 0xc4a252, roughness: 0.98 },
    sky: { turbidity: 8.0, rayleigh: 2.0, mie: 0.025, mieG: 0.60 },
    fixedSky: null,
  },
  snow: {
    label: 'Snow',      icon: '❄️',
    skyAddon: true,  clouds: true,  terrain: 'snow',      grid: false,
    ground: { color: 0xe8eef5, roughness: 1.0 },
    sky: { turbidity: 1.0, rayleigh: 4.0, mie: 0.002, mieG: 0.80 },
    fixedSky: null,
  },
  night: {
    label: 'Night',     icon: '🌃',
    skyAddon: false, clouds: false, terrain: 'city',      grid: false,
    ground: { color: 0x0d0d16, roughness: 0.85 },
    fixedSky: { bg: [0.008,0.008,0.020], fogC: [0.010,0.012,0.030], fogD: 0.018 },
  },
};

// ── Environment class ─────────────────────────────────────────────────────────
export class Environment {
  constructor(scene) {
    this.scene   = scene;
    this._ground = null;
    this._grid   = null;

    this._sky     = null;  // Sky addon instance (reused, never disposed)
    this._cloud   = null;  // single cloud mesh
    this._cloudU  = null;  // cloud uniforms ref
    this._terrain = null;  // terrain Group

    this._presetId = null;
    this._preset   = null;
    this._elapsed  = 0;
  }

  setGroundRefs(ground, grid) {
    this._ground = ground;
    this._grid   = grid;
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  setPreset(id) {
    if (id === this._presetId) return;
    const def = PRESETS[id];
    if (!def) return;
    this._presetId = id;
    this._preset   = def;
    this._apply(def);
  }

  getPresetId() { return this._presetId; }

  getSkyOverride() {
    return this._preset?.fixedSky ?? null;
  }

  // Called every frame by viewer._animate()
  update(delta, elevation, sunWorldPos, sunColor) {
    this._elapsed += delta;

    // Animate clouds
    if (this._cloudU) {
      this._cloudU.uTime.value    = this._elapsed;
      this._cloudU.uOpacity.value = Math.max(0, Math.min(0.7, elevation * 2.8 + 0.08));
      this._cloudU.uSunColor.value.copy(sunColor).clampScalar(0, 1);
    }

    // Update sky shader sun direction
    if (this._sky) {
      this._sky.material.uniforms['sunPosition'].value
        .copy(sunWorldPos).normalize();
    }
  }

  // ── Apply ──────────────────────────────────────────────────────────────────
  _apply(def) {
    // Ground
    if (this._ground?.material) {
      this._ground.material.color.setHex(def.ground.color);
      this._ground.material.roughness = def.ground.roughness;
    }

    // Grid
    if (this._grid) this._grid.visible = !!def.grid;

    // Sky addon — single instance, just update params
    if (def.skyAddon && def.sky) {
      if (!this._sky) {
        this._sky = new Sky();
        // Use camera far/2 so the sphere is definitely inside the frustum
        // but also fills the entire background
        this._sky.scale.setScalar(180);
      }
      const u = this._sky.material.uniforms;
      u['turbidity'].value       = def.sky.turbidity;
      u['rayleigh'].value        = def.sky.rayleigh;
      u['mieCoefficient'].value  = def.sky.mie;
      u['mieDirectionalG'].value = def.sky.mieG;
      if (!this._sky.parent) this.scene.add(this._sky);
    } else {
      if (this._sky?.parent) this.scene.remove(this._sky);
    }

    // Clouds — remove old, build new if needed
    this._removeCloud();
    if (def.clouds) this._buildCloud();

    // Terrain — clear old, build new
    this._clearTerrain();
    if (def.terrain) this._buildTerrain(def.terrain, def);
  }

  // ── Cloud — single layer, 3-octave FBM, 160×160 plane ────────────────────
  _buildCloud() {
    // Very small plane in geometry units (1×1), scaled up in world space.
    // Keeps UV coordinates clean and avoids fat vertex buffers.
    const geo = new THREE.PlaneGeometry(1, 1, 1, 1);
    geo.rotateX(-Math.PI / 2);

    this._cloudU = {
      uTime:     { value: this._elapsed },
      uOpacity:  { value: 0.5 },
      uSunColor: { value: new THREE.Color(1, 1, 1) },
    };

    const mat = new THREE.ShaderMaterial({
      uniforms:       this._cloudU,
      vertexShader:   CLOUD_VERT,
      fragmentShader: CLOUD_FRAG,
      transparent:    true,
      depthWrite:     false,
      side:           THREE.FrontSide,
    });

    this._cloud = new THREE.Mesh(geo, mat);
    // Scale the plane large in world space — cheaper than large geometry
    this._cloud.scale.set(160, 1, 160);
    this._cloud.position.y = 20;
    this._cloud.renderOrder = -1;
    this.scene.add(this._cloud);
  }

  _removeCloud() {
    if (!this._cloud) return;
    this.scene.remove(this._cloud);
    this._cloud.geometry.dispose();
    this._cloud.material.dispose();
    this._cloud  = null;
    this._cloudU = null;
  }

  // ── Terrain ────────────────────────────────────────────────────────────────
  _buildTerrain(type, def) {
    const group = new THREE.Group();

    // ── Mountains ────────────────────────────────────────────────────────────
    // 60 segs = 3,721 vertices (vs 140 segs = 19,881). Fast to build, low GPU.
    if (type === 'mountains' || type === 'snow') {
      const segs = 60;
      const geo  = new THREE.PlaneGeometry(280, 280, segs, segs);
      geo.rotateX(-Math.PI / 2);
      const pos = geo.attributes.position;

      const isSnow = type === 'snow';
      const colors = isSnow ? [] : null;
      const snowCol = new THREE.Color(0xdde8f5);
      const rockCol = new THREE.Color(0x7a8878);
      const baseCol = new THREE.Color(isSnow ? 0x9ab0c0 : 0x5e6d50);

      for (let i = 0; i < pos.count; i++) {
        const x = pos.getX(i), z = pos.getZ(i);
        const r = Math.sqrt(x * x + z * z);
        let h = 0;
        if (r > 48) {
          const a = Math.atan2(z, x);
          const t = Math.min((r - 48) / 65, 1) ** 1.6;
          h = Math.max(0, t * (
            14 * Math.sin(a * 3.0 + 0.8) +
             9 * Math.sin(a * 7.1 + 1.4) +
             5 * Math.sin(a * 12  + 2.1) +
             2 * Math.sin(a * 19  + 0.5)
          ));
        }
        pos.setY(i, h);

        if (isSnow) {
          const blend = Math.max(0, Math.min(1, (h - 4) / 7));
          const c = baseCol.clone().lerp(blend > 0.5 ? snowCol : rockCol, blend);
          colors.push(c.r, c.g, c.b);
        }
      }
      geo.computeVertexNormals();

      const mat = new THREE.MeshStandardMaterial({
        color:        isSnow ? 0x9ab0c0 : 0x5e6d50,
        roughness:    0.96,
        vertexColors: isSnow,
      });
      if (isSnow) geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

      group.add(new THREE.Mesh(geo, mat));
    }

    // ── City — InstancedMesh: 1 draw call instead of 140 ─────────────────────
    if (type === 'city') {
      const count   = 140;
      const boxGeo  = new THREE.BoxGeometry(1, 1, 1);
      const mat     = new THREE.MeshStandardMaterial({
        color: 0x1c1c28, roughness: 0.65, metalness: 0.35,
      });
      const instanced = new THREE.InstancedMesh(boxGeo, mat, count);
      instanced.castShadow    = true;
      instanced.receiveShadow = false;

      const dummy  = new THREE.Object3D();
      // Seed random with a fixed sequence so it's deterministic
      let seed = 42;
      const rng = () => { seed = (seed * 1664525 + 1013904223) & 0xffffffff; return (seed >>> 0) / 0xffffffff; };

      for (let i = 0; i < count; i++) {
        const a = (i / count) * Math.PI * 2 + (rng() - 0.5) * 0.12;
        const r = 52 + rng() * 28;
        const h = 2 + Math.pow(rng(), 0.4) * 26;
        const w = 1.8 + rng() * 4.5;
        const d = 1.8 + rng() * 4.5;
        dummy.position.set(Math.cos(a) * r, h / 2, Math.sin(a) * r);
        dummy.rotation.y = a + (rng() - 0.5) * 0.5;
        dummy.scale.set(w, h, d);
        dummy.updateMatrix();
        instanced.setMatrixAt(i, dummy.matrix);
      }
      instanced.instanceMatrix.needsUpdate = true;
      group.add(instanced);
    }

    // ── Desert dunes — 50 segs ───────────────────────────────────────────────
    if (type === 'dunes') {
      const segs = 50;
      const geo  = new THREE.PlaneGeometry(260, 260, segs, segs);
      geo.rotateX(-Math.PI / 2);
      const pos = geo.attributes.position;
      for (let i = 0; i < pos.count; i++) {
        const x = pos.getX(i), z = pos.getZ(i);
        const r = Math.sqrt(x * x + z * z);
        if (r > 40) {
          const a = Math.atan2(z, x);
          const t = Math.min((r - 40) / 50, 1);
          const h = Math.max(0, t * t * (
            6 * Math.sin(a * 2.5 + 1.0) +
            4 * Math.sin(a * 5.0 + 2.0) +
            2 * Math.sin(a * 9.0 + 0.5)
          ));
          pos.setY(i, h);
        }
      }
      geo.computeVertexNormals();
      group.add(new THREE.Mesh(geo,
        new THREE.MeshStandardMaterial({ color: 0xbe9a48, roughness: 0.98 })
      ));
    }

    this.scene.add(group);
    this._terrain = group;
  }

  _clearTerrain() {
    if (!this._terrain) return;
    this.scene.remove(this._terrain);
    this._terrain.traverse(n => {
      n.geometry?.dispose();
      if (n.material) {
        (Array.isArray(n.material) ? n.material : [n.material])
          .forEach(m => m.dispose());
      }
    });
    this._terrain = null;
  }
}

// ── Cloud shaders ─────────────────────────────────────────────────────────────
// 3-octave FBM only — ~half the GPU cost of 6 octaves.
// No matrix rotation between octaves (simple offset instead = cheaper).
// No second fbm2 call.

const CLOUD_VERT = /* glsl */`
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const CLOUD_FRAG = /* glsl */`
  uniform float uTime;
  uniform float uOpacity;
  uniform vec3  uSunColor;
  varying vec2  vUv;

  // Fast 2D value noise — no smooth lerp to keep cost down
  float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
  }

  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(hash(i),              hash(i + vec2(1,0)), u.x),
      mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), u.x), u.y);
  }

  // 3-octave FBM — good visual quality, low cost
  float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 3; i++) {
      v += a * noise(p);
      p  = p * 2.1 + vec2(5.3 * float(i) + 1.7, 9.2 + 3.1 * float(i));
      a *= 0.5;
    }
    return v;
  }

  void main() {
    // Drift east→west
    vec2 uv = (vUv - 0.5) * 3.2;
    uv.x += uTime * 0.012;
    uv.y += uTime * 0.004;

    float cloud = fbm(uv);
    cloud = smoothstep(0.45, 0.68, cloud);

    // Circular fade so the plane doesn't have a hard edge
    float dist = length(vUv - 0.5) * 2.0;
    float fade = 1.0 - smoothstep(0.72, 1.0, dist);

    // Tint with sun color at sunrise/sunset
    vec3 col = mix(vec3(0.96, 0.97, 1.0), uSunColor * 1.3, 0.20);
    col = max(col, vec3(0.82));

    gl_FragColor = vec4(col, cloud * fade * uOpacity);
  }
`;
