"""
Collision Validation Suite — 6-scenario offline test.

Runs pre-defined scenarios against the collision engine to verify
the haversine, TTC, CPA, and alert classification math.
Saves trajectory plots to tests/collision_validation.png.
"""

import math
import os
import sys

# Resolve imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from collision_engine.engine import (  # type: ignore
    haversine_m,
    compute_ttc,
    compute_cpa,
    alert_level,
    compute_all_pairs,
)


# ── Test scenarios ───────────────────────────────────────────────────────────

SCENARIOS = [
    {
        "name": "Head-on collision — close, converging fast",
        "ego":  {"lat": 12.9725, "lon": 77.5945, "spd": 20.0, "hdg": 90.0},
        "nb":   {"lat": 12.9725, "lon": 77.5955, "spd": 20.0, "hdg": 270.0},
        "expected_alert": "RED",
    },
    {
        "name": "Same direction — following closely",
        "ego":  {"lat": 12.9725, "lon": 77.5945, "spd": 20.0, "hdg": 90.0},
        "nb":   {"lat": 12.9725, "lon": 77.5947, "spd": 15.0, "hdg": 90.0},
        "expected_alert": "RED",
    },
    {
        "name": "Perpendicular crossing — near miss",
        "ego":  {"lat": 12.9720, "lon": 77.5950, "spd": 15.0, "hdg": 0.0},
        "nb":   {"lat": 12.9725, "lon": 77.5945, "spd": 15.0, "hdg": 90.0},
        "expected_alert": "AMBER",
    },
    {
        "name": "Diverging — moving apart",
        "ego":  {"lat": 12.9725, "lon": 77.5945, "spd": 20.0, "hdg": 0.0},
        "nb":   {"lat": 12.9725, "lon": 77.5955, "spd": 20.0, "hdg": 180.0},
        "expected_alert": "GREEN",
    },
    {
        "name": "Far apart — safe separation",
        "ego":  {"lat": 12.9700, "lon": 77.5930, "spd": 10.0, "hdg": 45.0},
        "nb":   {"lat": 12.9750, "lon": 77.5970, "spd": 10.0, "hdg": 225.0},
        "expected_alert": "GREEN",
    },
    {
        "name": "Stationary vehicles — parked side by side",
        "ego":  {"lat": 12.9725, "lon": 77.5950, "spd": 0.0, "hdg": 0.0},
        "nb":   {"lat": 12.9725, "lon": 77.5951, "spd": 0.0, "hdg": 0.0},
        "expected_alert": "GREEN",
    },
]


def run_scenarios():
    """Run all scenarios and print results."""
    print("=" * 70)
    print("  ROADLINK V2 — Collision Engine Validation")
    print("=" * 70)
    print()

    passed = 0
    failed = 0

    for i, sc in enumerate(SCENARIOS, 1):
        ego = sc["ego"]
        nb  = sc["nb"]

        dist = haversine_m(ego["lat"], ego["lon"], nb["lat"], nb["lon"])
        ttc  = compute_ttc(
            ego["lat"], ego["lon"], ego["spd"], ego["hdg"],
            nb["lat"],  nb["lon"],  nb["spd"],  nb["hdg"],
        )
        cpa  = compute_cpa(
            ego["lat"], ego["lon"], ego["spd"], ego["hdg"],
            nb["lat"],  nb["lon"],  nb["spd"],  nb["hdg"],
        )
        level = alert_level(ttc, cpa)

        ttc_str = f"{ttc:.2f}s" if not math.isinf(ttc) else "∞"
        ok = level == sc["expected_alert"]

        status = "✓ PASS" if ok else "✗ FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"  Scenario {i}: {sc['name']}")
        print(f"    Distance:  {dist:.1f} m")
        print(f"    TTC:       {ttc_str}")
        print(f"    CPA:       {cpa:.1f} m")
        print(f"    Alert:     {level} (expected: {sc['expected_alert']})")
        print(f"    Result:    {status}")
        print()

    print("-" * 70)
    print(f"  Results: {passed} passed, {failed} failed, {len(SCENARIOS)} total")
    print("-" * 70)

    return failed == 0


