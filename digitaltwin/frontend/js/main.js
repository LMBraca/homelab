// main.js — Boot: viewer + UI + store + API + polling + Phase 5 polish

import { Viewer }         from './viewer.js';
import { UI }             from './ui.js';
import { store }          from './store.js';
import { CommandPalette } from './command-palette.js';

const canvas   = document.getElementById('canvas');
const labelsEl = document.getElementById('labels');

const viewer = new Viewer(canvas, labelsEl);
const ui     = new UI(store, viewer);

// ── Command palette ────────────────────────────────────────────────────────────
const palette = new CommandPalette(
  store,
  roomId   => store.selectRoom(roomId),
  entityId => ui._openPicker(entityId, store.devices.get(entityId)?.room_id),
);

// ── Viewer → store ─────────────────────────────────────────────────────────────
viewer.onRoomClick   = id => store.selectRoom(id);
viewer.onRoomHover   = id => store.emit('roomHovered', { roomId: id });
viewer.onDeviceHover = id => store.emit('deviceHovered', { entityId: id });

// ── Store → viewer ─────────────────────────────────────────────────────────────
store.on('roomSelected', ({ roomId }) => {
  viewer.selectRoom(roomId);
  // Close sidebar on mobile when room selected
  if (window.innerWidth <= 600) _closeSidebar();
});

store.on('dataLoaded', ({ devices, rooms }) => {
  viewer.setRoomFloorMap(rooms);
  viewer.placeDeviceMarkers(devices, rooms);
  ui.rebuildSidebar();
  _buildMobileFloorButtons(rooms);
  document.getElementById('status-msg').textContent =
    `${rooms.size} rooms · ${devices.size} devices`;
});

store.on('devicesUpdated', ({ devices, structureChanged }) => {
  if (structureChanged) {
    viewer.placeDeviceMarkers(devices, store.rooms);
    ui.rebuildSidebar();
  } else {
    viewer.refreshDeviceMarkers(devices);
  }
  if (store.selectedRoomId) ui._showInfoPanel(store.selectedRoomId);
});

viewer.onModelLoaded = () => {
  _modelReady = true;
  if (store.loaded) {
    viewer.placeDeviceMarkers(store.devices, store.rooms);
    ui.rebuildSidebar();
  }
  _checkLoadingDone();
};

// ── Info panel close ───────────────────────────────────────────────────────────
document.getElementById('info-close-btn')?.addEventListener('click', () => {
  document.getElementById('info-panel').classList.remove('open');
  store.selectRoom(null);
});

// ═════════════════════════════════════════════════════════════════════════════
// Loading screen
// ═════════════════════════════════════════════════════════════════════════════

let _modelReady = false;
let _dataReady  = false;

function _checkLoadingDone() {
  if (!_modelReady || !_dataReady) return;
  const screen = document.getElementById('loading-screen');
  if (screen) {
    screen.classList.add('done');
    setTimeout(() => screen.remove(), 600);
  }
}

store.on('dataLoaded', () => { _dataReady = true; _checkLoadingDone(); });

// Failsafe
setTimeout(() => {
  const s = document.getElementById('loading-screen');
  if (s) { s.classList.add('done'); setTimeout(() => s.remove(), 600); }
}, 8000);

function _setLoadingStatus(msg) {
  const el = document.getElementById('ls-status');
  if (el) el.textContent = msg;
}

// ═════════════════════════════════════════════════════════════════════════════
// Time-of-day control
// ═════════════════════════════════════════════════════════════════════════════

let timeMode      = 'real';
let realTimeTimer = null;

const slider      = document.getElementById('time-slider');
const timeDisplay = document.getElementById('sun-clock');
const sunIcon     = document.getElementById('sun-icon');
const modeBtn     = document.getElementById('time-mode-btn');

function _hoursToLabel(h) {
  const m = Math.round((h % 1) * 60);
  return String(Math.floor(h)).padStart(2, '0') + ':' + String(m === 60 ? 0 : m).padStart(2, '0');
}

