"""
Collision Engine — Haversine, TTC, CPA, all-pairs computation, alert levels.

This is the single source of truth for all safety math. Imported by the
gateway (online, real-time) and the test validator (offline).
"""

import math
from itertools import combinations
from typing import Dict, Any

# ── Alert thresholds ─────────────────────────────────────────────────────────

TTC_RED       = 3.0     # seconds
TTC_AMBER     = 8.0     # seconds
CPA_RED       = 30.0    # metres
CPA_AMBER     = 80.0    # metres
CPA_LOOKAHEAD = 5.0     # seconds of trajectory to sample
CPA_STEP_S    = 0.5     # sampling interval within lookahead window

# Earth radius in metres (mean)
_R_EARTH = 6_371_000.0


# ── Haversine distance ───────────────────────────────────────────────────────

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Compute great-circle distance between two GPS coordinates in metres.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return _R_EARTH * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Velocity vector from speed + heading ─────────────────────────────────────

def _velocity_xy(speed_mps: float, heading_deg: float):
    """
    Convert speed + compass heading to (vx, vy) in m/s.
    vx = East component, vy = North component.
    """
    h = math.radians(heading_deg)
    return speed_mps * math.sin(h), speed_mps * math.cos(h)


def _pos_xy(lat: float, lon: float, ref_lat: float, ref_lon: float):
    """
    Convert GPS to local (x, y) metres relative to a reference point.
    """
    y = (lat - ref_lat) * 111_320.0
    x = (lon - ref_lon) * 111_320.0 * math.cos(math.radians(ref_lat))
    return x, y


# ── Time To Collision (TTC) ──────────────────────────────────────────────────

def compute_ttc(
    ego_lat: float, ego_lon: float, ego_spd: float, ego_hdg: float,
    nb_lat:  float, nb_lon:  float, nb_spd:  float, nb_hdg:  float,
) -> float:
    """
    Compute TTC using the closing-velocity method.

    TTC = -(r · v_rel) / |v_rel|²

    Returns float('inf') when vehicles are diverging or stationary.
    """
    ref_lat = (ego_lat + nb_lat) / 2
    ref_lon = (ego_lon + nb_lon) / 2

    ex, ey = _pos_xy(ego_lat, ego_lon, ref_lat, ref_lon)
    nx, ny = _pos_xy(nb_lat,  nb_lon,  ref_lat, ref_lon)

    # Relative position: r = nb_pos - ego_pos
    rx, ry = nx - ex, ny - ey

    evx, evy = _velocity_xy(ego_spd, ego_hdg)
    nvx, nvy = _velocity_xy(nb_spd, nb_hdg)

    # Relative velocity: v_rel = nb_vel - ego_vel
    vrx, vry = nvx - evx, nvy - evy

    vrel_sq = vrx * vrx + vry * vry
    if vrel_sq < 1e-6:
        return float("inf")  # Effectively stationary relative to each other

    r_dot_v = rx * vrx + ry * vry
    ttc = -(r_dot_v) / vrel_sq

    if ttc <= 0:
        return float("inf")  # Diverging

    return ttc


# ── Closest Point of Approach (CPA) ─────────────────────────────────────────

def compute_cpa(
    ego_lat: float, ego_lon: float, ego_spd: float, ego_hdg: float,
    nb_lat:  float, nb_lon:  float, nb_spd:  float, nb_hdg:  float,
    lookahead: float = CPA_LOOKAHEAD,
    step_s:    float = CPA_STEP_S,
) -> float:
    """
    Sample projected positions over a lookahead window and return
    the minimum pairwise distance in metres.
    """
    ref_lat = (ego_lat + nb_lat) / 2
    ref_lon = (ego_lon + nb_lon) / 2

    ex, ey = _pos_xy(ego_lat, ego_lon, ref_lat, ref_lon)
    nx, ny = _pos_xy(nb_lat,  nb_lon,  ref_lat, ref_lon)

    evx, evy = _velocity_xy(ego_spd, ego_hdg)
    nvx, nvy = _velocity_xy(nb_spd, nb_hdg)

    min_dist = float("inf")
    t = 0.0

    while t <= lookahead:
        # Project positions forward
        px_e = ex + evx * t
        py_e = ey + evy * t
        px_n = nx + nvx * t
        py_n = ny + nvy * t

        dx = px_n - px_e
        dy = py_n - py_e
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < min_dist:
            min_dist = dist

        t += step_s

    return min_dist


# ── Alert level classification ───────────────────────────────────────────────

def alert_level(ttc: float, cpa: float) -> str:
    """
    Classify alert level based on TTC and CPA.

    Both conditions must be simultaneously true for a level to apply.

    RED:   TTC < 3s  AND CPA < 30m
    AMBER: TTC < 8s  AND CPA < 80m
    GREEN: otherwise
    """
    if ttc < TTC_RED and cpa < CPA_RED:
        return "RED"
    if ttc < TTC_AMBER and cpa < CPA_AMBER:
        return "AMBER"
    return "GREEN"


# ── All-pairs computation ───────────────────────────────────────────────────

def compute_all_pairs(registry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute TTC, CPA, distance, and alert level for every unique pair.

    Input:
        registry = { vehicle_id: {lat, lon, spd, hdg, ...}, ... }

    Output:
        matrix = { 'idA-idB': {dist, ttc, cpa, alert}, ... }

    Pair key: "{lower_id}-{higher_id}" (lexicographic order).
    """
    matrix: Dict[str, Any] = {}
    ids = sorted(registry.keys())

    for id_a, id_b in combinations(ids, 2):
        a = registry[id_a]
        b = registry[id_b]

        # Current separation distance
        dist = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])

        # TTC via closing-velocity method
        ttc = compute_ttc(
            a["lat"], a["lon"], a["spd"], a["hdg"],
            b["lat"], b["lon"], b["spd"], b["hdg"],
        )

        # CPA via trajectory sampling
        cpa = compute_cpa(
            a["lat"], a["lon"], a["spd"], a["hdg"],
            b["lat"], b["lon"], b["spd"], b["hdg"],
        )

        # Cap TTC for JSON serialization (inf → 9999)
        ttc_wire = 9999.0 if math.isinf(ttc) else round(ttc, 2)

        pair_key = f"{id_a}-{id_b}"
        matrix[pair_key] = {
            "dist":  round(dist, 1),
            "ttc":   ttc_wire,
            "cpa":   round(cpa, 1),
            "alert": alert_level(ttc, cpa),
        }

    return matrix
