#!/usr/bin/env python3
"""What every lane reads, and where everything is.

    money/    what a subscription really costs per token
    select/   fold 1: which models are worth calling at all
    measure/  fold 2 and fold 3: the battery, then real work

The policy and the price catalogue are read by more than one lane, so they are
parsed once, here, and nowhere else. A lane owns its own files and its own
scripts; it does not reach into another lane's folder except through this module.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

BENCH = Path(__file__).resolve().parent
REPO = BENCH.parent
MONEY = BENCH / "money"
SELECT = BENCH / "select"
MEASURE = BENCH / "measure"

POLICY = BENCH / "models-policy.yml"
CATALOG = MONEY / "catalog-2026-11-10.csv"
CONFIG = REPO / "dsh" / "cordis.patch.yml"


def load_policy():
    """The gates and the admitted ids, as the YAML file states them."""
    gates: dict[str, dict[str, float]] = {}
    admitted: set[str] = set()
    phase = None
    section = None
    for line in POLICY.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^    (static|measured|fitness):\s*$", line)
        if m:
            phase, gates[m.group(1)] = m.group(1), {}
            continue
        m = re.match(r"^      (\w+):\s*([\d.]+)\s*$", line)
        if m and phase:
            gates[phase][m.group(1)] = float(m.group(2))
            continue
        if line.startswith("admitted:"):
            section, phase = "admitted", None
            continue
        if line.startswith("excluded:"):
            section = "excluded"
            continue
        m = re.match(r"^  - id:\s*(\S+)", line)
        if m and section == "admitted":
            admitted.add(m.group(1))
    return gates, admitted


def load_catalog() -> dict:
    """The frozen Command Code catalogue, as fold 1 wants it: price and grade."""
    rows = {}
    for r in csv.DictReader(open(CATALOG, encoding="utf-8")):
        rows[r["slug"]] = {
            "name": r["name"],
            "capability": float(r["intelligence"]) if re.match(r"^[\d.]+$", r.get("intelligence") or "") else None,
            "cost": float(r["best_turn"]) if r.get("best_turn") else None,
        }
    return rows