function _iconForHour(h) {
  if (h >= 6  && h < 8)  return '🌅';
  if (h >= 8  && h < 18) return '☀️';
  if (h >= 18 && h < 20) return '🌇';
  return '🌙';
}

function applyTime(hours) {
  viewer.setSunTime(hours);
  const label = _hoursToLabel(hours);
  const icon  = _iconForHour(hours);
  if (timeDisplay)    timeDisplay.textContent = label;
  if (sunIcon)        sunIcon.textContent     = icon;
  if (slider && timeMode === 'real') slider.value = hours;
  // Sync mobile bottom bar clock
  const mbbClock   = document.getElementById('mbb-clock');
  const mbbSunIcon = document.getElementById('mbb-sun-icon');
  if (mbbClock)   mbbClock.textContent   = label;
  if (mbbSunIcon) mbbSunIcon.textContent = icon;
}

function syncRealTime() {
  const now = new Date();
  applyTime(now.getHours() + now.getMinutes() / 60 + now.getSeconds() / 3600);
}

function startRealTime() {
  timeMode = 'real';
  if (modeBtn) { modeBtn.textContent = '🕐 Real Time'; modeBtn.classList.add('active'); }
  if (slider)  slider.disabled = true;
  syncRealTime();
  realTimeTimer = setInterval(syncRealTime, 60_000);
}

function startManual() {
  timeMode = 'manual';
  if (realTimeTimer) { clearInterval(realTimeTimer); realTimeTimer = null; }
  if (modeBtn) { modeBtn.textContent = '🎚 Manual'; modeBtn.classList.remove('active'); }
  if (slider)  slider.disabled = false;
}

modeBtn?.addEventListener('click', () => timeMode === 'real' ? startManual() : startRealTime());
slider?.addEventListener('input',  () => { if (timeMode === 'manual') applyTime(parseFloat(slider.value)); });

// Mobile: tapping the time button toggles real/manual
document.getElementById('mbb-time-btn')?.addEventListener('click', () => {
  if (timeMode === 'real') {
    startManual();
    if (slider) applyTime(parseFloat(slider.value));
  } else {
    startRealTime();
  }
});

startRealTime();

// ═════════════════════════════════════════════════════════════════════════════
// Connection status
// ═════════════════════════════════════════════════════════════════════════════

const _connDot   = document.getElementById('conn-dot');
const _connLabel = document.getElementById('conn-label');

function _setConnStatus(status) {
  if (!_connDot) return;
  _connDot.className = `conn-dot conn-${status}`;
  if (_connLabel) {
    _connLabel.textContent = status === 'online'   ? 'HA online'
                           : status === 'degraded' ? 'HA degraded'
                                                   : 'HA offline';
  }
}

async function _checkConnection() {
  try {
    const r    = await fetch('/health', { cache: 'no-store' });
    const data = await r.json();
    _setConnStatus(r.ok && data.ha_connected ? 'online' : 'degraded');
  } catch { _setConnStatus('offline'); }
}

_checkConnection();
setInterval(_checkConnection, 30_000);

// ═════════════════════════════════════════════════════════════════════════════
// Mobile sidebar helpers
// ═════════════════════════════════════════════════════════════════════════════

const _sidebar    = document.getElementById('sidebar');
const _hamburger  = document.getElementById('hamburger-btn');

function _openSidebar() {
  _sidebar?.classList.add('mobile-open');
  _hamburger?.setAttribute('aria-expanded', 'true');
}

function _closeSidebar() {
  _sidebar?.classList.remove('mobile-open');
  _hamburger?.setAttribute('aria-expanded', 'false');
}

function _toggleSidebar() {
  _sidebar?.classList.contains('mobile-open') ? _closeSidebar() : _openSidebar();
}

_hamburger?.addEventListener('click', _toggleSidebar);

// Mobile bottom bar — Rooms button
document.getElementById('mbb-rooms-btn')?.addEventListener('click', _openSidebar);

