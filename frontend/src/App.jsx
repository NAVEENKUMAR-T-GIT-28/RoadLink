/**
 * App — Root component and layout for the RoadLink dashboard.
 */

import React from 'react';
import useWS from './hooks/useWS';
import useVehicleStore from './store/vehicleStore';
import AlertBar from './components/AlertBar';
import VehicleList from './components/VehicleList';
import MapCanvas from './components/MapCanvas';
import DetailPanel from './components/DetailPanel';

export default function App() {
  // Establish WebSocket connection
  useWS();

  const connected    = useVehicleStore((s) => s.connected);
  const vehicles     = useVehicleStore((s) => s.vehicles);
  const collisionMatrix = useVehicleStore((s) => s.collisionMatrix);

  const vehicleCount = Object.keys(vehicles).length;

  // Compute worst global alert
  let worstAlert = 'GREEN';
  for (const data of Object.values(collisionMatrix)) {
    if (data.alert === 'RED') { worstAlert = 'RED'; break; }
    if (data.alert === 'AMBER') worstAlert = 'AMBER';
  }

  return (
    <div className="app-layout no-select">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="app-header">
        <div className="header-brand">
          <h1>ROADLINK</h1>
          <span className="version-badge">V2</span>
        </div>

        <div className="header-status">
          <div className="vehicle-count-badge">
            Vehicles: <span>{vehicleCount}</span>
          </div>

          <AlertBar alert={worstAlert} />

          <div className={`status-pill ${connected ? 'live' : 'disconnected'}`}>
            <span className="status-dot"></span>
            {connected ? 'LIVE' : 'DISCONNECTED'}
          </div>
        </div>
      </header>

      {/* ── Left Sidebar: Vehicle List ─────────────────────────────────── */}
      <div className="sidebar-left">
        <VehicleList />
      </div>

      {/* ── Centre: Map ────────────────────────────────────────────────── */}
      <div className="map-area">
        <MapCanvas />
      </div>

      {/* ── Right Sidebar: Detail Panel ────────────────────────────────── */}
      <div className="sidebar-right">
        <DetailPanel />
      </div>
    </div>
  );
}
