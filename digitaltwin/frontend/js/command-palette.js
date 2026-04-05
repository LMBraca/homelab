// command-palette.js — Ctrl+K search palette (Phase 5)
//
// Searches rooms and devices simultaneously.
// Arrow keys to navigate, Enter to select, Escape to close.

const DOMAIN_ICON = {
  light: '💡', switch: '🔌', binary_sensor: '📡', sensor: '🌡',
  lock: '🔒', media_player: '📺', fan: '💨', cover: '🪟',
};

export class CommandPalette {
  constructor(store, onSelectRoom, onSelectDevice) {
    this.store          = store;
    this.onSelectRoom   = onSelectRoom;
    this.onSelectDevice = onSelectDevice;

    this._results = [];   // flat array of { type, id, label, sub, icon }
    this._active  = -1;   // highlighted result index

    this._buildDOM();
  }

  // ── Public ─────────────────────────────────────────────────────────────────
  open() {
    this._el.classList.add('open');
    this._input.value = '';
    this._active = -1;
    this._search('');
    requestAnimationFrame(() => this._input.focus());
  }

  close() {
    this._el.classList.remove('open');
    this._active = -1;
  }

  isOpen() { return this._el.classList.contains('open'); }

  // ── DOM ────────────────────────────────────────────────────────────────────
  _buildDOM() {
    const el = document.createElement('div');
    el.className = 'cp-overlay';
    el.innerHTML = `
      <div class="cp-modal">
        <div class="cp-search-wrap">
          <span class="cp-search-icon">⌕</span>
          <input class="cp-input" type="text"
            placeholder="Search rooms and devices…" autocomplete="off" spellcheck="false">
          <kbd class="cp-esc-hint">esc</kbd>
        </div>
        <div class="cp-results" id="cp-results"></div>
        <div class="cp-footer">
          <span><kbd>↑↓</kbd> navigate</span>
          <span><kbd>↵</kbd> select</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>`;

    document.body.appendChild(el);
    this._el    = el;
    this._input = el.querySelector('.cp-input');

    // Close on backdrop click
    el.addEventListener('click', e => { if (e.target === el) this.close(); });

    // Search on type
    this._input.addEventListener('input', () => this._search(this._input.value));

    // Keyboard navigation
    this._input.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown')  { e.preventDefault(); this._move(1);  }
      if (e.key === 'ArrowUp')    { e.preventDefault(); this._move(-1); }
      if (e.key === 'Enter')      { e.preventDefault(); this._confirm(); }
      if (e.key === 'Escape')     { this.close(); }
    });
  }

  // ── Search ─────────────────────────────────────────────────────────────────
  _search(raw) {
    const q = raw.toLowerCase().trim();
    this._results = [];

    // Rooms
    for (const [, room] of this.store.rooms) {
      if (!q || room.name.toLowerCase().includes(q) || room.id.includes(q)) {
        this._results.push({
          type:  'room',
          id:    room.id,
          label: room.name,
          sub:   `Floor ${room.floor} · ${room.device_count ?? 0} device${room.device_count !== 1 ? 's' : ''}`,
          icon:  `<span class="cp-room-dot" style="background:${room.color ?? '#6366f1'}"></span>`,
          color: room.color ?? '#6366f1',
        });
      }
    }

    // Devices
    for (const [, device] of this.store.devices) {
      const nameMatch   = device.name?.toLowerCase().includes(q);
      const entityMatch = device.entity_id.toLowerCase().includes(q);
      const domainMatch = device.domain?.toLowerCase().includes(q);
      if (!q || nameMatch || entityMatch || domainMatch) {
        const state = device.live?.state ?? '—';
        const bv    = device.live?.brightness_pct;
        const stateStr = (device.domain === 'light' && state === 'on' && bv != null)
          ? `on · ${bv}%`
          : state;
        this._results.push({
          type:  'device',
          id:    device.entity_id,
          label: device.name ?? device.entity_id,
          sub:   `${device.entity_id} · ${stateStr}`,
          icon:  `<span class="cp-device-icon">${DOMAIN_ICON[device.domain] ?? '⚙️'}</span>`,
          state,
          domain: device.domain,
        });
      }
    }

    this._active = this._results.length > 0 ? 0 : -1;
    this._render();
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  _render() {
    const container = this._el.querySelector('#cp-results');

    if (this._results.length === 0) {
      container.innerHTML = `<div class="cp-empty">No results</div>`;
      return;
    }

    // Group header tracking
    let lastType = null;
    let html = '';

    for (let i = 0; i < this._results.length; i++) {
      const r = this._results[i];

      if (r.type !== lastType) {
        html += `<div class="cp-group-label">${r.type === 'room' ? 'Rooms' : 'Devices'}</div>`;
        lastType = r.type;
      }

      const isActive = i === this._active;
      const stateCls = r.state === 'on' ? 'cp-state-on'
                     : r.state === 'off' || r.state === 'unavailable' ? 'cp-state-off'
                     : '';

      html += `
        <div class="cp-result${isActive ? ' active' : ''}" data-index="${i}">
          <div class="cp-result-icon">${r.icon}</div>
          <div class="cp-result-text">
            <div class="cp-result-label">${_highlight(r.label, this._input.value)}</div>
            <div class="cp-result-sub">${r.sub}</div>
          </div>
          ${r.state != null ? `<span class="cp-result-state ${stateCls}">${r.state}</span>` : ''}
        </div>`;
    }

    container.innerHTML = html;

    // Wire click events
    container.querySelectorAll('.cp-result').forEach(el => {
      el.addEventListener('mouseenter', () => {
        this._active = parseInt(el.dataset.index);
        this._highlightActive();
      });
      el.addEventListener('click', () => {
        this._active = parseInt(el.dataset.index);
        this._confirm();
      });
    });

    this._scrollActive();
  }

  // ── Navigation ─────────────────────────────────────────────────────────────
  _move(delta) {
    if (this._results.length === 0) return;
    this._active = (this._active + delta + this._results.length) % this._results.length;
    this._highlightActive();
    this._scrollActive();
  }

  _highlightActive() {
    const container = this._el.querySelector('#cp-results');
    container.querySelectorAll('.cp-result').forEach((el, i) => {
      el.classList.toggle('active', i === this._active);
    });
  }

  _scrollActive() {
    const container = this._el.querySelector('#cp-results');
    const active = container.querySelector('.cp-result.active');
    active?.scrollIntoView({ block: 'nearest' });
  }

  _confirm() {
    if (this._active < 0 || this._active >= this._results.length) return;
    const r = this._results[this._active];
    this.close();
    if (r.type === 'room')   this.onSelectRoom(r.id);
    if (r.type === 'device') this.onSelectDevice(r.id);
  }
}

// Bold the matching portion of the label
function _highlight(text, query) {
  if (!query.trim()) return _esc(text);
  const idx = text.toLowerCase().indexOf(query.toLowerCase().trim());
  if (idx < 0) return _esc(text);
  return _esc(text.slice(0, idx))
    + `<mark class="cp-match">${_esc(text.slice(idx, idx + query.trim().length))}</mark>`
    + _esc(text.slice(idx + query.trim().length));
}

function _esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
