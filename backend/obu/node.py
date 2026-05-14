"""
OBU Node — On-Board Unit simulation thread.

Each OBUNode behaves like embedded firmware running on a vehicle:
  - path_engine.tick(dt) generates realistic GPS movement
  - tx_loop broadcasts BSM frames over UDP at 2–10 Hz
  - rx_loop receives BSM frames from all other OBUs and updates
    a local neighbour table

One Python thread per vehicle. Started/stopped by the gateway.
"""

import logging
import math
import os
import random
import socket
import struct
import sys
import threading
import time
from typing import Optional

# Resolve imports relative to the backend package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bsm_codec import encode, decode, FRAME_SIZE
from obu.path_engine import PathEngine, PROFILES, BOUNDARY, METRES_PER_DEG_LAT, METRES_PER_DEG_LON

logger = logging.getLogger("obu")


# ── Drive Physics helper ─────────────────────────────────────────────────────

class DrivePhysics:
    """
    Converts WASD key-press state into lat/lon/heading/speed updates.

    W = accelerate forward
    S = brake / reverse
    A = turn left
    D = turn right
    """

    ACCEL_RATE   = 4.0    # m/s² when W held
    BRAKE_RATE   = 6.0    # m/s² deceleration when S held
    TURN_RATE    = 60.0   # °/s when A or D held
    MAX_SPEED    = 20.0   # m/s cap for manual drive
    MIN_SPEED    = 0.0    # can stop completely

    def __init__(self, lat: float, lon: float, heading: float, speed: float) -> None:
        self.lat     = lat
        self.lon     = lon
        self.heading = heading
        self.speed   = speed

    def tick(self, dt: float, keys: dict) -> dict:
        """
        Advance physics by dt seconds given the currently held keys.

        keys: { "w": bool, "a": bool, "s": bool, "d": bool }
        Returns updated state dict.
        """
        w = keys.get("w", False)
        a = keys.get("a", False)
        s = keys.get("s", False)
        d = keys.get("d", False)

        # ── Turning (only when moving) ────────────────────────────────────
        if self.speed > 0.5:
            if a:
                self.heading = (self.heading - self.TURN_RATE * dt) % 360
            if d:
                self.heading = (self.heading + self.TURN_RATE * dt) % 360

        # ── Speed / acceleration ──────────────────────────────────────────
        if w and not s:
            self.speed = min(self.MAX_SPEED, self.speed + self.ACCEL_RATE * dt)
            accel = self.ACCEL_RATE
            brake = 0
        elif s and not w:
            self.speed = max(self.MIN_SPEED, self.speed - self.BRAKE_RATE * dt)
            accel = -self.BRAKE_RATE
            brake = 1
        else:
            # Coast — gentle friction
            self.speed = max(self.MIN_SPEED, self.speed - 1.5 * dt)
            accel = 0.0
            brake = 0

        # ── Position step ─────────────────────────────────────────────────
        heading_rad = math.radians(self.heading)
        distance_m  = self.speed * dt

        d_lat = (distance_m * math.cos(heading_rad)) / METRES_PER_DEG_LAT
        d_lon = (distance_m * math.sin(heading_rad)) / METRES_PER_DEG_LON

        self.lat += d_lat
        self.lon += d_lon

        # Clamp to boundary
        self.lat = max(BOUNDARY["lat_min"], min(BOUNDARY["lat_max"], self.lat))
        self.lon = max(BOUNDARY["lon_min"], min(BOUNDARY["lon_max"], self.lon))

        return {
            "lat":     self.lat,
            "lon":     self.lon,
            "speed":   self.speed,
            "heading": self.heading,
            "accel":   accel,
            "brake":   brake,
        }


# ── Configuration ────────────────────────────────────────────────────────────

BSM_BROADCAST_ADDR = ("127.0.0.1", 5005)
TICK_RATE_NORMAL   = 2          # Hz — base broadcast frequency
TICK_RATE_BRAKE    = 10         # Hz — elevated during brake events
RX_BUFFER_SIZE     = 64         # bytes — BSM frame is 28, headroom for safety
TRAIL_HISTORY      = 80         # positions to keep for map trail