def generate_plots():
    """Generate trajectory plots for each scenario."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("  [!] matplotlib/numpy not installed — skipping plots.")
        return

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle("RoadLink V2 — Collision Validation Scenarios", fontsize=14)
    axes = axes.flatten()

    for i, sc in enumerate(SCENARIOS):
        ax  = axes[i]
        ego = sc["ego"]
        nb  = sc["nb"]

        # Project trajectories over 5 seconds
        t_steps = np.linspace(0, 5, 50)

        ego_lats, ego_lons = [], []
        nb_lats,  nb_lons  = [], []

        for t in t_steps:
            e_hdg_r = math.radians(ego["hdg"])
            n_hdg_r = math.radians(nb["hdg"])

            e_lat = ego["lat"] + (ego["spd"] * t * math.cos(e_hdg_r)) / 111320
            e_lon = ego["lon"] + (ego["spd"] * t * math.sin(e_hdg_r)) / (111320 * math.cos(math.radians(ego["lat"])))
            n_lat = nb["lat"]  + (nb["spd"]  * t * math.cos(n_hdg_r)) / 111320
            n_lon = nb["lon"]  + (nb["spd"]  * t * math.sin(n_hdg_r)) / (111320 * math.cos(math.radians(nb["lat"])))

            ego_lats.append(e_lat)
            ego_lons.append(e_lon)
            nb_lats.append(n_lat)
            nb_lons.append(n_lon)

        ax.plot(ego_lons, ego_lats, "b-", linewidth=2, label="Ego")
        ax.plot(nb_lons,  nb_lats,  "r-", linewidth=2, label="Neighbour")
        ax.plot(ego_lons[0], ego_lats[0], "bo", markersize=8)
        ax.plot(nb_lons[0],  nb_lats[0],  "ro", markersize=8)
        ax.plot(ego_lons[-1], ego_lats[-1], "b^", markersize=8)
        ax.plot(nb_lons[-1],  nb_lats[-1],  "r^", markersize=8)

        # Alert color background
        colors = {"RED": "#FFE0E0", "AMBER": "#FFF3E0", "GREEN": "#E0FFE0"}
        ttc = compute_ttc(
            ego["lat"], ego["lon"], ego["spd"], ego["hdg"],
            nb["lat"],  nb["lon"],  nb["spd"],  nb["hdg"],
        )
        cpa = compute_cpa(
            ego["lat"], ego["lon"], ego["spd"], ego["hdg"],
            nb["lat"],  nb["lon"],  nb["spd"],  nb["hdg"],
        )
        level = alert_level(ttc, cpa)
        ax.set_facecolor(colors.get(level, "#FFFFFF"))

        ax.set_title(f"S{i+1}: {sc['name']}\n[{level}]", fontsize=9)
        ax.legend(fontsize=7, loc="upper left")
        ax.set_xlabel("Longitude", fontsize=8)
        ax.set_ylabel("Latitude", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = os.path.join(os.path.dirname(__file__), "collision_validation.png")
    plt.savefig(out_path, dpi=150)
    print(f"  Plots saved to: {out_path}")


def test_all_pairs():
    """Test the all-pairs computation with a small registry."""
    print()
    print("  Testing compute_all_pairs()...")

    registry = {
        "a1": {"lat": 12.9725, "lon": 77.5945, "spd": 20.0, "hdg": 90.0},
        "b2": {"lat": 12.9725, "lon": 77.5955, "spd": 20.0, "hdg": 270.0},
        "c3": {"lat": 12.9700, "lon": 77.5930, "spd": 10.0, "hdg": 45.0},
    }

    matrix = compute_all_pairs(registry)

    print(f"    Pairs computed: {len(matrix)}")
    for pair, data in sorted(matrix.items()):
        print(f"    {pair}: dist={data['dist']}m  ttc={data['ttc']}s  "
              f"cpa={data['cpa']}m  alert={data['alert']}")

    # Should have exactly 3 pairs for 3 vehicles: C(3,2) = 3
    assert len(matrix) == 3, f"Expected 3 pairs, got {len(matrix)}"
    print("    ✓ All-pairs OK")


if __name__ == "__main__":
    success = run_scenarios()
    test_all_pairs()
    generate_plots()

    print()
    if success:
        print("  ✓ All validation tests passed!")
    else:
        print("  ✗ Some tests failed — check collision engine logic.")
        sys.exit(1)
