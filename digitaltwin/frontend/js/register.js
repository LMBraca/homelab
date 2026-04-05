// register.js — Add Device registration flow (Phase 4)
//
// Flow:
//  1. User clicks "+ Add Device" in sidebar
//  2. Modal opens, fetches GET /api/v1/discover?unregistered=true
//  3. List of unregistered HA entities shown, grouped by domain, searchable
//  4. User clicks a device → config step: display name, room, notes
//  5. User clicks "Add to Twin" → POST /api/v1/twin/devices
//  6. On success → modal closes → 2D picker opens to set position
//
// The class returns a Promise<registeredDevice | null> from open().

import { api } from './api.js';

const DOMAIN_ICONS = {
  light: '💡', switch: '🔌', binary_sensor: '📡', sensor: '🌡',
  lock: '🔒', media_player: '📺', fan: '💨', cover: '🪟',
  climate: '🌡️', input_boolean: '🔘', number: '🔢', button: '🔲',
};

const DOMAIN_LABELS = {
  light: 'Lights', switch: 'Switches', binary_sensor: 'Binary Sensors',
  sensor: 'Sensors', lock: 'Locks', media_player: 'Media Players',
  fan: 'Fans', cover: 'Covers', climate: 'Thermostats',
  input_boolean: 'Helpers', number: 'Numbers', button: 'Buttons',
};

export class DeviceRegistration {
  constructor(store) {
    this.store    = store;
    this._resolve = null;

    // All unregistered devices fetched from API: Map<entityId, device>
    this._allDevices  = new Map();
    this._filtered    = [];         // current filtered list
    this._selected    = null;       // device chosen in step 1
    this._step        = 'list';     // 'list' | 'config' | 'loading'

    this._buildDOM();
  }

  // ── Public ─────────────────────────────────────────────────────────────────
  // Returns Promise<device object> if registered, or null if cancelled.
  open() {
    this._step     = 'list';
    this._selected = null;
    this._allDevices.clear();
    this._filtered  = [];

    this._modal.classList.add('open');
    document.body.style.overflow = 'hidden';

    this._showLoading('Fetching devices from Home Assistant…');
    this._fetchDevices();

    return new Promise(resolve => { this._resolve = resolve; });
  }

