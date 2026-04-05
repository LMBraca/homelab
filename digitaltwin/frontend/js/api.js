// api.js — Digital twin REST API wrapper

const BASE = '/api/v1';

async function _get(path) {
  const r = await fetch(`${BASE}${path}?_=${Date.now()}`);
  if (!r.ok) throw new Error(`API ${r.status}: ${path}`);
  return r.json();
}

async function _post(path, body = {}) {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`API ${r.status}: ${path}`);
  return r.json();
}

async function _put(path, body = {}) {
  const r = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`API ${r.status}: ${path}`);
  return r.json();
}

async function _delete(path) {
  const r = await fetch(`${BASE}${path}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`API ${r.status}: ${path}`);
  return r.json();
}

export const api = {
  // Rooms
  rooms:      ()         => _get('/rooms'),
  room:       (id)       => _get(`/rooms/${encodeURIComponent(id)}`),
  createRoom: (body)     => _post('/rooms', body),
  updateRoom: (id, body) => _put(`/rooms/${encodeURIComponent(id)}`, body),
  deleteRoom: (id)       => _delete(`/rooms/${encodeURIComponent(id)}`),

  // Twin devices
  twinDevices: ()  => _get('/twin/devices'),

  // Register a new device into the twin
  registerDevice: (body) => _post('/twin/devices', body),

  // Update twin metadata (room, position_3d, display_name, notes)
  updateTwinDevice: (eid, meta) =>
    _put(`/twin/devices/${encodeURIComponent(eid)}`, meta),

  // Unregister (remove from twin, NOT from HA)
  unregisterDevice: (eid) => _delete(`/twin/devices/${encodeURIComponent(eid)}`),

  // Discovery — unregistered=true lists only devices not yet in the twin
  discover:       (opts = {}) => {
    const params = new URLSearchParams();
    if (opts.unregistered) params.set('unregistered', 'true');
    if (opts.domain)       params.set('domain', opts.domain);
    return _get(`/discover?${params}`);
  },
  discoverDomains: () => _get('/discover/domains'),

  // Live device state + capabilities
  device: (eid) => _get(`/devices/${encodeURIComponent(eid)}`),

  // Control a device — action e.g. "turn_on", "turn_off", "toggle"
  controlDevice: (eid, action, data = {}) =>
    _post(`/devices/${encodeURIComponent(eid)}/control`, { action, ...data }),
};