// Mobile bottom bar — Search button
document.getElementById('mbb-search-btn')?.addEventListener('click', () => palette.open());

// ═════════════════════════════════════════════════════════════════════════════
// Mobile floor buttons (bottom bar + sidebar)
// ═════════════════════════════════════════════════════════════════════════════

function _buildMobileFloorButtons(rooms) {
  const floors = [...new Set([...rooms.values()].map(r => r.floor ?? 1))].sort();
  const btns   = [{ val: 0, label: 'All' }, ...floors.map(f => ({ val: f, label: `F${f}` }))];

  // Bottom bar floors
  const mbbFloors = document.getElementById('mbb-floors');
  if (mbbFloors) {
    mbbFloors.innerHTML = btns.map(b =>
      `<button class="mbb-floor-btn${b.val === store.floor ? ' active' : ''}" data-floor="${b.val}">${b.label}</button>`
    ).join('');
    mbbFloors.querySelectorAll('.mbb-floor-btn').forEach(btn => {
      btn.addEventListener('click', () => _setFloor(parseInt(btn.dataset.floor)));
    });
  }

  // Sidebar floor row (mobile: shown via CSS)
  const sidebarFloors = document.getElementById('sidebar-floor-row');
  if (sidebarFloors) {
    sidebarFloors.style.display = '';  // shown always; CSS hides on desktop
    sidebarFloors.innerHTML = btns.map(b =>
      `<button class="fsw-btn${b.val === store.floor ? ' active' : ''}" data-floor="${b.val}">${b.val === 0 ? 'All' : `Floor ${b.val}`}</button>`
    ).join('');
    sidebarFloors.querySelectorAll('.fsw-btn').forEach(btn => {
      btn.addEventListener('click', () => _setFloor(parseInt(btn.dataset.floor)));
    });
  }
}

// Central floor setter — keeps header switcher, mbb, sidebar row all in sync
function _setFloor(floor) {
  store.setFloor(floor);

  // Header floor switcher
  document.querySelectorAll('#floor-switcher .fsw-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.floor) === floor);
  });
  // Mobile bottom bar
  document.querySelectorAll('#mbb-floors .mbb-floor-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.floor) === floor);
  });
  // Sidebar floor row
  document.querySelectorAll('#sidebar-floor-row .fsw-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.floor) === floor);
  });
}

// Also wire the header floor switcher to use _setFloor
store.on('floorChanged', ({ floor }) => viewer.setFloor(floor));

// ═════════════════════════════════════════════════════════════════════════════
// Keyboard shortcuts
// ═════════════════════════════════════════════════════════════════════════════

document.addEventListener('keydown', e => {
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  const anyModalOpen = !!document.querySelector(
    '.cp-overlay.open, .reg-overlay.open, .picker-overlay.open'
  );
  if (anyModalOpen && e.key !== 'Escape') return;

  switch (e.key) {
    case 'Escape':
      if (palette.isOpen()) { palette.close(); break; }
      document.getElementById('info-panel')?.classList.remove('open');
      store.selectRoom(null);
      _closeSidebar();
      break;
    case 'f': case 'F':
      if (store.selectedRoomId) viewer.frameSelected();
      else                      viewer.resetCamera();
      break;
    case '0': _setFloor(0); break;
    case '1': _setFloor(1); break;
    case '2': _setFloor(2); break;
    default:
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        palette.isOpen() ? palette.close() : palette.open();
      }
  }
});

// ═════════════════════════════════════════════════════════════════════════════
// Boot
// ═════════════════════════════════════════════════════════════════════════════

_setLoadingStatus('Connecting to API…');
document.getElementById('status-msg').textContent = 'Connecting to API…';

store.loadData()
  .then(() => {
    _setLoadingStatus('Loading 3D model…');
    store.startPolling(5000);
  })
  .catch(() => {
    _setLoadingStatus('API unavailable — using offline data');
    _dataReady = true;
    _checkLoadingDone();
  });
