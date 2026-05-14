/**
 * VehicleList — Left sidebar: vehicle rows + Add button + SpawnForm.
 */

import React, { useState } from 'react';
import useVehicleStore from '../store/vehicleStore';
import SpawnForm from './SpawnForm';

export default function VehicleList() {
  const [showForm, setShowForm] = useState(false);

  const vehicles        = useVehicleStore((s) => s.vehicles);
  const collisionMatrix = useVehicleStore((s) => s.collisionMatrix);
  const selectedId      = useVehicleStore((s) => s.selectedId);
  const selectVehicle   = useVehicleStore((s) => s.selectVehicle);

  const vehicleList = Object.values(vehicles);

  /**
   * Compute the worst alert for a single vehicle across all pairs.
   */
  function getWorstAlert(vehicleId) {
    let worst = 'GREEN';
    for (const [pairKey, data] of Object.entries(collisionMatrix)) {
      if (!pairKey.includes(vehicleId)) continue;
      if (data.alert === 'RED') return 'RED';
      if (data.alert === 'AMBER') worst = 'AMBER';
    }
    return worst;
  }

  return (
    <div>
      <div className="sidebar-title">Vehicles</div>

      {vehicleList.length === 0 && (
        <p style={{ color: 'var(--text-muted)', fontSize: '12px', padding: '8px' }}>
          No vehicles running. Click "Add vehicle" to spawn one.
        </p>
      )}

      {vehicleList.map((v) => {
        const alert = getWorstAlert(v.id);
        return (
          <div
            key={v.id}
            id={`vehicle-row-${v.id}`}
            className={`vehicle-row ${selectedId === v.id ? 'selected' : ''}`}
            onClick={() => selectVehicle(v.id)}
          >
            <div className={`vehicle-dot ${v.type}`}></div>
            <div className="vehicle-info">
              <div className="vehicle-name">{v.name}</div>
            </div>
            <span className="vehicle-type-badge">{v.type}</span>
            <span className={`vehicle-alert ${alert}`}>{alert}</span>
          </div>
        );
      })}

      {/* Add vehicle button / form toggle */}
      {!showForm ? (
        <button
          className="spawn-btn"
          onClick={() => setShowForm(true)}
          id="add-vehicle-btn"
        >
          + Add vehicle
        </button>
      ) : (
        <SpawnForm onClose={() => setShowForm(false)} />
      )}
    </div>
  );
}
