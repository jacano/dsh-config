#!/usr/bin/env python3
"""Run the model policy as a funnel: static, measured, provider fitness.

Phase 1 static    capability, price and plan access from the catalog. A row that
                  fails here is never measured and never costs a token.
Phase 2 measured  speed, latency and cache: the per-call numbers.
Phase 3 fitness   prefill cost, cache in a loop, parallel retention and error
                  budget: whether the route behind the model is good enough for
                  an agent loop.

Every threshold is the envelope of the admitted rows, so a new model has to beat
the worst admitted one on every axis to get in.

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
MEASURED = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "measurements-2026-11-10-run3.csv"
FITNESS = ROOT / "fitness-2026-11-10.csv"


def load_policy():
    gates: dict[str, dict[str, float]] = {}
    admitted: set[str] = set()
    phase = None
    in_admitted = False

    for line in POLICY.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^    (static|measured|fitness):\s*$", line)
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


def load_fitness():
    out = {}
    for r in csv.DictReader(open(FITNESS, encoding="utf-8")):
        out[r["slug"]] = {
            "prefill": float(r["prefill_ms_per_1k"]),
            "cache": float(r["cache_hit"]),
            "retention": float(r["retention_4x"]),
            "errors": int(r["errors_10"]),
        }
    return out


GATES: dict[str, dict[str, float]] = {}


def fails_static(capability, cost):
    f = []
    g = GATES["static"]
    if capability is None or capability < g["capability_min"]:
        f.append(f"capability {capability or 0:.1f} < {g['capability_min']:.1f}")
    if cost is None or cost > g["cost_max"]:
        f.append(f"cost {cost or 0:.4f} > {g['cost_max']:.4f}")
    return f


def fails_measured(m, capability, cost):
    g = GATES["measured"]
    f = fails_static(capability, cost)
    if m["speed"] is None or m["speed"] < g["speed_min"]:
        f.append(f"speed {m['speed'] or 0:.0f} < {g['speed_min']:.0f}")
    if m["ttft"] is None or m["ttft"] > g["latency_max"]:
        f.append(f"latency {m['ttft'] or 0:.2f} > {g['latency_max']:.2f}")
    if m["cache"] is None or m["cache"] < g["cache_min"]:
        f.append(f"cache {m['cache'] or 0:.0%}")
    return f


def fails_fitness(fit):
    g = GATES["fitness"]
    f = []
    if fit["prefill"] > g["prefill_ms_per_1k_max"]:
        f.append(f"prefill {fit['prefill']:.1f} > {g['prefill_ms_per_1k_max']:.0f} ms/1k")
    if fit["cache"] < g["cache_hit_min"]:
        f.append(f"cache {fit['cache']:.0%}")
    if fit["retention"] < g["retention_4x_min"]:
        f.append(f"retention {fit['retention']:.2f}")
    if fit["errors"] > g["errors_per_10_max"]:
        f.append(f"errors {fit['errors']}/10")
    return f


def main():
    global GATES
    GATES, admitted = load_policy()
    catalog = load_catalog()
    measured = load_measured()
    fitness = load_fitness()

    by_slug = {r["slug"]: r for r in catalog}
    overrides = {m["catalog"]: m["capability_override"] for m in measured.values()
                 if m["capability_override"] is not None}
    for r in catalog:
        if r["capability"] is None and r["slug"] in overrides:
            r["capability"] = overrides[r["slug"]]

    print("phase 1 - static (no tokens spent):")
    print("  " + "  ".join(f"{k}={v}" for k, v in GATES["static"].items()))
    survivors = [r for r in catalog if not fails_static(r["capability"], r["cost"])]
    print(f"  {len(catalog)} catalog rows -> {len(survivors)} worth measuring")
    measured_catalogs = {m["catalog"] for m in measured.values()}
    for r in survivors:
        if r["slug"] not in measured_catalogs:
            print(f"    pending measurement: {r['name'][:40]:40s} capability {r['capability']:.1f}  cost ${r['cost']:.4f}")

    print("\nphase 2 - measured (per call):")
    print("  " + "  ".join(f"{k}={v}" for k, v in GATES["measured"].items()))
    print("phase 3 - fitness (per route):")
    print("  " + "  ".join(f"{k}={v}" for k, v in GATES["fitness"].items()))

    problems = []
    for m in measured.values():
        row = by_slug.get(m["catalog"], {})
        capability = m["capability_override"] if m["capability_override"] is not None else row.get("capability")
        cost = row.get("cost")
        f2 = fails_measured(m, capability, cost)
        fit = fitness.get(m["id"])
        f3 = fails_fitness(fit) if fit else ["no fitness data"]
        is_admitted = m["id"] in admitted
        verdict = "PASS" if not f2 and not f3 else "FAIL"
        if is_admitted:
            print(f"  {verdict:4s} {m['name'][:30]:30s} {', '.join(f2 + f3)}")
            if f2 or f3:
                problems.append(f"{m['name']} is admitted but misses: {', '.join(f2 + f3)}")
        elif not f2 and not f3:
            print(f"  ENTER {m['name'][:30]:30s} clears every gate but is not admitted")
            problems.append(f"{m['name']} clears every gate but is not admitted")

    for m in measured.values():
        if m["id"] in admitted and m["id"] not in fitness:
            problems.append(f"{m['name']} is admitted without fitness data")

    if problems:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nOK: every admitted row clears all three phases and nothing outside the menu does")
    return 0


if __name__ == "__main__":
    sys.exit(main())