  // ── DOM ────────────────────────────────────────────────────────────────────
  _buildDOM() {
    const el = document.createElement('div');
    el.className = 'reg-overlay';
    el.innerHTML = `
      <div class="reg-modal">

        <!-- Header -->
        <div class="reg-header">
          <div class="reg-header-left">
            <span class="reg-back-btn" id="reg-back" title="Back to list" style="display:none">← </span>
            <span class="reg-title" id="reg-title">Add Device to Twin</span>
          </div>
          <button class="reg-close" id="reg-close">✕</button>
        </div>

        <!-- Step 1: List -->
        <div class="reg-step" id="reg-step-list">
          <div class="reg-search-wrap">
            <span class="reg-search-icon">🔍</span>
            <input class="reg-search" id="reg-search" type="text" placeholder="Search devices…" autocomplete="off">
            <span class="reg-count" id="reg-device-count"></span>
          </div>
          <div class="reg-device-list" id="reg-device-list">
            <div class="reg-loading-msg" id="reg-loading">Loading…</div>
          </div>
        </div>

        <!-- Step 2: Config -->
        <div class="reg-step" id="reg-step-config" style="display:none">
          <div class="reg-selected-device" id="reg-selected-preview"></div>

          <div class="reg-field">
            <label class="reg-label">Display Name</label>
            <input class="reg-input" id="reg-display-name" type="text" placeholder="e.g. Bedside Lamp">
            <div class="reg-hint">Overrides the HA name in the 3D viewer</div>
          </div>

          <div class="reg-field">
            <label class="reg-label">Room</label>
            <select class="reg-select" id="reg-room">
              <option value="">— No room (unassigned) —</option>
            </select>
          </div>

          <div class="reg-field">
            <label class="reg-label">Notes <span class="reg-optional">(optional)</span></label>
            <input class="reg-input" id="reg-notes" type="text" placeholder="e.g. IKEA Tradfri E27, needs Zigbee dongle">
          </div>

          <div class="reg-config-footer">
            <button class="reg-btn-secondary" id="reg-back-btn">← Back</button>
            <button class="reg-btn-primary" id="reg-add-btn">Add to Twin →</button>
          </div>
        </div>

        <!-- Step 3: Success -->
        <div class="reg-step" id="reg-step-success" style="display:none">
          <div class="reg-success-content">
            <div class="reg-success-icon">✓</div>
            <div class="reg-success-title" id="reg-success-name"></div>
            <div class="reg-success-sub">Added to your digital twin</div>
            <div class="reg-success-sub" style="margin-top:6px;color:var(--muted2)">
              Opening position picker…
            </div>
          </div>
        </div>

      </div>`;

    document.body.appendChild(el);
    this._modal = el;

    // Wire events
    el.querySelector('#reg-close').addEventListener('click', () => this._cancel());
    el.addEventListener('click', e => { if (e.target === el) this._cancel(); });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && el.classList.contains('open')) this._cancel();
    });

    el.querySelector('#reg-search').addEventListener('input', e => {
      this._applyFilter(e.target.value);
    });

    el.querySelector('#reg-back').addEventListener('click', () => this._showList());
    el.querySelector('#reg-back-btn').addEventListener('click', () => this._showList());
    el.querySelector('#reg-add-btn').addEventListener('click', () => this._submit());
  }

  // ── Fetch devices ──────────────────────────────────────────────────────────
  async _fetchDevices() {
    try {
      const data = await api.discover({ unregistered: true });
      this._allDevices.clear();

      for (const [domain, devices] of Object.entries(data.domains ?? {})) {
        for (const d of devices) {
          this._allDevices.set(d.entity_id, { ...d, domain });
        }
      }

      this._applyFilter('');
    } catch (err) {
      this._showError(`Could not fetch devices: ${err.message}`);
    }
  }

  // ── Filter + render list ───────────────────────────────────────────────────
  _applyFilter(query) {
    const q = query.toLowerCase().trim();
    const all = [...this._allDevices.values()];

    this._filtered = q
      ? all.filter(d =>
          d.entity_id.toLowerCase().includes(q) ||
          (d.name  ?? '').toLowerCase().includes(q) ||
          (d.domain ?? '').toLowerCase().includes(q)
        )
      : all;

    this._renderList();
  }

  _renderList() {
    const listEl  = this._modal.querySelector('#reg-device-list');
    const countEl = this._modal.querySelector('#reg-device-count');

    const total = this._allDevices.size;
    const shown = this._filtered.length;

    if (total === 0) {
      listEl.innerHTML = `<div class="reg-empty">
        <div class="reg-empty-icon">🎉</div>
        <div class="reg-empty-title">All devices are registered</div>
        <div class="reg-empty-sub">Every HA entity is already in the twin.<br>
          Add real devices in Home Assistant first.</div>
      </div>`;
      countEl.textContent = '';
      return;
    }

    countEl.textContent = shown === total ? `${total}` : `${shown} / ${total}`;

    if (shown === 0) {
      listEl.innerHTML = `<div class="reg-empty">
        <div class="reg-empty-icon">🔍</div>
        <div class="reg-empty-title">No results</div>
        <div class="reg-empty-sub">Try a different search term.</div>
      </div>`;
      return;
    }

    // Group by domain
    const byDomain = new Map();
    for (const d of this._filtered) {
      if (!byDomain.has(d.domain)) byDomain.set(d.domain, []);
      byDomain.get(d.domain).push(d);
    }

    let html = '';
    for (const [domain, devices] of [...byDomain.entries()].sort()) {
      const icon  = DOMAIN_ICONS[domain]  ?? '⚙️';
      const label = DOMAIN_LABELS[domain] ?? domain;
      html += `<div class="reg-domain-group">
        <div class="reg-domain-header">
          <span class="reg-domain-icon">${icon}</span>
          <span class="reg-domain-label">${label}</span>
          <span class="reg-domain-count">${devices.length}</span>
        </div>`;

      for (const d of devices) {
        const displayName = d.name ?? d.entity_id;
        html += `
          <button class="reg-device-row" data-entity="${d.entity_id}">
            <div class="reg-device-main">
              <div class="reg-device-name">${displayName}</div>
              <div class="reg-device-id">${d.entity_id}</div>
            </div>
            <span class="reg-device-arrow">›</span>
          </button>`;
      }
      html += '</div>';
    }

    listEl.innerHTML = html;

    listEl.querySelectorAll('.reg-device-row').forEach(btn => {
      btn.addEventListener('click', () => {
        const device = this._allDevices.get(btn.dataset.entity);
        if (device) this._showConfig(device);
      });
    });
  }

  // ── Step 2: Config ─────────────────────────────────────────────────────────
  _showConfig(device) {
    this._selected = device;

    // Header
    this._modal.querySelector('#reg-title').textContent = 'Configure Device';
    this._modal.querySelector('#reg-back').style.display = '';

    // Selected device preview
    const icon        = DOMAIN_ICONS[device.domain] ?? '⚙️';
    const displayName = device.name ?? device.entity_id;
    this._modal.querySelector('#reg-selected-preview').innerHTML = `
      <div class="reg-preview-icon">${icon}</div>
      <div>
        <div class="reg-preview-name">${displayName}</div>
        <div class="reg-preview-id">${device.entity_id}</div>
      </div>`;

    // Pre-fill display name
    this._modal.querySelector('#reg-display-name').value = displayName;

    // Clear notes
    this._modal.querySelector('#reg-notes').value = '';

    // Populate room dropdown from store
    const roomSelect = this._modal.querySelector('#reg-room');
    const rooms = this.store.getRoomsList().sort((a, b) => a.floor - b.floor || a.name.localeCompare(b.name));
    roomSelect.innerHTML = '<option value="">— No room (unassigned) —</option>' +
      rooms.map(r => `<option value="${r.id}">${r.name} (Floor ${r.floor})</option>`).join('');

    // If device is in a room already (shouldn't be since it's unregistered, but just in case)
    if (device.room_id) roomSelect.value = device.room_id;

    // Show config step
    this._modal.querySelector('#reg-step-list').style.display   = 'none';
    this._modal.querySelector('#reg-step-config').style.display = '';
    this._modal.querySelector('#reg-step-success').style.display = 'none';

    // Focus the name field
    setTimeout(() => this._modal.querySelector('#reg-display-name').focus(), 50);
  }

  _showList() {
    this._modal.querySelector('#reg-title').textContent = 'Add Device to Twin';
    this._modal.querySelector('#reg-back').style.display = 'none';
    this._modal.querySelector('#reg-step-list').style.display   = '';
    this._modal.querySelector('#reg-step-config').style.display = 'none';
    this._modal.querySelector('#reg-step-success').style.display = 'none';
  }

  // ── Step 3: Submit ─────────────────────────────────────────────────────────
  async _submit() {
    const device      = this._selected;
    if (!device) return;

    const displayName = this._modal.querySelector('#reg-display-name').value.trim();
    const roomId      = this._modal.querySelector('#reg-room').value;
    const notes       = this._modal.querySelector('#reg-notes').value.trim();

    const addBtn = this._modal.querySelector('#reg-add-btn');
    addBtn.disabled    = true;
    addBtn.textContent = 'Adding…';

    try {
      const registered = await api.registerDevice({
        entity_id:    device.entity_id,
        display_name: displayName || undefined,
        room_id:      roomId      || undefined,
        notes:        notes       || undefined,
      });

      // Show success briefly
      this._modal.querySelector('#reg-success-name').textContent =
        displayName || device.name || device.entity_id;
      this._modal.querySelector('#reg-step-config').style.display  = 'none';
      this._modal.querySelector('#reg-step-success').style.display = '';

      // Close after short delay then resolve with the registered device
      setTimeout(() => {
        this._close();
        // registered is { ok: true, data: <device> } from the API
        this._resolve?.(registered?.data ?? registered);
        this._resolve = null;
      }, 1200);

    } catch (err) {
      addBtn.disabled    = false;
      addBtn.textContent = 'Add to Twin →';
      // Show inline error
      let errDiv = this._modal.querySelector('.reg-submit-error');
      if (!errDiv) {
        errDiv = document.createElement('div');
        errDiv.className = 'reg-submit-error';
        this._modal.querySelector('.reg-config-footer').before(errDiv);
      }
      errDiv.textContent = `Failed: ${err.message}`;
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  _showLoading(msg) {
    const el = this._modal.querySelector('#reg-loading');
    if (el) el.textContent = msg;
  }

  _showError(msg) {
    const listEl = this._modal.querySelector('#reg-device-list');
    listEl.innerHTML = `<div class="reg-empty">
      <div class="reg-empty-icon">⚠️</div>
      <div class="reg-empty-title">Could not load devices</div>
      <div class="reg-empty-sub">${msg}</div>
      <button class="reg-retry-btn" id="reg-retry">Retry</button>
    </div>`;
    listEl.querySelector('#reg-retry')?.addEventListener('click', () => {
      listEl.innerHTML = '<div class="reg-loading-msg">Loading…</div>';
      this._fetchDevices();
    });
  }

  _cancel() {
    this._close();
    this._resolve?.(null);
    this._resolve = null;
  }

  _close() {
    this._modal.classList.remove('open');
    document.body.style.overflow = '';
    // Reset to list step for next open
    this._showList();
    this._modal.querySelector('#reg-search').value = '';
    const errDiv = this._modal.querySelector('.reg-submit-error');
    if (errDiv) errDiv.remove();
    const addBtn = this._modal.querySelector('#reg-add-btn');
    if (addBtn) { addBtn.disabled = false; addBtn.textContent = 'Add to Twin →'; }
  }
}
