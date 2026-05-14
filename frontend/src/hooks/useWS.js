/**
 * useWS — WebSocket hook for the RoadLink dashboard.
 *
 * Connects to the gateway WebSocket, sends the handshake,
 * parses incoming JSON frames, and dispatches to the Zustand store.
 * Auto-reconnects on disconnect.
 */

import { useEffect, useRef } from 'react';
import useVehicleStore, { WS_URL, RECONNECT_MS } from '../store/vehicleStore';

export default function useWS() {
  const wsRef        = useRef(null);
  const reconnectRef = useRef(null);

  const setConnected = useVehicleStore((s) => s.setConnected);
  const processFrame = useVehicleStore((s) => s.processFrame);
  const _setWsSend   = useVehicleStore((s) => s._setWsSend);

  useEffect(() => {
    let mounted = true;

    function connect() {
      if (!mounted) return;

      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        // Send dashboard handshake
        ws.send(JSON.stringify({ type: 'dashboard' }));
        setConnected(true);

        // Register send function so the store can push drive_input messages
        _setWsSend((msg) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(msg));
          }
        });
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          processFrame(payload);
        } catch (err) {
          console.warn('[WS] Failed to parse frame:', err);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        _setWsSend(null);   // Clear on disconnect
        // Auto-reconnect
        if (mounted) {
          reconnectRef.current = setTimeout(connect, RECONNECT_MS);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      mounted = false;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [setConnected, processFrame, _setWsSend]);
}
