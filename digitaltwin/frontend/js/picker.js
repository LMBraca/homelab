// picker.js — 2D floor plan position picker modal
// Replaces imprecise 3D click placement with a top-down drag + height slider.
// Model-agnostic: receives room bounds as a plain {cx,cy,cz,w,d,h} object.

import { WALL_HEIGHT } from './rooms.js';

const CANVAS_W = 310;
const CANVAS_H = 220;
const PAD      = 24;   // px padding inside canvas

export class PositionPicker {
  constructor() {
    this._modal    = null;
    this._canvas   = null;
    this._ctx      = null;
    this._resolve  = null;

    // Current state
    this._device   = null;  // { entity_id, name, domain }
    this._room     = null;  // { id, name, color }
    this._bounds   = null;  // { cx, cy, cz, w, d, h }
    this._siblings = [];    // [{position_3d, name}]

    // Room-local position being edited (starts at existing position)
    this._x = 0;    // left-right (−w/2 … +w/2)
    this._y = 1.2;  // height (0 = floor, h = ceiling)
    this._z = 0;    // front-back (−d/2 … +d/2)

    // Drag state
    this._dragging    = false;
    this._scale       = 1;   // px per meter on canvas
    this._originX     = 0;   // canvas px for x=0
    this._originZ     = 0;   // canvas px for z=0

    this._buildDOM();
  }

  // ── Open — returns Promise<{x,y,z}> or null if cancelled ──────────────────
  open(device, room, bounds, siblings = []) {
    this._device   = device;
    this._room     = room;
    this._bounds   = bounds;
    this._siblings = siblings;

    // Pre-populate with existing position (if any)
    const pos = device.position_3d;
    this._x = pos?.x ?? 0;
    this._y = pos?.y ?? _defaultHeight(device.domain);
    this._z = pos?.z ?? 0;

    // Clamp to room bounds
    const hw = bounds.w / 2 - 0.1;
    const hd = bounds.d / 2 - 0.1;
    this._x = Math.max(-hw, Math.min(hw, this._x));
    this._z = Math.max(-hd, Math.min(hd, this._z));
    this._y = Math.max(0,   Math.min(bounds.h, this._y));

    // Compute canvas scale: fit w×d into (CANVAS_W - 2*PAD) × (CANVAS_H - 2*PAD)
    const availW = CANVAS_W - 2 * PAD;
    const availH = CANVAS_H - 2 * PAD;
    this._scale   = Math.min(availW / bounds.w, availH / bounds.d);
    this._originX = CANVAS_W / 2;
    this._originZ = CANVAS_H / 2;

    // Update UI
    this._modal.querySelector('.pk-device-name').textContent = device.name;
    this._modal.querySelector('.pk-room-name').textContent   = room.name;
    const dot = this._modal.querySelector('.pk-room-dot');
    if (dot) dot.style.background = room.color ?? '#6366f1';

    // Height slider
    const slider = this._modal.querySelector('.pk-height-slider');
    slider.min   = 0;
    slider.max   = bounds.h;
    slider.step  = 0.05;
    slider.value = this._y;

    this._updateCoordDisplay();
    this._draw();

    this._modal.classList.add('open');
    document.body.style.overflow = 'hidden';

    return new Promise(resolve => { this._resolve = resolve; });
  }

