/**
 * useKeyboard — Captures WASD keydown/keyup for drive mode.
 * Only active when selectedId is set and driveMode is true.
 *
 * Also handles browser blur (window losing focus) to release all held keys,
 * preventing stuck-key state when tabbing away.
 */
import { useEffect } from 'react';
import useVehicleStore from '../store/vehicleStore';

const DRIVE_KEYS = new Set(['w', 'a', 's', 'd']);

export default function useKeyboard() {
  const setDriveKey = useVehicleStore((s) => s.setDriveKey);
  const driveMode   = useVehicleStore((s) => s.driveMode);
  const selectedId  = useVehicleStore((s) => s.selectedId);

  useEffect(() => {
    if (!driveMode || !selectedId) return;

    const onKeyDown = (e) => {
      const key = e.key.toLowerCase();
      if (!DRIVE_KEYS.has(key)) return;
      e.preventDefault();          // stop Leaflet map pan
      setDriveKey(key, true);
    };

    const onKeyUp = (e) => {
      const key = e.key.toLowerCase();
      if (!DRIVE_KEYS.has(key)) return;
      e.preventDefault();
      setDriveKey(key, false);
    };

    // Release all keys when the browser tab loses focus
    const onBlur = () => {
      for (const key of DRIVE_KEYS) {
        setDriveKey(key, false);
      }
    };

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup',   onKeyUp);
    window.addEventListener('blur',    onBlur);

    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup',   onKeyUp);
      window.removeEventListener('blur',    onBlur);
    };
  }, [driveMode, selectedId, setDriveKey]);
}
