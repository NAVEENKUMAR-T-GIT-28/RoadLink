"""
Path Engine — GPS path simulation for each vehicle type.

Each vehicle type has a PathProfile controlling its movement behaviour.
The PathEngine produces realistic GPS coordinates via a constrained random
walk with boundary clamping, smooth heading/speed steering, and per-type
speed ranges, turn aggressiveness, and brake probability.
"""

import math
import random
import time
from dataclasses import dataclass, field
from typing import Tuple


# ── Simulation boundary ─────────────────────────────────────────────────────
# ~500 m × 500 m box around the NH48 corridor in Chennai

BOUNDARY = {
    "lat_min": 12.9700,
    "lat_max": 12.9750,
    "lon_min": 77.5930,
    "lon_max": 77.5970,
}

# Approximate metres per degree at this latitude
METRES_PER_DEG_LAT = 111_320.0
METRES_PER_DEG_LON = 111_320.0 * math.cos(math.radians(12.9725))


# ── Path profile dataclass ──────────────────────────────────────────────────

@dataclass
class PathProfile:
    """Movement characteristics for a vehicle type."""
    speed_min:         float              # m/s — minimum cruise speed
    speed_max:         float              # m/s — maximum speed
    initial_speed:     float              # m/s — starting speed
    turn_rate_max:     float              # °/s — max heading change per second
    turn_interval:     Tuple[float, float]  # seconds between heading decisions
    brake_probability: float              # per-tick probability of brake event
    vehicle_class:     int                # BSM vehicle_cls field


# ── Pre-defined profiles per README spec ─────────────────────────────────────

PROFILES: dict[str, PathProfile] = {
    "car": PathProfile(
        speed_min         = 8.0,
        speed_max         = 25.0,
        initial_speed     = 18.0,
        turn_rate_max     = 45.0,
        turn_interval     = (3, 8),
        brake_probability = 0.08,
        vehicle_class     = 0,
    ),
    "truck": PathProfile(
        speed_min         = 6.0,
        speed_max         = 22.0,
        initial_speed     = 15.0,
        turn_rate_max     = 30.0,
        turn_interval     = (5, 12),
        brake_probability = 0.05,
        vehicle_class     = 1,
    ),
    "bike": PathProfile(
        speed_min         = 4.0,
        speed_max         = 15.0,
        initial_speed     = 10.0,
        turn_rate_max     = 60.0,
        turn_interval     = (2, 6),
        brake_probability = 0.12,
        vehicle_class     = 2,
    ),
    "emergency": PathProfile(
        speed_min         = 15.0,
        speed_max         = 40.0,
        initial_speed     = 30.0,
        turn_rate_max     = 60.0,
        turn_interval     = (2, 5),
        brake_probability = 0.03,
        vehicle_class     = 3,
    ),
}


# ── Path engine ──────────────────────────────────────────────────────────────

