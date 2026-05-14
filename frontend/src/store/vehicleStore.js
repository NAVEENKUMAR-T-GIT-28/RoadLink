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

  // ── Actions ────────────────────────────────────────────────────────────

  setConnected: (val) => set({ connected: val }),

  selectVehicle: (id) => set({ selectedId: id }),

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

    // If selected vehicle was removed, deselect
    let selectedId = state.selectedId;
    if (selectedId && !(selectedId in vehicles)) {
      selectedId = null;
    }

    set({
      vehicles,
      collisionMatrix: collision_matrix || {},
      timestamp:       t,
      trails,
      ttcHistory:      trimmedHistory,
      alertLog,
      selectedId,
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
    const resp = await fetch(`${REST_BASE}/api/vehicles/${id}`, {
      method: 'DELETE',
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Delete failed');
    // Deselect if this was the selected vehicle
    if (get().selectedId === id) {
      set({ selectedId: null });
    }
    return data;
  },
}));

export { WS_URL, RECONNECT_MS };
export default useVehicleStore;
