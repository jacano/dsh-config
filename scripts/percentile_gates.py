"""Percentile gates for the Command Code model menu.

Replaces hand-picked thresholds with rank-based rules computed from two frozen
populations: the catalog snapshot (cost, capability) and the locally measured
set (speed, latency). Robust aggregates only: medians and quantiles, never the
mean, because n is small and one 382 tok/s outlier moves an average but not a
median.

Run: python scripts/percentile_gates.py
"""

from __future__ import annotations

import csv
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog-2026-11-10.csv"
MEASURED = ROOT / "measurements-2026-11-10.csv"

BOOT = 2000
random.seed(7)  # reproducible CIs


def quantile(values, q):
    s = sorted(values)
    if not s:
        return None
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def boot_ci(values, q, n=BOOT):
    if len(values) < 4:
        return (None, None)
    stats = []
    for _ in range(n):
        sample = [random.choice(values) for _ in values]
        stats.append(quantile(sample, q))
    return (quantile(stats, 0.025), quantile(stats, 0.975))


def load():
    catalog = {}
    with open(CATALOG, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            catalog[row["slug"]] = row

    measured = []
    with open(MEASURED, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            slug = row["slug"]
            cat = catalog.get(row["catalog_slug"], {})
            intel = None
            if cat.get("intelligence"):
                intel = float(cat["intelligence"])
            elif row.get("intel_override"):
                intel = float(row["intel_override"])
            measured.append({
                "slug": slug,
                "name": row["name"],
                "speed": float(row["speed_tps"]) if row["speed_tps"] else None,
                "ttft": float(row["ttft_s"]) if row["ttft_s"] else None,
                "cache": float(row["cache_hit"]) if row["cache_hit"] else None,
                "cost": float(cat["best_turn"]) if cat.get("best_turn") else None,
                "intel": intel,
            })
    return catalog, measured


def main():
    catalog, measured = load()

    speeds = [m["speed"] for m in measured if m["speed"]]
    ttfts = [m["ttft"] for m in measured if m["ttft"]]
    costs = [float(r["best_turn"]) for r in catalog.values() if r["best_turn"]]
    intels = [float(r["intelligence"]) for r in catalog.values() if r["intelligence"]]

    gates = {
        "speed_min": quantile(speeds, 0.25),   # not in the slowest quarter
        "ttft_max": quantile(ttfts, 0.50),      # not slower to start than typical
        "cost_max": quantile(costs, 0.25),      # cheapest quarter of the catalog
        "intel_min": quantile(intels, 0.50),    # above the catalog median
        "cache_min": 0.80,                      # hit rate, not a binary
    }

    print(f"populations: speed n={len(speeds)}, latency n={len(ttfts)}, "
          f"cost n={len(costs)}, intelligence n={len(intels)}")
    print("\ngates (robust quantiles, 95% bootstrap CI):")
    for label, values, q in (("speed  >= P25", speeds, 0.25),
                             ("ttft   <= P50", ttfts, 0.50),
                             ("cost   <= P25", costs, 0.25),
                             ("intel  >= P50", intels, 0.50)):
        value = quantile(values, q)
        lo, hi = boot_ci(values, q)
        ci = f"[{lo:.3f}, {hi:.3f}]" if lo is not None else "n too small"
        print(f"  {label:14s} {value:9.3f}   {ci}")

    print("\nmodel evaluation (ranks are percentiles within each population):")
    header = f"{'model':34s} {'tok/s':>6s} {'rank':>5s} {'ttft':>6s} {'cost':>8s} {'rank':>5s} {'intel':>6s}  verdict"
    print(header)
    print("-" * len(header))

    for m in sorted(measured, key=lambda x: -(x["speed"] or 0)):
        fails = []
        if m["speed"] is None:
            fails.append("no speed")
        elif m["speed"] < gates["speed_min"]:
            fails.append(f"speed {m['speed']:.0f} < {gates['speed_min']:.0f}")
        if m["ttft"] is None:
            fails.append("no ttft")
        elif m["ttft"] > gates["ttft_max"]:
            fails.append(f"ttft {m['ttft']:.1f}s > {gates['ttft_max']:.1f}s")
        if m["cost"] is not None and m["cost"] > gates["cost_max"]:
            fails.append(f"cost ${m['cost']:.4f} > ${gates['cost_max']:.4f}")
        if m["intel"] is None:
            fails.append("unscored")
        elif m["intel"] < gates["intel_min"]:
            fails.append(f"intel {m['intel']:.1f} < {gates['intel_min']:.1f}")
        if m["cache"] is not None and m["cache"] < gates["cache_min"]:
            fails.append(f"cache {m['cache']*100:.0f}%")

        speed_rank = (sum(1 for s in speeds if s <= m["speed"]) / len(speeds) * 100) if m["speed"] else 0
        cost_rank = (sum(1 for c in costs if c <= m["cost"]) / len(costs) * 100) if m["cost"] else 0
        print(f"{m['name'][:34]:34s} {m['speed'] or 0:6.0f} {speed_rank:4.0f}% "
              f"{(m['ttft'] or 0):6.1f} {(m['cost'] or 0):8.4f} {cost_rank:4.0f}% "
              f"{(m['intel'] or 0):6.1f}  {'PASS' if not fails else 'fail: ' + ', '.join(fails)}")


if __name__ == "__main__":
    main()