class PathEngine:
    """
    Simulates realistic GPS movement for a single vehicle.

    On every tick(dt):
      - Decides whether to change heading (random turn events)
      - Applies boundary clamping (steers toward centre when near edge)
      - Updates speed with small random perturbations
      - Resolves brake events probabilistically
      - Steps lat/lon forward based on speed + heading
    """

    def __init__(self, profile: PathProfile) -> None:
        self.profile = profile

        # Initial position: random point within the boundary
        self.lat = random.uniform(BOUNDARY["lat_min"], BOUNDARY["lat_max"])
        self.lon = random.uniform(BOUNDARY["lon_min"], BOUNDARY["lon_max"])

        # Initial kinematics
        self.speed:   float = profile.initial_speed
        self.heading: float = random.uniform(0, 360)       # degrees, 0=North
        self.accel:   float = 0.0                           # m/s²
        self.brake:   int   = 0                             # 0 or 1

        # Turn scheduling
        self._next_turn_time: float = time.monotonic() + random.uniform(
            *profile.turn_interval
        )
        self._target_heading: float = self.heading

        # Brake event duration tracking
        self._brake_end_time: float = 0.0

    def tick(self, dt: float) -> dict:
        """
        Advance simulation by dt seconds.

        Returns:
            Dict with updated state: lat, lon, speed, heading, accel, brake.
        """
        now = time.monotonic()
        p   = self.profile

        # ── 1. Heading decisions ─────────────────────────────────────────
        if now >= self._next_turn_time:
            # Pick a new target heading within ± turn_rate_max of current
            delta = random.uniform(-p.turn_rate_max, p.turn_rate_max)
            self._target_heading = (self.heading + delta) % 360
            self._next_turn_time = now + random.uniform(*p.turn_interval)

        # ── 2. Boundary clamping ─────────────────────────────────────────
        # If near the edge, steer toward the centre with ±30° offset
        centre_lat = (BOUNDARY["lat_min"] + BOUNDARY["lat_max"]) / 2
        centre_lon = (BOUNDARY["lon_min"] + BOUNDARY["lon_max"]) / 2

        margin_lat = (BOUNDARY["lat_max"] - BOUNDARY["lat_min"]) * 0.15
        margin_lon = (BOUNDARY["lon_max"] - BOUNDARY["lon_min"]) * 0.15

        at_boundary = (
            self.lat < BOUNDARY["lat_min"] + margin_lat
            or self.lat > BOUNDARY["lat_max"] - margin_lat
            or self.lon < BOUNDARY["lon_min"] + margin_lon
            or self.lon > BOUNDARY["lon_max"] - margin_lon
        )

        if at_boundary:
            # Compute bearing toward centre
            dlat = centre_lat - self.lat
            dlon = centre_lon - self.lon
            bearing = math.degrees(math.atan2(dlon, dlat)) % 360
            # Add ±30° random offset to avoid all vehicles heading to same point
            self._target_heading = (bearing + random.uniform(-30, 30)) % 360

        # ── 3. Smooth heading interpolation ──────────────────────────────
        diff = (self._target_heading - self.heading + 540) % 360 - 180
        max_turn = p.turn_rate_max * dt
        if abs(diff) <= max_turn:
            self.heading = self._target_heading
        else:
            self.heading = (self.heading + max_turn * (1 if diff > 0 else -1)) % 360

        # ── 4. Brake events ──────────────────────────────────────────────
        if self.brake == 0 and random.random() < p.brake_probability * dt:
            # Start braking for 1–3 seconds
            self.brake = 1
            self._brake_end_time = now + random.uniform(1.0, 3.0)
        elif self.brake == 1 and now >= self._brake_end_time:
            self.brake = 0

        # ── 5. Speed + acceleration ──────────────────────────────────────
        if self.brake:
            # Decelerate while braking
            target_accel = random.uniform(-4.0, -2.0)
        else:
            # Gentle acceleration / cruise with random perturbation
            target_speed = random.uniform(p.speed_min, p.speed_max)
            target_accel = (target_speed - self.speed) * 0.3

        # Smooth acceleration changes
        self.accel = self.accel * 0.7 + target_accel * 0.3
        self.accel = max(-12.7, min(12.7, self.accel))

        # Apply acceleration to speed
        self.speed += self.accel * dt
        self.speed = max(p.speed_min, min(p.speed_max, self.speed))

        # ── 6. Position step ─────────────────────────────────────────────
        heading_rad  = math.radians(self.heading)
        distance_m   = self.speed * dt

        # North component → latitude, East component → longitude
        d_lat = (distance_m * math.cos(heading_rad)) / METRES_PER_DEG_LAT
        d_lon = (distance_m * math.sin(heading_rad)) / METRES_PER_DEG_LON

        self.lat += d_lat
        self.lon += d_lon

        # Hard clamp to boundary (safety net)
        self.lat = max(BOUNDARY["lat_min"], min(BOUNDARY["lat_max"], self.lat))
        self.lon = max(BOUNDARY["lon_min"], min(BOUNDARY["lon_max"], self.lon))

        return {
            "lat":     self.lat,
            "lon":     self.lon,
            "speed":   self.speed,
            "heading": self.heading,
            "accel":   self.accel,
            "brake":   self.brake,
        }
