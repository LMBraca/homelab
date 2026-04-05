// devices.js — Phase 3: Device Control Panel + Position Picker

import { api } from './api.js';
import { ROOM_LAYOUT, WALL_HEIGHT, FLOOR_SLAB } from './rooms.js';

// ── Helpers ───────────────────────────────────────────────────────────────────

const DOMAIN_ICON = {
  light:         '💡',
  switch:        '🔌',
  binary_sensor: '📡',
  sensor:        '🌡',
  lock:          '🔒',
  media_player:  '📺',
  climate:       '🌡',
  fan:           '💨',
  cover:         '🪟',
};

function _badgeCls(device) {
  const s = device.live?.state;
  if (s === 'on')                         return 'badge-on';
  if (s === 'locked')                     return 'badge-locked';
  if (s === 'unlocked')                   return 'badge-unlocked';
  if (s === 'off' || s === 'unavailable') return 'badge-off';
  if (device.domain === 'sensor')         return 'badge-sensor';
  return 'badge-off';
}

function _stateLabel(device) {
  const s  = device.live?.state ?? '—';
  const bv = device.live?.brightness_pct;
  if (device.domain === 'light' && s === 'on' && bv != null) return `on · ${bv}%`;
  if (device.domain === 'sensor') return `${s}${device.live?.unit ?? ''}`;
  return s;
}

function _miredsToK(mireds) { return Math.round(1_000_000 / mireds / 100) * 100; }

