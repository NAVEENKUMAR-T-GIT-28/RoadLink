/**
 * DetailPanel — Right sidebar: telemetry, nearby vehicles, TTC chart, alert log.
 *
 * Shows when a vehicle is selected via the map or vehicle list.
 */

import React, { useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer,
} from 'recharts';
import useVehicleStore from '../store/vehicleStore';

function DriveKey({ k, pressed, label }) {
  return (
    <div className={`drive-key ${pressed ? 'pressed' : ''}`}>
      <span className="key-label">{k}</span>
      <span className="key-action">{label}</span>
    </div>
  );
}

export default function DetailPanel() {
  const vehicles        = useVehicleStore((s) => s.vehicles);
  const collisionMatrix = useVehicleStore((s) => s.collisionMatrix);
  const selectedId      = useVehicleStore((s) => s.selectedId);
  const ttcHistory      = useVehicleStore((s) => s.ttcHistory);
  const alertLog        = useVehicleStore((s) => s.alertLog);
  const deleteVehicle   = useVehicleStore((s) => s.deleteVehicle);
  const driveMode       = useVehicleStore((s) => s.driveMode);
  const setDriveMode    = useVehicleStore((s) => s.setDriveMode);
  const driveKeys       = useVehicleStore((s) => s.driveKeys);

  const vehicle = selectedId ? vehicles[selectedId] : null;

  // ── Nearby vehicles sorted by TTC ascending ────────────────────────────
  const nearby = useMemo(() => {
    if (!selectedId) return [];

    const results = [];
    for (const [pairKey, data] of Object.entries(collisionMatrix)) {
      if (!pairKey.includes(selectedId)) continue;
      const [idA, idB] = pairKey.split('-');
      const otherId = idA === selectedId ? idB : idA;
      const other   = vehicles[otherId];
      if (!other) continue;

      results.push({
        id:    otherId,
        name:  other.name,
        type:  other.type,
        alert: data.alert,
        ttc:   data.ttc,
        cpa:   data.cpa,
        dist:  data.dist,
      });
    }

    // Sort by TTC ascending (most dangerous first)
    results.sort((a, b) => a.ttc - b.ttc);
    return results;
  }, [selectedId, vehicles, collisionMatrix]);

  // ── TTC chart data for the most critical pair involving this vehicle ────
  const chartData = useMemo(() => {
    if (!selectedId || nearby.length === 0) return [];

    // Find the most critical pair (lowest TTC)
    const criticalPair = nearby[0];
    if (!criticalPair) return [];

    // Build pair key (lexicographic order)
    const ids = [selectedId, criticalPair.id].sort();
    const pairKey = `${ids[0]}-${ids[1]}`;

    return ttcHistory
      .filter((e) => e.pairKey === pairKey)
      .map((e) => ({
        t:   e.t.toFixed(1),
        ttc: e.ttc >= 9999 ? null : e.ttc,
      }));
  }, [selectedId, nearby, ttcHistory]);

  // ── Relevant alert log entries ─────────────────────────────────────────
  const relevantLog = useMemo(() => {
    if (!selectedId) return [];
    return alertLog
      .filter((e) => e.pair.includes(selectedId))
      .slice(0, 20);
  }, [selectedId, alertLog]);

  // ── Handle delete ──────────────────────────────────────────────────────
  const handleDelete = async () => {
    if (!selectedId) return;
    try {
      await deleteVehicle(selectedId);
    } catch (err) {
      console.error('Delete failed:', err);
    }
  };

  // ── Empty state ────────────────────────────────────────────────────────
  if (!vehicle) {
    return (
      <div className="detail-empty">
        <div className="detail-empty-icon">📡</div>
        <p>Select a vehicle on the map<br/>to view its telemetry</p>
      </div>
    );
  }

  return (
    <div id="detail-panel">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="detail-header">
        <div className="detail-header-info">
          <div className={`vehicle-dot ${vehicle.type}`}></div>
          <div>
            <div className="detail-vehicle-name">{vehicle.name}</div>
            <span className="vehicle-type-badge">{vehicle.type}</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            className={`drive-toggle-btn ${driveMode ? 'active' : ''}`}
            onClick={() => setDriveMode(!driveMode)}
            title={driveMode ? 'Switch to Auto mode' : 'Switch to Drive mode (WASD)'}
            id="drive-mode-btn"
          >
            {driveMode ? '🕹 DRIVE' : '🤖 AUTO'}
          </button>
          <button
            className="delete-btn"
            onClick={handleDelete}
            title="Delete vehicle"
            id="delete-vehicle-btn"
          >
            🗑 Delete
          </button>
        </div>
      </div>

      {/* ── Telemetry ───────────────────────────────────────────────────── */}
      <div className="detail-section">
        <div className="detail-section-title">Telemetry</div>
        <div className="telemetry-grid">
          <div className="telemetry-item">
            <div className="telemetry-label">Latitude</div>
            <div className="telemetry-value">{vehicle.lat?.toFixed(6)}</div>
          </div>
          <div className="telemetry-item">
            <div className="telemetry-label">Longitude</div>
            <div className="telemetry-value">{vehicle.lon?.toFixed(6)}</div>
          </div>
          <div className="telemetry-item">
            <div className="telemetry-label">Speed</div>
            <div className="telemetry-value">{vehicle.spd?.toFixed(1)} m/s</div>
          </div>
          <div className="telemetry-item">
            <div className="telemetry-label">Heading</div>
            <div className="telemetry-value">{vehicle.hdg?.toFixed(1)}°</div>
          </div>
          <div className="telemetry-item">
            <div className="telemetry-label">Brake</div>
            <div className={`telemetry-value ${vehicle.brake ? 'brake-active' : 'brake-off'}`}>
              {vehicle.brake ? 'ACTIVE' : 'OFF'}
            </div>
          </div>
          <div className="telemetry-item">
            <div className="telemetry-label">Tx Rate</div>
            <div className="telemetry-value">{vehicle.tx_rate} Hz</div>
          </div>
        </div>
      </div>

      {/* ── Drive HUD ─────────────────────────────────────────────────── */}
      {driveMode && (
        <div className="drive-hud">
          <div className="drive-hud-title">🕹 Drive Controls</div>
          <div className="drive-key-grid">
            <span />
            <DriveKey k="W" pressed={driveKeys.w} label="Accel" />
            <span />
            <DriveKey k="A" pressed={driveKeys.a} label="Left" />
            <DriveKey k="S" pressed={driveKeys.s} label="Brake" />
            <DriveKey k="D" pressed={driveKeys.d} label="Right" />
          </div>
        </div>
      )}

      {/* ── Nearby Vehicles ─────────────────────────────────────────────── */}
      <div className="detail-section">
        <div className="detail-section-title">
          Nearby Vehicles ({nearby.length})
        </div>
        {nearby.length === 0 && (
          <p style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
            No other vehicles in the simulation.
          </p>
        )}
        {nearby.map((nb) => (
          <div key={nb.id} className="nearby-item">
            <div className="nearby-info">
              <div className={`vehicle-dot ${nb.type}`}></div>
              <span style={{ fontSize: '12px', fontWeight: 600 }}>{nb.name}</span>
              <span className={`vehicle-alert ${nb.alert}`}>{nb.alert}</span>
            </div>
            <div className="nearby-stats">
              <div>
                <div className="nearby-stat-label">TTC</div>
                <div>{nb.ttc >= 9999 ? '∞' : `${nb.ttc}s`}</div>
              </div>
              <div>
                <div className="nearby-stat-label">CPA</div>
                <div>{nb.cpa}m</div>
              </div>
              <div>
                <div className="nearby-stat-label">Dist</div>
                <div>{nb.dist}m</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* ── TTC Chart ───────────────────────────────────────────────────── */}
      {chartData.length > 2 && (
        <div className="detail-section">
          <div className="detail-section-title">TTC History (Critical Pair)</div>
          <div className="chart-container">
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis
                  dataKey="t"
                  stroke="var(--text-muted)"
                  fontSize={10}
                  tickLine={false}
                />
                <YAxis
                  stroke="var(--text-muted)"
                  fontSize={10}
                  tickLine={false}
                  domain={[0, 'auto']}
                />
                <Tooltip
                  contentStyle={{
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    borderRadius: '6px',
                    fontSize: '11px',
                  }}
                />
                <ReferenceLine y={3}  stroke="#ef4444" strokeDasharray="4 4" label="RED" />
                <ReferenceLine y={8}  stroke="#f59e0b" strokeDasharray="4 4" label="AMBER" />
                <Line
                  type="monotone"
                  dataKey="ttc"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={false}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ── Alert Log ───────────────────────────────────────────────────── */}
      {relevantLog.length > 0 && (
        <div className="detail-section">
          <div className="detail-section-title">Alert Log</div>
          <div className="alert-log">
            {relevantLog.map((entry, i) => (
              <div key={i} className="alert-log-entry">
                <span className="time">{entry.t}s</span>
                <span className={`vehicle-alert ${entry.alert}`}>{entry.alert}</span>
                <span>{entry.pair}</span>
                <span>TTC:{entry.ttc >= 9999 ? '∞' : `${entry.ttc}s`}</span>
                <span>{entry.dist}m</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
