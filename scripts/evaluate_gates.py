#!/usr/bin/env python3
"""Run the model policy as a funnel: static prefilter first, measurement second.

Phase 1 is static: capability, price and plan access come from the catalog, so a
row that fails here is never measured and never costs a token.
Phase 2 is measured: speed, latency and cache are the only properties that need
the API, so only the survivors of phase 1 are worth a request.

Both phases are the envelope of the admitted rows, which means a new model has
to beat the worst admitted one on every axis to get in.

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
    gates: dict[str, dict[str, float]] = {}
    admitted: set[str] = set()
    phase = None
    in_admitted = False

    for line in POLICY.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^    (static|measured):\s*$", line)
        if m:
            phase = m.group(1)
            gates[phase] = {}
            continue
        m = re.match(r"^      (\w+):\s*([\d.]+)\s*$", line)
        if m and phase:
            gates[phase][m.group(1)] = float(m.group(2))
            continue
        if line.startswith("admitted:"):
            in_admitted = True
            phase = None
            continue
        if in_admitted:
            if line.startswith("excluded:"):
                in_admitted = False
                continue
            m = re.match(r"^  - id:\s*(\S+)", line)
            if m:
                admitted.add(m.group(1))
    return gates, admitted


def load_catalog():
    rows = []
    for r in csv.DictReader(open(CATALOG, encoding="utf-8")):
        rows.append({
            "slug": r["slug"],
            "name": r["name"],
            "capability": float(r["intelligence"]) if re.match(r"^[\d.]+$", r.get("intelligence") or "") else None,
            "cost": float(r["best_turn"]) if r.get("best_turn") else None,
        })
    return rows


def load_measured():
    out = {}
    for r in csv.DictReader(open(MEASURED, encoding="utf-8")):
        cap = None
        m = re.match(r"^[\d.]+$", r.get("intel_override") or "")
        if m:
            cap = float(m.group(0))
        out[r["slug"]] = {
            "id": r["slug"],
            "name": r["name"],
            "catalog": r["catalog_slug"],
            "capability_override": cap,
            "speed": float(r["speed_tps"]) if r["speed_tps"] else None,
            "ttft": float(r["ttft_s"]) if r["ttft_s"] else None,
            "cache": float(r["cache_hit"]) if r["cache_hit"] else None,
        }
    return out


def fails_static(row):
    f = []
    if row["capability"] is None or row["capability"] < GATES["static"]["capability_min"]:
        f.append(f"capability {row['capability'] or 0:.1f} < {GATES['static']['capability_min']:.1f}")
    if row["cost"] is None or row["cost"] > GATES["static"]["cost_max"]:
        f.append(f"cost {row['cost'] or 0:.4f} > {GATES['static']['cost_max']:.4f}")
    return f


def fails_measured(m, capability, cost):
    f = []
    g = GATES["measured"]
    if m["speed"] is None or m["speed"] < g["speed_min"]:
        f.append(f"speed {m['speed'] or 0:.0f} < {g['speed_min']:.0f}")
    if m["ttft"] is None or m["ttft"] > g["latency_max"]:
        f.append(f"latency {m['ttft'] or 0:.2f} > {g['latency_max']:.2f}")
    if m["cache"] is None or m["cache"] < g["cache_min"]:
        f.append(f"cache {m['cache'] or 0:.0%}")
    f += fails_static({"capability": capability, "cost": cost})
    return f


GATES: dict[str, dict[str, float]] = {}


def main():
    global GATES
    GATES, admitted = load_policy()
    catalog = load_catalog()
    measured = load_measured()

    by_slug = {r["slug"]: r for r in catalog}
    # Published capability that the catalog leaves blank but the measurements
    # file documents (same weights as a scored sibling, or an AA estimate).
    # Still static: no request is spent to know it.
    overrides = {m["catalog"]: m["capability_override"] for m in measured.values()
                 if m["capability_override"] is not None}
    for r in catalog:
        if r["capability"] is None and r["slug"] in overrides:
            r["capability"] = overrides[r["slug"]]
    print("phase 1 - static (no tokens spent):")
    print("  " + "  ".join(f"{k}={v}" for k, v in GATES["static"].items()))
    survivors = [r for r in catalog if not fails_static(r)]
    print(f"  {len(catalog)} catalog rows -> {len(survivors)} worth measuring")
    measured_catalogs = {m["catalog"] for m in measured.values()}
    for r in survivors:
        if r["slug"] not in measured_catalogs:
            print("    pending measurement: " + r["name"][:40].ljust(40) +
                  " capability " + format(r["capability"], ".1f") +
                  "  cost $" + format(r["cost"], ".4f"))

    print("\nphase 2 - measured:")
    print("  " + "  ".join(f"{k}={v}" for k, v in GATES["measured"].items()))

    problems = []
    admitted_measured = 0
    for m in measured.values():
        row = by_slug.get(m["catalog"], {})
        capability = m["capability_override"] if m["capability_override"] is not None else row.get("capability")
        cost = row.get("cost")
        f = fails_measured(m, capability, cost)
        is_admitted = m["id"] in admitted
        if is_admitted:
            admitted_measured += 1
            print(f"  {'PASS' if not f else 'FAIL':4s} {m['name'][:32]:32s} {', '.join(f)}")
            if f:
                problems.append(f"{m['name']} is admitted but misses: {', '.join(f)}")
        elif not f:
            print(f"  {'ENTER':4s} {m['name'][:32]:32s} clears every gate but is not admitted")
            problems.append(f"{m['name']} clears every gate but is not admitted")

    print(f"\n  admitted and measured: {admitted_measured} of {len(admitted)}")
    unmeasured = [s for s in admitted if s not in {m['id'] for m in measured.values()}]
    if unmeasured:
        problems.append(f"admitted but never measured: {', '.join(sorted(unmeasured))}")

    print("\nphase 1 rejects (never measured, no tokens spent):")
    rejected = [r for r in catalog if fails_static(r)]
    print(f"  {len(rejected)} of {len(catalog)} rows")
    for r in rejected[:8]:
        print(f"    {r['name'][:40]:40s} {', '.join(fails_static(r))}")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nOK: every admitted row clears both phases, and no unadmitted measured row does")
    return 0


if __name__ == "__main__":
    sys.exit(main())
