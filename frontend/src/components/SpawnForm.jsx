/**
 * SpawnForm — Type picker + name input + POST /api/vehicles.
 */

import React, { useState } from 'react';
import useVehicleStore from '../store/vehicleStore';

export default function SpawnForm({ onClose }) {
  const [type, setType]       = useState('car');
  const [name, setName]       = useState('');
  const [error, setError]     = useState('');
  const [loading, setLoading] = useState(false);

  const spawnVehicle = useVehicleStore((s) => s.spawnVehicle);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('Name is required');
      return;
    }
    setLoading(true);
    setError('');

    try {
      await spawnVehicle(type, name.trim());
      setName('');
      setType('car');
      if (onClose) onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="spawn-form" onSubmit={handleSubmit} id="spawn-form">
      <label htmlFor="spawn-type">Type</label>
      <select
        id="spawn-type"
        name="type"
        value={type}
        onChange={(e) => setType(e.target.value)}
      >
        <option value="car">car</option>
        <option value="truck">truck</option>
        <option value="bike">bike</option>
        <option value="emergency">emergency</option>
      </select>

      <label htmlFor="spawn-name">Name</label>
      <input
        id="spawn-name"
        type="text"
        name="name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="e.g. Car A"
        maxLength={32}
        autoFocus
      />

      {error && (
        <p style={{ color: 'var(--accent-red)', fontSize: '12px', marginBottom: '8px' }}>
          {error}
        </p>
      )}

      <button
        type="submit"
        className="spawn-submit"
        disabled={loading}
        id="spawn-submit-btn"
      >
        {loading ? 'Spawning...' : 'Spawn OBU'}
      </button>
    </form>
  );
}
