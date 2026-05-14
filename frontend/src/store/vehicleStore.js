/**
 * Vehicle Store — Zustand global state for the RoadLink dashboard.
 *
 * Holds:
 *   - vehicles:         Map of vehicle_id → vehicle state
 *   - collisionMatrix:  Map of pair_key → collision data
 *   - selectedId:       Currently selected vehicle ID (for detail panel)
 *   - connected:        WebSocket connection status
 *   - alertLog:         Recent alert events (last 100)
 *   - ttcHistory:       TTC values over time for charting
 */

import { create } from 'zustand';

const WS_URL       = "ws://127.0.0.1:8765";
const REST_BASE    = "http://127.0.0.1:8080";
const RECONNECT_MS = 2000;
const TRAIL_MAX    = 80;
const CHART_WINDOW = 60;    // seconds of TTC history
const MAX_LOG      = 100;

const useVehicleStore = create((set, get) => ({
  // ── State ──────────────────────────────────────────────────────────────
  vehicles:        {},
  collisionMatrix: {},
  selectedId:      null,
  connected:       false,
  timestamp:       0,
  alertLog:        [],
  ttcHistory:      [],       // [{t, pairKey, ttc}, ...]
  trails:          {},       // {vehicleId: [{lat, lon}, ...]}

  // Drive mode state
  driveMode:  false,       // is the selected vehicle in drive mode?
  driveKeys:  { w: false, a: false, s: false, d: false },
  _wsSend:    null,

  // ── Actions ────────────────────────────────────────────────────────────

  setConnected: (val) => set({ connected: val }),

  selectVehicle: (id) => {
    const { driveMode, selectedId, _wsSend } = get();
    // Release previous vehicle from drive mode
    if (driveMode && selectedId && selectedId !== id && _wsSend) {
      _wsSend({ type: "drive_input", id: selectedId, mode: "auto",
                keys: { w: false, a: false, s: false, d: false } });
    }
    set({ selectedId: id, driveMode: false,
          driveKeys: { w: false, a: false, s: false, d: false } });
  },

  /**
   * Process an incoming WebSocket frame from the gateway.
   * Updates vehicles, collision matrix, trails, TTC history, and alert log.
   */
  processFrame: (payload) => {
    const { t, vehicles, collision_matrix } = payload;
    const state = get();

    // Update trails
    const trails = { ...state.trails };
    for (const [id, v] of Object.entries(vehicles)) {
      const prev = trails[id] || [];
      const next = [...prev, { lat: v.lat, lon: v.lon }];
      trails[id] = next.length > TRAIL_MAX ? next.slice(-TRAIL_MAX) : next;
    }

    // Remove trails for vehicles that no longer exist
    for (const id of Object.keys(trails)) {
      if (!(id in vehicles)) {
        delete trails[id];
      }
    }

    // Build TTC history for charting
    const ttcHistory = [...state.ttcHistory];
    for (const [pairKey, data] of Object.entries(collision_matrix || {})) {
      ttcHistory.push({ t: t, pairKey, ttc: data.ttc, alert: data.alert });
    }
    // Trim to chart window
    const cutoff = t - CHART_WINDOW;
    const trimmedHistory = ttcHistory.filter((e) => e.t >= cutoff);

    // Detect alert changes for alert log
    const alertLog = [...state.alertLog];
    const oldMatrix = state.collisionMatrix;
    for (const [pairKey, data] of Object.entries(collision_matrix || {})) {
      const oldAlert = oldMatrix[pairKey]?.alert;
      if (oldAlert && oldAlert !== data.alert) {
        alertLog.unshift({
          t:     t.toFixed(1),
          pair:  pairKey,
          alert: data.alert,
          ttc:   data.ttc,
          dist:  data.dist,
        });
      }
    }
    // Trim log
    if (alertLog.length > MAX_LOG) alertLog.length = MAX_LOG;

    // If selected vehicle was removed, deselect and exit drive mode
    let selectedId = state.selectedId;
    let driveMode  = state.driveMode;
    if (selectedId && !(selectedId in vehicles)) {
      selectedId = null;
      driveMode  = false;
    }

    set({
      vehicles,
      collisionMatrix: collision_matrix || {},
      timestamp:       t,
      trails,
      ttcHistory:      trimmedHistory,
      alertLog,
      selectedId,
      driveMode,
      driveKeys: driveMode ? state.driveKeys : { w: false, a: false, s: false, d: false },
    });
  },

  // ── REST API helpers ───────────────────────────────────────────────────

  spawnVehicle: async (type, name) => {
    const resp = await fetch(`${REST_BASE}/api/vehicles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, name }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Spawn failed');
    return data;
  },

  deleteVehicle: async (id) => {
    const { selectedId, driveMode, _wsSend } = get();
    // If deleting the driven vehicle, release drive mode first
    if (selectedId === id && driveMode && _wsSend) {
      _wsSend({ type: "drive_input", id, mode: "auto",
                keys: { w: false, a: false, s: false, d: false } });
    }
    const resp = await fetch(`${REST_BASE}/api/vehicles/${id}`, {
      method: 'DELETE',
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Delete failed');
    // Deselect if this was the selected vehicle
    if (get().selectedId === id) {
      set({ selectedId: null, driveMode: false,
            driveKeys: { w: false, a: false, s: false, d: false } });
    }
    return data;
  },

  // ── Drive mode actions ──────────────────────────────────────────────────

  setDriveMode: (active) => {
    const { selectedId, _wsSend } = get();
    if (!selectedId) return;

    set({ driveMode: active });

    // Tell the backend immediately when toggling
    if (_wsSend) {
      _wsSend({
        type: "drive_input",
        id:   selectedId,
        mode: active ? "drive" : "auto",
        keys: { w: false, a: false, s: false, d: false },
      });
    }

    // On leaving drive, release all keys
    if (!active) {
      set({ driveKeys: { w: false, a: false, s: false, d: false } });
    }
  },

  setDriveKey: (key, pressed) => {
    const { selectedId, driveMode, driveKeys, _wsSend } = get();
    if (!selectedId || !driveMode) return;

    const newKeys = { ...driveKeys, [key]: pressed };
    set({ driveKeys: newKeys });

    if (_wsSend) {
      _wsSend({
        type: "drive_input",
        id:   selectedId,
        mode: "drive",
        keys: newKeys,
      });
    }
  },

  // Internal: set the WS send function (called from useWS)
  _setWsSend: (fn) => set({ _wsSend: fn }),
}));

export { WS_URL, RECONNECT_MS };
export default useVehicleStore;
