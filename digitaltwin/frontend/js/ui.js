// ui.js — Sidebar, floor switcher, info panel, device controls + 2D picker + registration

import { api }                from './api.js';
import { PositionPicker }     from './picker.js';
import { DeviceRegistration } from './register.js';

const picker = new PositionPicker();
let registration = null;

export class UI {
  constructor(store, viewer) {
    this.store  = store;
    this.viewer = viewer;

    registration = new DeviceRegistration(store);

    this._buildFloorSwitcher();
    this._buildSidebarFooter();
    this._bindStore();
  }

  // ── Sidebar ───────────────────────────────────────────────────────────────
  rebuildSidebar() {
    const list = document.getElementById('room-list');
    if (!list) return;

    const rooms  = [...this.store.rooms.values()].sort((a, b) => a.floor - b.floor || a.name.localeCompare(b.name));
    const floors = [...new Set(rooms.map(r => r.floor))].sort();
    let html = '';

    for (const floor of floors) {
      html += `<div class="floor-group"><div class="floor-group-label">Floor ${floor}</div>`;
      for (const room of rooms.filter(r => r.floor === floor)) {
        const count = room.device_count ?? 0;
        html += `
          <button class="room-item" data-room="${room.id}">
            <span class="ri-dot" style="background:${room.color ?? '#6366f1'}"></span>
            <span class="ri-name">${room.name}</span>
            <span class="ri-badge">${count}</span>
          </button>`;
      }
      html += '</div>';
    }

    list.innerHTML = html;
    list.querySelectorAll('.room-item').forEach(btn =>
      btn.addEventListener('click', () => this.store.selectRoom(btn.dataset.room))
    );
    if (this.store.selectedRoomId) {
      const active = list.querySelector(`[data-room="${this.store.selectedRoomId}"]`);
      if (active) active.classList.add('active');
    }
    for (const room of rooms) {
      this.viewer.updateRoomLabelCount(room.id, room.device_count ?? 0);
    }
  }

  // ── Sidebar footer ────────────────────────────────────────────────────────
  _buildSidebarFooter() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;

    const footer = document.createElement('div');
    footer.className = 'sidebar-footer';
    footer.innerHTML = `
      <button class="sidebar-add-btn" id="add-device-btn">
        <span class="sidebar-add-btn-icon">＋</span>
        Add Device
      </button>`;
    sidebar.appendChild(footer);