function _hexToRgb(hex) {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

function _rgbArrayToHex(rgb) {
  if (!rgb || rgb.length < 3) return '#ffffff';
  return '#' + rgb.map(v => v.toString(16).padStart(2, '0')).join('');
}

// ── Toast ─────────────────────────────────────────────────────────────────────

export function showToast(msg, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.classList.add('visible'), 10);
  setTimeout(() => {
    toast.classList.remove('visible');
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

// ═════════════════════════════════════════════════════════════════════════════
// ── PositionPicker — 2D floor-plan modal ────────────────────────────────────
// ═════════════════════════════════════════════════════════════════════════════

class PositionPicker {
  constructor(store) {
    this.store   = store;
    this._modal  = document.getElementById('position-modal');
    this._canvas = document.getElementById('pp-canvas');
    this._ctx    = this._canvas?.getContext('2d');
    this._resolve  = null;
    this._device   = null;
    this._room     = null;
    this._layout   = null;
    this._pos      = { x: 0, y: FLOOR_SLAB + 0.1, z: 0 };
    this._dragging = false;
    this._bindEvents();
  }

  // Returns Promise<{x,y,z}|null>
  open(device, store) {
    return new Promise(resolve => {
      this._resolve = resolve;
      this._device  = device;
      this._room    = store.rooms.get(device.room_id);
      this._layout  = ROOM_LAYOUT[device.room_id];

      if (!this._layout) { resolve(null); return; }

      // Seed from existing position or room centre
      this._pos = device.position_3d
        ? { ...device.position_3d }
        : { x: 0, y: FLOOR_SLAB + 0.1, z: 0 };

      // Populate header
      document.getElementById('pp-device-name').textContent = device.name;
      document.getElementById('pp-room-name').textContent   = this._room?.name ?? device.room_id;

      // Height slider
      const slider = document.getElementById('pp-height');
      slider.min   = 0;
      slider.max   = WALL_HEIGHT;
      slider.step  = 0.05;
      slider.value = this._pos.y;

      this._modal.classList.add('open');
      this._resizeCanvas();
      this._draw();
      this._updateReadout();
    });
  }

  cancel() { this._close(null); }

  _close(result) {
    this._modal.classList.remove('open');
    this._resolve?.(result);
    this._resolve = null;
  }

  _bindEvents() {
    document.getElementById('pp-cancel')?.addEventListener('click', () => this._close(null));
    document.getElementById('pp-save')?.addEventListener('click', () => this._close({ ...this._pos }));
    document.getElementById('pp-modal-close')?.addEventListener('click', () => this._close(null));

    // Click backdrop to cancel
    this._modal?.addEventListener('click', e => {
      if (e.target === this._modal) this._close(null);
    });

    // Height slider
    document.getElementById('pp-height')?.addEventListener('input', e => {
      this._pos.y = parseFloat(e.target.value);
      this._updateReadout();
    });

    // Canvas mouse
    const c = this._canvas;
    if (!c) return;
    c.addEventListener('mousedown', e => { this._dragging = true;  this._onMousePos(e); });
    c.addEventListener('mousemove', e => { if (this._dragging) this._onMousePos(e); });
    c.addEventListener('mouseup',   () => { this._dragging = false; });
    c.addEventListener('mouseleave',() => { this._dragging = false; });

    // Touch
    c.addEventListener('touchstart', e => { e.preventDefault(); this._dragging = true;  this._onTouchPos(e); }, { passive: false });
    c.addEventListener('touchmove',  e => { e.preventDefault(); if (this._dragging) this._onTouchPos(e); },  { passive: false });
    c.addEventListener('touchend',   () => { this._dragging = false; });

    // Resize canvas when modal opens
    new ResizeObserver(() => { if (this._modal.classList.contains('open')) { this._resizeCanvas(); this._draw(); } })
      .observe(this._canvas?.parentElement ?? document.body);
  }

  _resizeCanvas() {
    const c = this._canvas;
    if (!c) return;
    const parent = c.parentElement;
    c.width  = parent.clientWidth;
    c.height = parent.clientHeight;
  }

  _onMousePos(e) {
    const r = this._canvas.getBoundingClientRect();
    this._setPosFromPixel(e.clientX - r.left, e.clientY - r.top);
  }

  _onTouchPos(e) {
    const t = e.touches[0];
    const r = this._canvas.getBoundingClientRect();
    this._setPosFromPixel(t.clientX - r.left, t.clientY - r.top);
  }

  _setPosFromPixel(px, py) {
    const { PAD, scaleX, scaleZ } = this._metrics();
    const localX = (px - PAD) / scaleX - this._layout.w / 2;
    const localZ = (py - PAD) / scaleZ - this._layout.d / 2;
    this._pos.x = Math.max(-this._layout.w / 2 + 0.05, Math.min(this._layout.w / 2 - 0.05, localX));
    this._pos.z = Math.max(-this._layout.d / 2 + 0.05, Math.min(this._layout.d / 2 - 0.05, localZ));
    this._draw();
    this._updateReadout();
  }

  _metrics() {
    const PAD  = 28;
    const cw   = this._canvas.width;
    const ch   = this._canvas.height;
    const rw   = cw - PAD * 2;
    const rh   = ch - PAD * 2;
    const scaleX = rw / this._layout.w;
    const scaleZ = rh / this._layout.d;
    return { PAD, cw, ch, rw, rh, scaleX, scaleZ };
  }

  // Convert local room coords to canvas pixels
  _toCanvas(localX, localZ) {
    const { PAD, scaleX, scaleZ } = this._metrics();
    return {
      px: PAD + (localX + this._layout.w / 2) * scaleX,
      py: PAD + (localZ + this._layout.d / 2) * scaleZ,
    };
  }

  _draw() {
    const ctx = this._ctx;
    const { PAD, cw, ch, rw, rh, scaleX, scaleZ } = this._metrics();

    ctx.clearRect(0, 0, cw, ch);

    // ── Room background ──────────────────────────────────────────────────────
    const roomColor = this._room?.color ?? '#6366f1';
    ctx.fillStyle   = 'rgba(20, 23, 36, 0.95)';
    ctx.strokeStyle = roomColor + '50';
    ctx.lineWidth   = 2;
    ctx.beginPath();
    ctx.roundRect(PAD, PAD, rw, rh, 6);
    ctx.fill();
    ctx.stroke();

    // ── Grid (1m squares) ────────────────────────────────────────────────────
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.lineWidth   = 1;
    for (let x = 0; x <= this._layout.w; x++) {
      const px = PAD + x * scaleX;
      ctx.beginPath(); ctx.moveTo(px, PAD); ctx.lineTo(px, PAD + rh); ctx.stroke();
    }
    for (let z = 0; z <= this._layout.d; z++) {
      const pz = PAD + z * scaleZ;
      ctx.beginPath(); ctx.moveTo(PAD, pz); ctx.lineTo(PAD + rw, pz); ctx.stroke();
    }

    // ── Room border ──────────────────────────────────────────────────────────
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth   = 1.5;
    ctx.beginPath();
    ctx.roundRect(PAD, PAD, rw, rh, 6);
    ctx.stroke();

    // ── Dimension labels ─────────────────────────────────────────────────────
    ctx.fillStyle  = 'rgba(90,96,128,0.9)';
    ctx.font       = '10px "SF Mono", monospace';
    ctx.textAlign  = 'center';
    ctx.fillText(`${this._layout.w}m`, PAD + rw / 2, PAD - 8);
    ctx.save();
    ctx.translate(PAD - 10, PAD + rh / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(`${this._layout.d}m`, 0, 0);
    ctx.restore();

    // ── Axis labels ──────────────────────────────────────────────────────────
    ctx.fillStyle = 'rgba(90,96,128,0.6)';
    ctx.font      = '9px monospace';
    ctx.textAlign = 'right';
    ctx.fillText('← W', PAD + 4, PAD + rh + 14);
    ctx.textAlign = 'left';
    ctx.fillText('E →', PAD + rw - 4, PAD + rh + 14);
    ctx.textAlign = 'center';
    ctx.fillText('N ↑', PAD + rw / 2, PAD + rh + 14);

    // ── Other devices in the same room ────────────────────────────────────────
    ctx.font = '11px sans-serif';
    for (const [, d] of this.store.devices) {
      if (d.room_id !== this._device.room_id) continue;
      if (d.entity_id === this._device.entity_id) continue;
      if (!d.position_3d) continue;

      const { px, py } = this._toCanvas(d.position_3d.x, d.position_3d.z);
      ctx.beginPath();
      ctx.arc(px, py, 5, 0, Math.PI * 2);
      ctx.fillStyle   = 'rgba(100,110,140,0.45)';
      ctx.strokeStyle = 'rgba(255,255,255,0.15)';
      ctx.lineWidth   = 1;
      ctx.fill();
      ctx.stroke();

      // Mini icon label
      const icon = DOMAIN_ICON[d.domain] ?? '⚙';
      ctx.fillText(icon, px, py - 9);
    }

    // ── Crosshair ────────────────────────────────────────────────────────────
    const { px: dotX, py: dotZ } = this._toCanvas(this._pos.x, this._pos.z);
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = roomColor + '50';
    ctx.lineWidth   = 1;
    ctx.beginPath(); ctx.moveTo(dotX, PAD + 1); ctx.lineTo(dotX, PAD + rh - 1); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(PAD + 1, dotZ); ctx.lineTo(PAD + rw - 1, dotZ); ctx.stroke();
    ctx.setLineDash([]);

    // ── Device dot ───────────────────────────────────────────────────────────
    // Outer glow
    const grd = ctx.createRadialGradient(dotX, dotZ, 0, dotX, dotZ, 18);
    grd.addColorStop(0, roomColor + '40');
    grd.addColorStop(1, 'transparent');
    ctx.beginPath();
    ctx.arc(dotX, dotZ, 18, 0, Math.PI * 2);
    ctx.fillStyle = grd;
    ctx.fill();

    // Fill
    ctx.beginPath();
    ctx.arc(dotX, dotZ, 9, 0, Math.PI * 2);
    ctx.fillStyle = roomColor;
    ctx.fill();

    // Border
    ctx.beginPath();
    ctx.arc(dotX, dotZ, 9, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(255,255,255,0.85)';
    ctx.lineWidth   = 2;
    ctx.stroke();

    // Icon inside dot
    ctx.fillStyle  = '#fff';
    ctx.font       = '10px sans-serif';
    ctx.textAlign  = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(DOMAIN_ICON[this._device.domain] ?? '⚙', dotX, dotZ);
    ctx.textBaseline = 'alphabetic';
  }

  _updateReadout() {
    const y   = parseFloat(document.getElementById('pp-height').value);
    this._pos.y = y;

    const pct   = y / WALL_HEIGHT;
    const label = pct > 0.85 ? 'Ceiling'
                : pct > 0.5  ? 'Upper wall'
                : pct > 0.25 ? 'Mid-wall'
                : pct > 0.05 ? 'Low'
                              : 'Floor';

    document.getElementById('pp-height-label').textContent = `${y.toFixed(2)}m — ${label}`;
    document.getElementById('pp-coords').textContent =
      `x ${this._pos.x.toFixed(2)}  ·  y ${y.toFixed(2)}  ·  z ${this._pos.z.toFixed(2)}`;
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// ── DevicePanel ──────────────────────────────────────────────────────────────
// ═════════════════════════════════════════════════════════════════════════════

export class DevicePanel {
  constructor(store, viewer) {
    this.store  = store;
    this.viewer = viewer;

    this._entityId = null;
    this._el       = document.getElementById('device-panel');
    this._picker   = new PositionPicker(store);

    this._bindStaticEvents();
    this.store.on('devicesUpdated', () => this.refresh());
  }

  open(entityId) {
    const device = this.store.devices.get(entityId);
    if (!device) return;
    this._entityId = entityId;
    this._render(device);
    this._el.classList.add('open');
    document.getElementById('info-panel')?.classList.remove('open');
  }

  close() {
    this._picker.cancel();
    this._entityId = null;
    this._el.classList.remove('open');
  }

  refresh() {
    if (!this._entityId || !this._el.classList.contains('open')) return;
    const device = this.store.devices.get(this._entityId);
    if (device) this._render(device);
  }

  // ── Rendering ──────────────────────────────────────────────────────────────

  _render(device) {
    const live = device.live ?? {};
    const icon = DOMAIN_ICON[device.domain] ?? '⚙️';

    document.getElementById('dp-icon').textContent   = icon;
    document.getElementById('dp-name').textContent   = device.name;
    document.getElementById('dp-entity').textContent = device.entity_id;

    const badge = document.getElementById('dp-state-badge');
    badge.textContent = _stateLabel(device);
    badge.className   = `dp-state-badge ${_badgeCls(device)}`;

    document.getElementById('dp-controls').innerHTML = this._buildControls(device);
    this._bindControlEvents(device);
    this._renderRoomDropdown(device);

    const placeBtn = document.getElementById('dp-place-btn');
    if (placeBtn) {
      placeBtn.textContent = device.position_3d ? '📍 Reposition' : '📍 Place in 3D';
      placeBtn.disabled    = !device.room_id;
      placeBtn.title       = device.room_id ? '' : 'Assign a room first';
    }
  }

  // ── Controls ───────────────────────────────────────────────────────────────

  _buildControls(device) {
    const caps  = device.capabilities ?? [];
    const live  = device.live ?? {};
    const state = live.state ?? '—';
    const isOn  = state === 'on';

    if (caps.length === 0 || (caps.length === 1 && caps[0] === 'read_only')) {
      return `<div class="dp-readonly">
        <span class="dp-readonly-label">Current value</span>
        <span class="dp-readonly-value">${state}${live.unit ?? ''}</span>
      </div>`;
    }

    if (device.domain === 'lock') {
      const isLocked = state === 'locked';
      return `<div class="dp-control-row dp-lock-row">
        <div class="dp-lock-state ${isLocked ? 'locked' : 'unlocked'}">
          <span class="dp-lock-icon">${isLocked ? '🔒' : '🔓'}</span>
          <span>${isLocked ? 'Locked' : 'Unlocked'}</span>
        </div>
        <button class="dp-btn ${isLocked ? 'dp-btn-danger' : 'dp-btn-success'}"
          data-action="lock_toggle">${isLocked ? 'Unlock' : 'Lock'}</button>
      </div>`;
    }

    let html = '';

    if (caps.includes('on_off')) {
      html += `<div class="dp-control-row">
        <span class="dp-ctrl-label">Power</span>
        <button class="dp-toggle ${isOn ? 'on' : ''}" data-action="toggle" aria-pressed="${isOn}">
          <span class="dp-toggle-track"><span class="dp-toggle-thumb"></span></span>
          <span class="dp-toggle-text">${isOn ? 'ON' : 'OFF'}</span>
        </button>
      </div>`;
    }

    if (caps.includes('brightness')) {
      const bv = live.brightness_pct ?? 100;
      html += `<div class="dp-control-row ${!isOn ? 'dp-row-dim' : ''}">
        <span class="dp-ctrl-label">Brightness</span>
        <div class="dp-slider-wrap">
          <input type="range" class="dp-slider" min="1" max="100" value="${bv}"
            data-action="brightness" ${!isOn ? 'disabled' : ''}>
          <span class="dp-slider-val" id="dp-brightness-val">${bv}%</span>
        </div>
      </div>`;
    }

    if (caps.includes('color_temp')) {
      const ctK = live.color_temp_kelvin ?? (live.color_temp ? _miredsToK(live.color_temp) : 4000);
      html += `<div class="dp-control-row ${!isOn ? 'dp-row-dim' : ''}">
        <span class="dp-ctrl-label">Color Temp</span>
        <div class="dp-slider-wrap">
          <input type="range" class="dp-slider dp-ct-slider" min="2000" max="6500" step="100"
            value="${ctK}" data-action="color_temp" ${!isOn ? 'disabled' : ''}>
          <span class="dp-slider-val" id="dp-ct-val">${ctK}K</span>
        </div>
      </div>`;
    }

    if (caps.includes('color')) {
      const hexColor = live.rgb_color ? _rgbArrayToHex(live.rgb_color) : '#ffffff';
      html += `<div class="dp-control-row ${!isOn ? 'dp-row-dim' : ''}">
        <span class="dp-ctrl-label">Color</span>
        <div class="dp-color-wrap">
          <input type="color" class="dp-color-picker" value="${hexColor}"
            data-action="color" ${!isOn ? 'disabled' : ''}>
          <span class="dp-color-swatch" style="background:${hexColor}"></span>
          <span class="dp-color-val" id="dp-color-val">${hexColor}</span>
        </div>
      </div>`;
    }

    return html || `<div class="dp-readonly"><span class="dp-readonly-value">${state}</span></div>`;
  }

  _bindControlEvents(device) {
    const el  = document.getElementById('dp-controls');
    const eid = device.entity_id;

    el.querySelector('[data-action="toggle"]')?.addEventListener('click', () => {
      this._control(eid, device.live?.state === 'on' ? 'turn_off' : 'turn_on');
    });
    el.querySelector('[data-action="lock_toggle"]')?.addEventListener('click', () => {
      this._control(eid, device.live?.state === 'locked' ? 'unlock' : 'lock');
    });

    const bSlider = el.querySelector('[data-action="brightness"]');
    if (bSlider) {
      bSlider.addEventListener('input',  e => { document.getElementById('dp-brightness-val').textContent = `${e.target.value}%`; });
      bSlider.addEventListener('change', e => { this._control(eid, 'turn_on', { brightness_pct: parseInt(e.target.value) }); });
    }

    const ctSlider = el.querySelector('[data-action="color_temp"]');
    if (ctSlider) {
      ctSlider.addEventListener('input',  e => { document.getElementById('dp-ct-val').textContent = `${e.target.value}K`; });
      ctSlider.addEventListener('change', e => { this._control(eid, 'turn_on', { color_temp_kelvin: parseInt(e.target.value) }); });
    }

    const colorPicker = el.querySelector('[data-action="color"]');
    if (colorPicker) {
      colorPicker.addEventListener('input', e => {
        el.querySelector('.dp-color-swatch').style.background = e.target.value;
        document.getElementById('dp-color-val').textContent   = e.target.value;
      });
      colorPicker.addEventListener('change', e => {
        this._control(eid, 'turn_on', { rgb_color: _hexToRgb(e.target.value) });
      });
    }
  }

  async _control(entityId, action, serviceData = {}) {
    try {
      await api.controlDevice(entityId, action, serviceData);
      showToast(`✓ ${action.replace(/_/g, ' ')}`, 'success');
      setTimeout(() => this.store.refreshDevices(), 700);
    } catch (err) {
      showToast(`✗ ${err.message}`, 'error');
    }
  }

  // ── Room dropdown ──────────────────────────────────────────────────────────

  _renderRoomDropdown(device) {
    const select = document.getElementById('dp-room-select');
    if (!select) return;
    select.innerHTML =
      `<option value="">— unassigned —</option>` +
      [...this.store.rooms.values()]
        .sort((a, b) => a.name.localeCompare(b.name))
        .map(r => `<option value="${r.id}" ${r.id === device.room_id ? 'selected' : ''}>${r.name}</option>`)
        .join('');
    select.onchange = async () => {
      try {
        await api.updateDevice(device.entity_id, { room_id: select.value || null });
        showToast('Room updated', 'success');
        await this.store.loadData();
        this.viewer.placeDeviceMarkers(this.store.devices, this.store.rooms);
        this.refresh();
      } catch (err) {
        showToast(`✗ ${err.message}`, 'error');
      }
    };
  }

  // ── 2D Position Picker ─────────────────────────────────────────────────────

  async _openPicker() {
    const device = this.store.devices.get(this._entityId);
    if (!device?.room_id) return;

    document.getElementById('dp-place-btn')?.classList.add('active');
    const pos = await this._picker.open(device, this.store);
    document.getElementById('dp-place-btn')?.classList.remove('active');

    if (!pos) return; // cancelled

    try {
      await api.updateDevice(this._entityId, {
        room_id:     device.room_id,
        position_3d: { x: +pos.x.toFixed(3), y: +pos.y.toFixed(3), z: +pos.z.toFixed(3) },
      });
      showToast('📍 Position saved', 'success');
      await this.store.loadData();
      this.viewer.placeDeviceMarkers(this.store.devices, this.store.rooms);
      this.refresh();
    } catch (err) {
      showToast(`✗ ${err.message}`, 'error');
    }
  }

  _bindStaticEvents() {
    document.getElementById('dp-close-btn')?.addEventListener('click',  () => this.close());
    document.getElementById('dp-place-btn')?.addEventListener('click',  () => this._openPicker());
  }
}
