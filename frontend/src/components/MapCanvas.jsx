/**
 * MapCanvas — Leaflet map with custom vehicle markers, trails, and alert connectors.
 */

import React, { useMemo } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Polyline,
  Popup,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import useVehicleStore from '../store/vehicleStore';

// ── Simulation boundary centre ───────────────────────────────────────────────
const MAP_CENTER = [12.9725, 77.5950];
const MAP_ZOOM   = 17;

// ── Vehicle type colors ──────────────────────────────────────────────────────
const TYPE_COLORS = {
  car:       '#3b82f6',
  truck:     '#14b8a6',
  bike:      '#f97316',
  emergency: '#ef4444',
};

const TYPE_LETTERS = {
  car:       'C',
  truck:     'T',
  bike:      'B',
  emergency: 'E',
};

const ALERT_COLORS = {
  GREEN: null,
  AMBER: '#f59e0b',
  RED:   '#ef4444',
};

// ── Create custom divIcon for a vehicle ──────────────────────────────────────
function makeVehicleIcon(type, alert) {
  const baseColor = ALERT_COLORS[alert] || TYPE_COLORS[type] || '#3b82f6';
  const letter    = TYPE_LETTERS[type] || '?';
  const alertClass = alert === 'RED' ? 'alert-RED' : '';

  return L.divIcon({
    className: '',
    html: `<div class="vehicle-marker-icon ${alertClass}" 
                style="background:${baseColor};">
             ${letter}
           </div>`,
    iconSize:   [28, 28],
    iconAnchor: [14, 14],
  });
}

// ── Trail color (subtle, matching vehicle type) ──────────────────────────────
function trailColor(type) {
  const c = TYPE_COLORS[type] || '#3b82f6';
  return c + '60'; // 60 = ~38% opacity in hex
}

// ── MapUpdater — adjusts bounds when vehicles change ─────────────────────────
function MapUpdater({ vehicles }) {
  const map = useMap();

  const positions = useMemo(() => {
    return Object.values(vehicles)
      .filter((v) => v.lat && v.lon)
      .map((v) => [v.lat, v.lon]);
  }, [vehicles]);

  // Only auto-fit if there are vehicles
  React.useEffect(() => {
    if (positions.length >= 2) {
      const bounds = L.latLngBounds(positions);
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 18 });
    }
  }, [positions.length]); // Only re-fit when count changes

  return null;
}

// ── Main component ───────────────────────────────────────────────────────────
export default function MapCanvas() {
  const vehicles        = useVehicleStore((s) => s.vehicles);
  const collisionMatrix = useVehicleStore((s) => s.collisionMatrix);
  const trails          = useVehicleStore((s) => s.trails);
  const selectedId      = useVehicleStore((s) => s.selectedId);
  const selectVehicle   = useVehicleStore((s) => s.selectVehicle);

  // Compute worst alert per vehicle for icon coloring
  const vehicleAlerts = useMemo(() => {
    const alerts = {};
    for (const id of Object.keys(vehicles)) {
      let worst = 'GREEN';
      for (const [pairKey, data] of Object.entries(collisionMatrix)) {
        if (!pairKey.includes(id)) continue;
        if (data.alert === 'RED') { worst = 'RED'; break; }
        if (data.alert === 'AMBER') worst = 'AMBER';
      }
      alerts[id] = worst;
    }
    return alerts;
  }, [vehicles, collisionMatrix]);

  // RED alert connector lines between pairs
  const redLines = useMemo(() => {
    const lines = [];
    for (const [pairKey, data] of Object.entries(collisionMatrix)) {
      if (data.alert !== 'RED') continue;
      const [idA, idB] = pairKey.split('-');
      const a = vehicles[idA];
      const b = vehicles[idB];
      if (a && b) {
        lines.push({
          key: pairKey,
          positions: [[a.lat, a.lon], [b.lat, b.lon]],
          ttc: data.ttc,
        });
      }
    }
    return lines;
  }, [vehicles, collisionMatrix]);

  return (
    <MapContainer
      center={MAP_CENTER}
      zoom={MAP_ZOOM}
      style={{ height: '100%', width: '100%' }}
      zoomControl={true}
      id="map-container"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      <MapUpdater vehicles={vehicles} />

      {/* Vehicle trails */}
      {Object.entries(trails).map(([id, trail]) => {
        if (!trail || trail.length < 2) return null;
        const v = vehicles[id];
        if (!v) return null;
        return (
          <Polyline
            key={`trail-${id}`}
            positions={trail.map((p) => [p.lat, p.lon])}
            pathOptions={{
              color:   trailColor(v.type),
              weight:  2,
              opacity: 0.6,
            }}
          />
        );
      })}

      {/* RED alert connector lines */}
      {redLines.map((line) => (
        <Polyline
          key={`red-${line.key}`}
          positions={line.positions}
          pathOptions={{
            color:     '#ef4444',
            weight:    2,
            dashArray: '8, 6',
            opacity:   0.8,
          }}
        />
      ))}

      {/* Vehicle markers */}
      {Object.values(vehicles).map((v) => {
        if (!v.lat || !v.lon) return null;
        const alert = vehicleAlerts[v.id] || 'GREEN';

        return (
          <Marker
            key={v.id}
            position={[v.lat, v.lon]}
            icon={makeVehicleIcon(v.type, alert)}
            eventHandlers={{
              click: () => selectVehicle(v.id),
            }}
          >
            <Popup>
              <strong>{v.name}</strong> ({v.type})<br/>
              Speed: {v.spd?.toFixed(1)} m/s<br/>
              Heading: {v.hdg?.toFixed(1)}°
            </Popup>
          </Marker>
        );
      })}
    </MapContainer>
  );
}
