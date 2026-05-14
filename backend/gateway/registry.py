"""
Vehicle Registry — spawn, kill, update, and query OBU nodes.

Maintains an in-memory dict mapping registry_id → vehicle state.
The gateway reads from this registry to build WebSocket payloads.
OBU nodes are spawned/stopped through this registry.
"""

import logging
import os
import random
import sys
import threading
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from obu.node import OBUNode

logger = logging.getLogger("registry")

# Valid vehicle types accepted by the REST API
VALID_TYPES = {"car", "truck", "bike", "emergency"}

# Maximum concurrent OBU threads (safety limit)
MAX_VEHICLES = 20


class VehicleRegistry:
    """
    Thread-safe registry of all active OBU nodes.

    Provides spawn/kill/update/get operations used by the gateway.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, OBUNode]  = {}   # registry_id → OBUNode
        self._names: Dict[str, str]      = {}   # name → registry_id (uniqueness)
        self._lock  = threading.Lock()

    # ── Spawn ────────────────────────────────────────────────────────────

    def spawn(self, name: str, vehicle_type: str) -> Dict[str, Any]:
        """
        Create and start a new OBU node.

        Args:
            name:         Human-readable vehicle name.
            vehicle_type: One of VALID_TYPES.

        Returns:
            Dict with id, name, type, vehicle_id, status.

        Raises:
            ValueError: On invalid type, empty name, duplicate name, or capacity limit.
        """
        if vehicle_type not in VALID_TYPES:
            raise ValueError("invalid type")

        if not name or not name.strip():
            raise ValueError("name required")

        name = name.strip()[:32]  # Max 32 chars per spec

        with self._lock:
            if name in self._names:
                raise ValueError("name already exists")

            if len(self._nodes) >= MAX_VEHICLES:
                raise ValueError(f"max vehicles ({MAX_VEHICLES}) reached")

            # Generate unique IDs
            registry_id = self._generate_registry_id()
            vehicle_id  = random.randint(0x1000, 0xFFFF)

            # Create and start the OBU node
            node = OBUNode(
                name         = name,
                vehicle_type = vehicle_type,
                vehicle_id   = vehicle_id,
                registry_id  = registry_id,
            )
            node.start()

            self._nodes[registry_id] = node
            self._names[name]        = registry_id

            logger.info(f"[Registry] Spawned {name} ({vehicle_type}) as {registry_id}")

            return {
                "id":         registry_id,
                "name":       name,
                "type":       vehicle_type,
                "vehicle_id": vehicle_id,
                "status":     "running",
            }

    # ── Kill ─────────────────────────────────────────────────────────────

    def kill(self, registry_id: str) -> Optional[Dict[str, Any]]:
        """
        Stop and remove an OBU node.

        Returns:
            Dict with id, name, status on success, or None if not found.
        """
        with self._lock:
            node = self._nodes.pop(registry_id, None)
            if node is None:
                return None

            # Remove name mapping
            self._names.pop(node.name, None)

        # Stop outside the lock to avoid blocking
        node.stop()
        logger.info(f"[Registry] Killed {node.name} ({registry_id})")

        return {
            "id":     registry_id,
            "name":   node.name,
            "status": "stopped",
        }

    # ── Drive override ──────────────────────────────────────────────────

    def set_drive_override(self, registry_id: str, mode: str, keys: dict) -> None:
        """
        Route a drive_input WebSocket message to the correct OBU node.

        Args:
            registry_id: The hex registry ID of the target vehicle.
            mode: "auto" or "drive"
            keys: {"w": bool, "a": bool, "s": bool, "d": bool}
        """
        with self._lock:
            node = self._nodes.get(registry_id)
        if node:
            node.set_drive_override(mode, keys)

    # ── Query ────────────────────────────────────────────────────────────

    def get_all_states(self) -> Dict[str, Dict]:
        """
        Return a snapshot of all vehicle states for the WebSocket payload.

        Returns:
            Dict mapping registry_id → vehicle state dict.
        """
        with self._lock:
            nodes = dict(self._nodes)

        result = {}
        for rid, node in nodes.items():
            state = node.state
            if state:
                result[rid] = state
        return result

    def list_vehicles(self) -> list:
        """Return a list of all vehicle summaries for the REST API."""
        with self._lock:
            nodes = dict(self._nodes)

        return [
            {
                "id":         rid,
                "name":       node.name,
                "type":       node.vehicle_type,
                "vehicle_id": node.vehicle_id,
            }
            for rid, node in nodes.items()
        ]

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._nodes)

    def has_name(self, name: str) -> bool:
        with self._lock:
            return name in self._names

    # ── Internal ─────────────────────────────────────────────────────────

    def _generate_registry_id(self) -> str:
        """Generate a short unique hex ID (6 chars)."""
        while True:
            rid = f"{random.randint(0, 0xFFFFFF):06x}"
            if rid not in self._nodes:
                return rid

    def shutdown_all(self) -> None:
        """Stop all OBU nodes (used during gateway shutdown)."""
        with self._lock:
            nodes = dict(self._nodes)
            self._nodes.clear()
            self._names.clear()

        for rid, node in nodes.items():
            node.stop()
        logger.info("[Registry] All vehicles stopped")