  // ── DOM ───────────────────────────────────────────────────────────────────
  _buildDOM() {
    const el = document.createElement('div');
    el.className = 'picker-overlay';
    el.innerHTML = `
      <div class="picker-modal">
        <div class="pk-header">
          <span class="pk-icon">📍</span>
          <div class="pk-titles">
            <div class="pk-device-name"></div>
            <div class="pk-room-line">
              <span class="pk-room-dot"></span>
              <span class="pk-room-name"></span>
            </div>
          </div>
          <button class="pk-close" title="Cancel">✕</button>
        </div>

        <div class="pk-body">
          <div class="pk-canvas-label">TOP VIEW — drag to position (X / Z)</div>
          <canvas class="pk-canvas" width="${CANVAS_W}" height="${CANVAS_H}"></canvas>

          <div class="pk-height-section">
            <div class="pk-height-header">
              <span class="pk-height-label-text">HEIGHT</span>
              <span class="pk-height-value"></span>
            </div>
            <div class="pk-slider-row">
              <span class="pk-slider-edge">Floor</span>
              <input class="pk-height-slider" type="range">
              <span class="pk-slider-edge">Ceiling</span>
            </div>
            <div class="pk-height-desc"></div>
          </div>

          <div class="pk-coords"></div>
        </div>

        <div class="pk-footer">
          <button class="pk-cancel-btn">Cancel</button>
          <button class="pk-save-btn">Save Position</button>
        </div>
      </div>`;

    document.body.appendChild(el);
    this._modal  = el;
    this._canvas = el.querySelector('.pk-canvas');
    this._ctx    = this._canvas.getContext('2d');

    // Height slider events
    const slider = el.querySelector('.pk-height-slider');
    slider.addEventListener('input', () => {
      this._y = parseFloat(slider.value);
      this._updateCoordDisplay();
      this._draw();
    });

    // Canvas drag events
    this._canvas.addEventListener('mousedown',  e => this._onDown(e));
    this._canvas.addEventListener('mousemove',  e => this._onMove(e));
    this._canvas.addEventListener('mouseup',    ()  => { this._dragging = false; });
    this._canvas.addEventListener('mouseleave', ()  => { this._dragging = false; });
    // Touch
    this._canvas.addEventListener('touchstart', e => { e.preventDefault(); this._onDown(e.touches[0]); }, { passive: false });
    this._canvas.addEventListener('touchmove',  e => { e.preventDefault(); this._onMove(e.touches[0]); }, { passive: false });
    this._canvas.addEventListener('touchend',   ()  => { this._dragging = false; });

    // Buttons
    el.querySelector('.pk-close').addEventListener('click',      () => this._cancel());
    el.querySelector('.pk-cancel-btn').addEventListener('click', () => this._cancel());
    el.querySelector('.pk-save-btn').addEventListener('click',   () => this._save());

    // Click on overlay backdrop to cancel
    el.addEventListener('click', e => { if (e.target === el) this._cancel(); });

    // Escape key
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && el.classList.contains('open')) this._cancel(); });
  }

  // ── Canvas drawing ────────────────────────────────────────────────────────
  _draw() {
    const ctx = this._ctx;
    const s   = this._scale;
    const ox  = this._originX;
    const oz  = this._originZ;
    const b   = this._bounds;

    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);

    // Background
    ctx.fillStyle = '#0d1018';
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

    // Room outline
    const rw = b.w * s;
    const rd = b.d * s;
    const rx = ox - rw / 2;
    const rz = oz - rd / 2;

    ctx.strokeStyle = 'rgba(255,255,255,0.15)';
    ctx.lineWidth   = 1;
    ctx.fillStyle   = 'rgba(255,255,255,0.04)';
    ctx.beginPath();
    ctx.rect(rx, rz, rw, rd);
    ctx.fill();
    ctx.stroke();

    // 1m grid lines
    ctx.strokeStyle = 'rgba(255,255,255,0.07)';
    ctx.lineWidth   = 0.5;
    for (let x = Math.ceil(-b.w / 2); x <= Math.floor(b.w / 2); x++) {
      const px = ox + x * s;
      ctx.beginPath(); ctx.moveTo(px, rz); ctx.lineTo(px, rz + rd); ctx.stroke();
    }
    for (let z = Math.ceil(-b.d / 2); z <= Math.floor(b.d / 2); z++) {
      const pz = oz + z * s;
      ctx.beginPath(); ctx.moveTo(rx, pz); ctx.lineTo(rx + rw, pz); ctx.stroke();
    }

    // Origin crosshair
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth   = 0.8;
    ctx.setLineDash([3, 4]);
    ctx.beginPath(); ctx.moveTo(ox, rz); ctx.lineTo(ox, rz + rd); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(rx, oz); ctx.lineTo(rx + rw, oz); ctx.stroke();
    ctx.setLineDash([]);

    // Sibling devices (other devices in the same room)
    for (const sib of this._siblings) {
      if (!sib.position_3d || sib.entity_id === this._device.entity_id) continue;
      const sx = ox + sib.position_3d.x * s;
      const sz = oz + sib.position_3d.z * s;
      ctx.beginPath();
      ctx.arc(sx, sz, 5, 0, Math.PI * 2);
      ctx.fillStyle   = 'rgba(180,180,200,0.35)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(180,180,200,0.6)';
      ctx.lineWidth   = 1;
      ctx.stroke();
    }

    // Current device dot
    const dx = ox + this._x * s;
    const dz = oz + this._z * s;

    // Outer glow
    const grd = ctx.createRadialGradient(dx, dz, 0, dx, dz, 18);
    grd.addColorStop(0,   'rgba(99,102,241,0.35)');
    grd.addColorStop(1,   'rgba(99,102,241,0)');
    ctx.beginPath();
    ctx.arc(dx, dz, 18, 0, Math.PI * 2);
    ctx.fillStyle = grd;
    ctx.fill();

    // Ring
    ctx.beginPath();
    ctx.arc(dx, dz, 9, 0, Math.PI * 2);
    ctx.fillStyle   = '#6366f1';
    ctx.fill();
    ctx.strokeStyle = '#a5b4fc';
    ctx.lineWidth   = 2;
    ctx.stroke();

    // Centre dot
    ctx.beginPath();
    ctx.arc(dx, dz, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.fill();

    // Dimension labels (room size)
    ctx.fillStyle = 'rgba(120,130,160,0.7)';
    ctx.font      = '9px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`${b.w.toFixed(1)}m`, ox, rz + rd + 12);
    ctx.save();
    ctx.translate(rx - 12, oz);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(`${b.d.toFixed(1)}m`, 0, 0);
    ctx.restore();
  }

  // ── Pointer events ────────────────────────────────────────────────────────
  _canvasCoord(e) {
    const r = this._canvas.getBoundingClientRect();
    return {
      px: (e.clientX - r.left) * (CANVAS_W / r.width),
      pz: (e.clientY - r.top)  * (CANVAS_H / r.height),
    };
  }

  _onDown(e) {
    this._dragging = true;
    this._moveDot(e);
  }

  _onMove(e) {
    if (!this._dragging) return;
    this._moveDot(e);
  }

  _moveDot(e) {
    const { px, pz } = this._canvasCoord(e);
    const hw = this._bounds.w / 2;
    const hd = this._bounds.d / 2;
    this._x = Math.max(-hw, Math.min(hw, (px - this._originX) / this._scale));
    this._z = Math.max(-hd, Math.min(hd, (pz - this._originZ) / this._scale));
    this._updateCoordDisplay();
    this._draw();
  }

  // ── Coord display ─────────────────────────────────────────────────────────
  _updateCoordDisplay() {
    const h = this._y;

    // Height label
    let heightLabel;
    if      (h < 0.15) heightLabel = 'Floor level';
    else if (h < 0.60) heightLabel = 'Low (socket/sensor)';
    else if (h < 1.20) heightLabel = 'Mid (switch height)';
    else if (h < 1.80) heightLabel = 'Upper wall';
    else if (h < 2.30) heightLabel = 'High (sconce/camera)';
    else               heightLabel = 'Ceiling';

    const valEl  = this._modal.querySelector('.pk-height-value');
    const descEl = this._modal.querySelector('.pk-height-desc');
    if (valEl)  valEl.textContent  = h.toFixed(2) + 'm';
    if (descEl) descEl.textContent = heightLabel;

    const coordEl = this._modal.querySelector('.pk-coords');
    if (coordEl) {
      coordEl.textContent =
        `x: ${this._x.toFixed(2)}  ·  y: ${h.toFixed(2)}  ·  z: ${this._z.toFixed(2)}`;
    }
  }

  // ── Actions ───────────────────────────────────────────────────────────────
  _save() {
    const pos = {
      x: parseFloat(this._x.toFixed(3)),
      y: parseFloat(this._y.toFixed(3)),
      z: parseFloat(this._z.toFixed(3)),
    };
    this._close();
    this._resolve?.(pos);
    this._resolve = null;
  }

  _cancel() {
    this._close();
    this._resolve?.(null);
    this._resolve = null;
  }

  _close() {
    this._modal.classList.remove('open');
    document.body.style.overflow = '';
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function _defaultHeight(domain) {
  switch (domain) {
    case 'light':         return 2.2;   // near ceiling
    case 'binary_sensor': return 1.8;   // upper wall (motion/door)
    case 'sensor':        return 1.5;   // mid wall (temp/humidity)
    case 'lock':          return 1.0;   // door handle height
    default:              return 1.2;
  }
}
