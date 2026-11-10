#!/usr/bin/env python3
"""Enforce the tier gates in models-policy.yml against the measured rows.

Two directions are checked:
  1. every admitted row clears its own tier;
  2. every measured row outside the menu misses at least one gate, so nothing
     new can slip in without a threshold moving on purpose.

Stdlib only. Run: python scripts/evaluate_gates.py [measurements.csv]
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "models-policy.yml"
CATALOG = ROOT / "catalog-2026-11-10.csv"
MEASURED = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "measurements-2026-11-10-run2.csv"


def load_policy():
    tiers: dict[str, dict[str, float]] = {}
    admitted: dict[str, str] = {}
    tier = None
    in_admitted = False
    current = None

    for line in POLICY.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^    (\w+):\s*$", line)
        if m and m.group(1) in ("daily", "budget"):
            tier = m.group(1)
            tiers[tier] = {}
            continue
        m = re.match(r"^      (\w+):\s*([\d.]+)\s*$", line)
        if m and tier:
            tiers[tier][m.group(1)] = float(m.group(2))
            continue
        if line.startswith("admitted:"):
            in_admitted = True
            tier = None
            continue
        if in_admitted:
            m = re.match(r"^  - id:\s*(\S+)", line)
            if m:
                current = m.group(1)
                admitted[current] = "daily"
                continue
            m = re.match(r"^    tier:\s*(\S+)", line)
            if m and current:
                admitted[current] = m.group(1)
                continue
            if line.startswith("excluded:") or line.startswith("# "):
                if line.startswith("excluded:"):
                    in_admitted = False
    return tiers, admitted


def load_catalog():
    prices, intel = {}, {}
    for row in csv.DictReader(open(CATALOG, encoding="utf-8")):
        if row.get("best_turn"):
            prices[row["slug"]] = float(row["best_turn"])
        if re.match(r"^[\d.]+$", row.get("intelligence") or ""):
            intel[row["slug"]] = float(row["intelligence"])
    return prices, intel


def load_measured(prices, catalog_intel):
    out = []
    for row in csv.DictReader(open(MEASURED, encoding="utf-8")):
        cat = row["catalog_slug"]
        intel = catalog_intel.get(cat)
        m = re.match(r"^[\d.]+$", row.get("intel_override") or "")
        if m:
            intel = float(m.group(0))
        out.append({
            "id": row["slug"],
            "name": row["name"],
            "speed": float(row["speed_tps"]) if row["speed_tps"] else None,
            "ttft": float(row["ttft_s"]) if row["ttft_s"] else None,
            "cache": float(row["cache_hit"]) if row["cache_hit"] else None,
            "cost": prices.get(cat),
            "capability": intel,
        })
    return out


def check(model, gates):
    """List of failed gate names."""
    fails = []
    if gates.get("speed_min") is not None:
        if model["speed"] is None or model["speed"] < gates["speed_min"]:
            fails.append(f"speed {model['speed'] or 0:.0f} < {gates['speed_min']:.0f}")
    if gates.get("latency_max") is not None:
        if model["ttft"] is None or model["ttft"] > gates["latency_max"]:
            fails.append(f"ttft {model['ttft'] or 0:.2f} > {gates['latency_max']:.2f}")
    if gates.get("cost_max") is not None:
        if model["cost"] is None or model["cost"] > gates["cost_max"]:
            fails.append(f"cost {model['cost'] or 0:.4f} > {gates['cost_max']:.4f}")
    if gates.get("capability_min") is not None:
        if model["capability"] is None or model["capability"] < gates["capability_min"]:
            fails.append(f"capability {model['capability'] or 0:.1f} < {gates['capability_min']:.1f}")
    if gates.get("cache_min") is not None:
        if model["cache"] is None or model["cache"] < gates["cache_min"]:
            fails.append(f"cache {model['cache'] or 0:.0%}")
    return fails


def main():
    tiers, admitted = load_policy()
    prices, catalog_intel = load_catalog()
    measured = load_measured(prices, catalog_intel)

    problems = []

    print("tier gates:")
    for name, gates in tiers.items():
        print(f"  {name:7s} " + "  ".join(f"{k}={v}" for k, v in gates.items()))

    print("\nadmitted rows:")
    for m in measured:
        if m["id"] not in admitted:
            continue
        tier = admitted[m["id"]]
        fails = check(m, tiers[tier])
        print(f"  {'PASS' if not fails else 'FAIL':4s} {m['name'][:30]:30s} [{tier}] {', '.join(fails)}")
        if fails:
            problems.append(f"{m['id']} is admitted but misses {tier}: {', '.join(fails)}")

    print("\noutside the menu (each must miss at least one gate):")
    for m in measured:
        if m["id"] in admitted:
            continue
        passing = [t for t, g in tiers.items() if not check(m, g)]
        print(f"  {'WOULD ENTER ' + passing[0] if passing else 'blocked':12s} {m['name'][:30]:30s} "
              f"{', '.join(check(m, tiers['daily'])) or 'clears daily'}")
        if passing:
            problems.append(f"{m['id']} is not admitted but clears the {passing[0]} tier")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nOK: every admitted row clears its tier and nothing outside the menu does")
    return 0


if __name__ == "__main__":
    sys.exit(main())
