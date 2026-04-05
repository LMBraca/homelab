// store.js — Reactive state + API data loading + device polling

import { api }               from './api.js';
import { ROOMS as STATIC_ROOMS } from './rooms.js';

const _listeners = {};

export const store = {
  floor:          0,
  selectedRoomId: null,

  rooms:   new Map(),  // roomId   → room object
  devices: new Map(),  // entityId → device object (with live state)
  loaded:  false,

  _pollTimer: null,

  // ── Event bus ─────────────────────────────────────────────────────────────
  on(event, fn) {
    if (!_listeners[event]) _listeners[event] = [];
    _listeners[event].push(fn);
  },

  emit(event, data) {
    (_listeners[event] || []).forEach(fn => fn(data));
  },

  // ── Actions ───────────────────────────────────────────────────────────────
  setFloor(floor) {
    this.floor = floor;
    this.emit('floorChanged', { floor });
  },

  selectRoom(id) {
    this.selectedRoomId = id;
    this.emit('roomSelected', { roomId: id });
  },

  // ── API bootstrap ─────────────────────────────────────────────────────────
  async loadData() {
    try {
      const [roomsArr, devData] = await Promise.all([
        api.rooms(),
        api.twinDevices(),
      ]);

      this.rooms.clear();
      for (const r of roomsArr) this.rooms.set(r.id, r);

      this.devices.clear();
      for (const d of devData.devices) this.devices.set(d.entity_id, d);

      this._recomputeRoomCounts();
      this.loaded = true;
      this.emit('dataLoaded', { rooms: this.rooms, devices: this.devices });
    } catch (err) {
      console.warn('[store] API unavailable, using static fallback:', err.message);
      this.rooms.clear();
      for (const r of STATIC_ROOMS) this.rooms.set(r.id, { ...r, device_count: r.devices });
      this.loaded = true;
      this.emit('dataLoaded', { rooms: this.rooms, devices: new Map() });
    }
  },

  // ── Full device sync (called by poller every 5s) ───────────────────────────
  // Emits { structureChanged: true } when devices are added/removed or
  // positions/rooms change. Emits { structureChanged: false } for live-state-only
  // changes (on/off, brightness). main.js uses this to decide full rebuild vs
  // fast refresh.
  async refreshDevices() {
    try {
      const devData = await api.twinDevices();
      let liveChanged      = false;
      let structureChanged = false;

      const serverIds = new Set(devData.devices.map(d => d.entity_id));

      // Remove devices no longer on server
      for (const eid of this.devices.keys()) {
        if (!serverIds.has(eid)) {
          this.devices.delete(eid);
          structureChanged = true;
        }
      }

      // Update / add
      for (const d of devData.devices) {
        const prev = this.devices.get(d.entity_id);
        if (!prev) {
          structureChanged = true;
        } else {
          if (JSON.stringify(prev.live)       !== JSON.stringify(d.live))       liveChanged      = true;
          if (JSON.stringify(prev.position_3d) !== JSON.stringify(d.position_3d)) structureChanged = true;
          if (prev.room_id !== d.room_id)                                         structureChanged = true;
        }
        this.devices.set(d.entity_id, d);
      }

      if (liveChanged || structureChanged) {
        this._recomputeRoomCounts();
        this.emit('devicesUpdated', { devices: this.devices, structureChanged });
      }
    } catch { /* silent on poll failure */ }
  },

  // ── Recompute room device counts ──────────────────────────────────────────
  _recomputeRoomCounts() {
    for (const room of this.rooms.values()) room.device_count = 0;
    for (const d of this.devices.values()) {
      if (d.room_id && this.rooms.has(d.room_id)) {
        this.rooms.get(d.room_id).device_count =
          (this.rooms.get(d.room_id).device_count ?? 0) + 1;
      }
    }
  },

  // ── Optimistic add ────────────────────────────────────────────────────────
  addDevice(device) {
    this.devices.set(device.entity_id, device);
    this._recomputeRoomCounts();
    this.emit('devicesUpdated', { devices: this.devices, structureChanged: true });
  },

  // ── Optimistic remove ─────────────────────────────────────────────────────
  removeDevice(entityId) {
    if (!this.devices.has(entityId)) return;
    this.devices.delete(entityId);
    this._recomputeRoomCounts();
    this.emit('devicesUpdated', { devices: this.devices, structureChanged: true });
  },

  // ── Polling ───────────────────────────────────────────────────────────────
  startPolling(ms = 5000) {
    if (this._pollTimer) clearInterval(this._pollTimer);
    this._pollTimer = setInterval(() => this.refreshDevices(), ms);
  },

  // ── Selectors ─────────────────────────────────────────────────────────────
  getDevicesForRoom(roomId) {
    return [...this.devices.values()].filter(d => d.room_id === roomId);
  },

  getRoomById(id)  { return this.rooms.get(id); },
  getRoomsList()   { return [...this.rooms.values()]; },
};