class OBUNode:
    """
    Simulates a single vehicle On-Board Unit.

    Lifecycle:
        node = OBUNode(name="Car A", vehicle_type="car", vehicle_id=0xA001)
        node.start()    # spawns tx + rx threads
        ...
        node.stop()     # signals graceful shutdown, blocks until threads exit
    """

    def __init__(
        self,
        name:         str,
        vehicle_type: str,
        vehicle_id:   int,
        registry_id:  str,
    ) -> None:
        """
        Args:
            name:         Human-readable vehicle name (e.g. "Car A").
            vehicle_type: One of "car", "truck", "bike", "emergency".
            vehicle_id:   Numeric ID embedded in BSM frames (uint32).
            registry_id:  Short hex ID used in the gateway registry.
        """
        if vehicle_type not in PROFILES:
            raise ValueError(f"Unknown vehicle type: {vehicle_type}")

        self.name         = name
        self.vehicle_type = vehicle_type
        self.vehicle_id   = vehicle_id
        self.registry_id  = registry_id

        # Path engine for this vehicle's profile
        profile           = PROFILES[vehicle_type]
        self.path_engine  = PathEngine(profile)
        self.vehicle_class = profile.vehicle_class

        # State tracking
        self._start_time:  float = 0.0
        self._state:       dict  = {}
        self._trail:       list  = []
        self._neighbours:  dict  = {}   # vehicle_id → latest decoded BSM

        # ── Drive override (manual control) ──────────────────────────────
        # When mode == "drive", the path engine is frozen and DrivePhysics
        # is used instead.  keys dict is updated by set_drive_override().
        self._drive_lock     = threading.Lock()
        self._drive_override = {
            "mode": "auto",        # "auto" | "drive"
            "keys": {"w": False, "a": False, "s": False, "d": False},
        }
        self._drive_physics: Optional[DrivePhysics] = None

        # Threading
        self._stop_event = threading.Event()
        self._tx_thread: Optional[threading.Thread] = None
        self._rx_thread: Optional[threading.Thread] = None

        # UDP socket — shared between tx and rx
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Allow receiving broadcast on the same port
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.settimeout(0.5)  # non-blocking rx with 500ms timeout

    # ── Public API ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the OBU — spawns tx and rx threads."""
        self._start_time = time.monotonic()
        self._stop_event.clear()

        self._tx_thread = threading.Thread(
            target=self._tx_loop, name=f"OBU-TX-{self.name}", daemon=True
        )
        self._rx_thread = threading.Thread(
            target=self._rx_loop, name=f"OBU-RX-{self.name}", daemon=True
        )
        self._tx_thread.start()
        self._rx_thread.start()
        logger.info(f"[OBU] {self.name} started (id={self.registry_id}, vid={self.vehicle_id})")

    def stop(self) -> None:
        """Signal the OBU to stop and wait for threads to exit."""
        self._stop_event.set()
        if self._tx_thread and self._tx_thread.is_alive():
            self._tx_thread.join(timeout=2.0)
        if self._rx_thread and self._rx_thread.is_alive():
            self._rx_thread.join(timeout=2.0)
        try:
            self._sock.close()
        except OSError:
            pass
        logger.info(f"[OBU] {self.name} stopped")

    @property
    def is_running(self) -> bool:
        return not self._stop_event.is_set()

    @property
    def state(self) -> dict:
        """Current vehicle state for the registry."""
        return dict(self._state)

    @property
    def trail(self) -> list:
        """Position history for map trail rendering."""
        return list(self._trail)

    @property
    def neighbours(self) -> dict:
        """Local neighbour table built from received BSM frames."""
        return dict(self._neighbours)

    @property
    def tx_rate(self) -> int:
        """Current BSM broadcast rate in Hz."""
        return TICK_RATE_BRAKE if self._state.get("brake", 0) else TICK_RATE_NORMAL

    def set_drive_override(self, mode: str, keys: dict) -> None:
        """
        Switch between auto-pilot and manual drive mode.

        Args:
            mode: "auto" or "drive"
            keys: dict with boolean flags for w, a, s, d (used when mode=="drive")
        """
        with self._drive_lock:
            prev_mode = self._drive_override["mode"]
            self._drive_override["mode"] = mode
            self._drive_override["keys"] = keys

            # When first entering drive mode, seed DrivePhysics from current state
            if mode == "drive" and prev_mode != "drive":
                s = self._state
                self._drive_physics = DrivePhysics(
                    lat     = s.get("lat",  12.9725),
                    lon     = s.get("lon",  77.5950),
                    heading = s.get("hdg",  0.0),
                    speed   = s.get("spd",  0.0),
                )
                logger.info(f"[OBU] {self.name} → DRIVE mode")

            elif mode == "auto" and prev_mode == "drive":
                self._drive_physics = None
                logger.info(f"[OBU] {self.name} → AUTO mode")

    # ── TX loop ──────────────────────────────────────────────────────────

    def _tx_loop(self) -> None:
        """
        Transmit loop — ticks the path engine and broadcasts a BSM frame.

        Runs at TICK_RATE_NORMAL Hz normally, escalates to TICK_RATE_BRAKE Hz
        when the vehicle is braking (per README spec).
        """
        last_tick = time.monotonic()

        while not self._stop_event.is_set():
            now = time.monotonic()
            dt  = now - last_tick
            last_tick = now

            # Branch on drive mode vs auto mode
            with self._drive_lock:
                override = dict(self._drive_override)

            if override["mode"] == "drive" and self._drive_physics is not None:
                state = self._drive_physics.tick(dt, override["keys"])
            else:
                state = self.path_engine.tick(dt)

            # Compute timestamp relative to node start
            timestamp_ms = int((now - self._start_time) * 1000)

            # Update internal state
            self._state = {
                "id":           self.registry_id,
                "name":         self.name,
                "type":         self.vehicle_type,
                "lat":          state["lat"],
                "lon":          state["lon"],
                "spd":          round(state["speed"], 2),
                "hdg":          round(state["heading"], 1),
                "accel":        round(state["accel"], 2),
                "brake":        state["brake"],
                "tx_rate":      self.tx_rate,
                "timestamp_ms": timestamp_ms,
            }

            # Append to trail history
            self._trail.append({"lat": state["lat"], "lon": state["lon"]})
            if len(self._trail) > TRAIL_HISTORY:
                self._trail = self._trail[-TRAIL_HISTORY:]

            # Encode BSM frame
            frame = encode(
                vehicle_id    = self.vehicle_id,
                lat           = state["lat"],
                lon           = state["lon"],
                speed_mps     = state["speed"],
                heading_deg   = state["heading"],
                accel_ms2     = state["accel"],
                brake         = state["brake"],
                vehicle_class = self.vehicle_class,
                timestamp_ms  = timestamp_ms,
            )

            # Broadcast over UDP
            try:
                self._sock.sendto(frame, BSM_BROADCAST_ADDR)
            except OSError as e:
                logger.warning(f"[OBU] {self.name} TX error: {e}")

            # Sleep for the tick interval
            rate = TICK_RATE_BRAKE if state["brake"] else TICK_RATE_NORMAL
            interval = 1.0 / rate
            # Subtract elapsed processing time
            elapsed = time.monotonic() - now
            sleep_time = max(0.01, interval - elapsed)
            self._stop_event.wait(sleep_time)

    # ── RX loop ──────────────────────────────────────────────────────────

    def _rx_loop(self) -> None:
        """
        Receive loop — listens for BSM frames from other OBUs
        and updates the local neighbour table.
        """
        while not self._stop_event.is_set():
            try:
                data, addr = self._sock.recvfrom(RX_BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    break
                continue

            # Decode the frame
            decoded = decode(data)
            if decoded is None:
                continue

            # Skip our own frames
            if decoded["vehicle_id"] == self.vehicle_id:
                continue

            # Update neighbour table
            self._neighbours[decoded["vehicle_id"]] = {
                "lat":          decoded["lat"],
                "lon":          decoded["lon"],
                "spd":          decoded["spd"],
                "hdg":          decoded["hdg"],
                "accel":        decoded["accel"],
                "brake":        decoded["brake"],
                "timestamp_ms": decoded["timestamp_ms"],
                "last_seen":    time.monotonic(),
            }