    footer.querySelector('#add-device-btn').addEventListener('click', () => {
      this._openRegistration();
    });
  }

  // ── Floor switcher ────────────────────────────────────────────────────────
  _buildFloorSwitcher() {
    const sw = document.getElementById('floor-switcher');
    if (!sw) return;
    sw.innerHTML = [
      { val: 0, label: 'All' },
      { val: 1, label: 'Floor 1' },
      { val: 2, label: 'Floor 2' },
    ].map(f =>
      `<button class="fsw-btn${f.val === 0 ? ' active' : ''}" data-floor="${f.val}">${f.label}</button>`
    ).join('');

    sw.querySelectorAll('.fsw-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        sw.querySelectorAll('.fsw-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.store.setFloor(parseInt(btn.dataset.floor));
      });
    });
  }

  // ── Store bindings ────────────────────────────────────────────────────────
  _bindStore() {
    this.store.on('roomSelected', ({ roomId }) => {
      document.querySelectorAll('.room-item').forEach(btn =>
        btn.classList.toggle('active', btn.dataset.room === roomId)
      );
      this._showInfoPanel(roomId);
    });

    this.store.on('floorChanged', ({ floor }) => this.viewer.setFloor(floor));
    // devicesUpdated panel refresh is handled by main.js calling ui._showInfoPanel directly
  }

  // ── Registration flow ─────────────────────────────────────────────────────
  async _openRegistration() {
    const device = await registration.open();
    if (!device) return;

    // Add to store immediately (optimistic) — triggers devicesUpdated → full rebuild
    this.store.addDevice(device);

    _toast(`${device.name ?? device.entity_id} added ✓`);

    // Open 2D picker to set position
    if (device.room_id) {
      const room   = this.store.getRoomById(device.room_id);
      const bounds = this.viewer.getRoomBounds(device.room_id);
      if (room && bounds) {
        const siblings = this.store.getDevicesForRoom(device.room_id);
        const localPos = await picker.open(device, room, bounds, siblings);

        if (localPos) {
          await this._savePosition(device.entity_id, localPos);
        }
      }
    }

    // Refresh panel for the new device's room
    if (this.store.selectedRoomId === device.room_id) {
      this._showInfoPanel(device.room_id);
    }
  }

  // ── 2D Position Picker (from info panel 📍 button) ────────────────────────
  async _openPicker(entityId, roomId) {
    const device  = this.store.devices.get(entityId);
    const room    = this.store.getRoomById(roomId);
    if (!device || !room) return;

    const bounds = this.viewer.getRoomBounds(roomId);
    if (!bounds) {
      _toast('Room bounds not available yet', true);
      return;
    }

    const siblings = this.store.getDevicesForRoom(roomId);
    const localPos = await picker.open(device, room, bounds, siblings);
    if (!localPos) return;

    await this._savePosition(entityId, localPos);
  }

  // ── Shared: save position to API + update store + rebuild markers ──────────
  // This is the ONE place that handles position saving, avoiding duplicate bugs.
  async _savePosition(entityId, localPos) {
    try {
      await api.updateTwinDevice(entityId, { position_3d: localPos });

      // CRITICAL: update the object that is CURRENTLY in the store.
      // The picker awaits user interaction — the poll may have replaced the
      // store reference during that time. We must NOT mutate the local `device`
      // variable; we must update whatever is in the store RIGHT NOW.
      const inStore = this.store.devices.get(entityId);
      if (inStore) inStore.position_3d = localPos;

      // Full marker rebuild — now the device has position_3d in the store
      this.viewer.placeDeviceMarkers(this.store.devices, this.store.rooms);

      _toast('Position saved ✓');
    } catch (err) {
      _toast('Could not save position', true);
      console.error(err);
    }
  }

  // ── Info panel ────────────────────────────────────────────────────────────
  _showInfoPanel(roomId) {
    const panel = document.getElementById('info-panel');
    if (!panel) return;
    if (!roomId) { panel.classList.remove('open'); return; }

    const room = this.store.getRoomById(roomId);
    if (!room) return;
    const devices = this.store.getDevicesForRoom(roomId);

    document.getElementById('info-room-name').textContent     = room.name;
    document.getElementById('info-room-floor').textContent    = `Floor ${room.floor}`;
    document.getElementById('info-room-dot').style.background = room.color ?? '#6366f1';
    document.getElementById('info-room-id').textContent       = room.id;
    document.getElementById('info-device-count').textContent  =
      `${devices.length} device${devices.length !== 1 ? 's' : ''}`;

    const listEl = document.getElementById('info-device-list');
    if (!listEl) return;

    listEl.innerHTML = devices.length === 0
      ? `<div class="di-empty">No devices — click <strong>＋ Add Device</strong> in the sidebar</div>`
      : devices.map(d => _renderDeviceRow(d)).join('');

    listEl.querySelectorAll('.di-toggle').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        this._toggleDevice(btn.dataset.entity, btn.dataset.domain);
      });
    });

    listEl.querySelectorAll('.di-brightness').forEach(slider => {
      slider.addEventListener('change', e => {
        e.stopPropagation();
        this._setBrightness(slider.dataset.entity, parseInt(slider.value));
      });
      slider.addEventListener('input', () => {
        const label = slider.parentElement.querySelector('.di-brightness-val');
        if (label) label.textContent = slider.value + '%';
      });
    });

    listEl.querySelectorAll('.di-reposition').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        this._openPicker(btn.dataset.entity, roomId);
      });
    });

    listEl.querySelectorAll('.di-unregister').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        this._unregisterDevice(btn.dataset.entity);
      });
    });

    panel.classList.add('open');
  }

  // ── Device actions ────────────────────────────────────────────────────────
  async _toggleDevice(entityId, domain) {
    try {
      const action = _toggleAction(domain, this.store.devices.get(entityId)?.live?.state);
      await api.controlDevice(entityId, action);
      setTimeout(() => this.store.refreshDevices(), 400);
    } catch {
      _toast('Control failed', true);
    }
  }

  async _setBrightness(entityId, pct) {
    try {
      await api.controlDevice(entityId, 'turn_on', { brightness_pct: pct });
      setTimeout(() => this.store.refreshDevices(), 400);
    } catch {
      _toast('Brightness failed', true);
    }
  }

  async _unregisterDevice(entityId) {
    const device = this.store.devices.get(entityId);
    const name   = device?.name ?? entityId;
    if (!confirm(`Remove "${name}" from the twin?\n\nThis only removes it from your 3D model — the device stays in Home Assistant.`)) return;

    try {
      await api.unregisterDevice(entityId);
      this.store.removeDevice(entityId);
      _toast(`${name} removed from twin`);
    } catch {
      _toast('Failed to remove device', true);
    }
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function _toggleAction(domain, currentState) {
  if (domain === 'lock') return currentState === 'locked' ? 'unlock' : 'lock';
  return currentState === 'on' ? 'turn_off' : 'turn_on';
}

function _renderDeviceRow(device) {
  const s         = device.live?.state ?? '—';
  const isOn      = s === 'on';
  const isLocked  = s === 'locked';
  const canToggle = ['light','switch','input_boolean','lock','fan'].includes(device.domain);
  const canDim    = device.domain === 'light' && isOn;
  const bPct      = device.live?.brightness_pct ?? 80;
  const hasPos    = !!device.position_3d;

  return `
    <div class="device-item" data-entity="${device.entity_id}">
      <div class="di-icon">${_domainIcon(device.domain)}</div>
      <div class="di-info">
        <div class="di-name">${device.name}</div>
        <div class="di-domain">${device.domain}${!hasPos ? ' · <span style="color:var(--warn)">no position</span>' : ''}</div>
        ${canDim ? `
        <div class="di-slider-wrap">
          <input class="di-brightness" type="range" min="1" max="100" value="${bPct}" data-entity="${device.entity_id}">
          <span class="di-brightness-val">${bPct}%</span>
        </div>` : ''}
      </div>
      <div class="di-actions">
        <span class="di-badge ${_stateBadgeCls(device)}">${_stateStr(device)}</span>
        ${canToggle ? `<button class="di-toggle" data-entity="${device.entity_id}" data-domain="${device.domain}">${isOn || isLocked ? '⏸' : '▶'}</button>` : ''}
        <button class="di-reposition" data-entity="${device.entity_id}" title="${hasPos ? 'Reposition' : 'Set position'}">📍</button>
        <button class="di-unregister" data-entity="${device.entity_id}" title="Remove from twin">🗑</button>
      </div>
    </div>`;
}

function _domainIcon(domain) {
  return {light:'💡',switch:'🔌',binary_sensor:'📡',sensor:'🌡',lock:'🔒',media_player:'📺',fan:'💨',cover:'🪟'}[domain] ?? '⚙️';
}

function _stateStr(device) {
  const s  = device.live?.state ?? '—';
  const bv = device.live?.brightness_pct;
  if (device.domain === 'light'  && s === 'on' && bv != null) return `on · ${bv}%`;
  if (device.domain === 'sensor') return `${s}${device.live?.unit ?? ''}`;
  return s;
}

function _stateBadgeCls(device) {
  const s = device.live?.state;
  if (s === 'on')                         return 'badge-on';
  if (s === 'off' || s === 'unavailable') return 'badge-off';
  if (s === 'locked')                     return 'badge-locked';
  if (s === 'unlocked')                   return 'badge-unlocked';
  if (device.domain === 'sensor')         return 'badge-sensor';
  return 'badge-off';
}

function _toast(msg, isError = false) {
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' toast-error' : '');
  el.textContent = msg;
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add('toast-show'));
  setTimeout(() => { el.classList.remove('toast-show'); setTimeout(() => el.remove(), 300); }, 2200);
}
