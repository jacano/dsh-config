#!/usr/bin/env python3
"""models.dev may say what a model is. It may not say what it costs.

    python bench/test_cost_sources.py

Two proofs, both free and both offline:

  1. price independence - the cost block models.dev carries, multiplied by a
     thousand, zeroed, and blanked out, leaves every priced column and every
     verdict exactly where it was;
  2. signal dependence - the same table with one signal turned off does move a
     verdict, so this test is also watching the path it is not pinning.

A third check is structural: no file but this one and shortlist.py may mention
the cross-check column, and the decision function may not either. If somebody
later feeds models.dev into the cost gate, this fails and says which row moved.
"""

from __future__ import annotations

import copy
import inspect
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))

import evaluate as ev  # noqa: E402
import shortlist as sl  # noqa: E402

COLUMN = "crosscheck_turn_usd"
PRICED = ("list_turn_usd", "factor", "effective_turn_usd", "real_turn_usd", "leverage")


def load(name: str, key: str = "models") -> dict:
    return json.loads((BENCH / name).read_text(encoding="utf-8"))[key]


def priced_rows(table: dict) -> dict:
    """Fold 1 as the gates see it: no file written, no model called."""
    gates = ev.load_policy()[0]["static"]
    catalog, judged, scores = ev.load_catalog(), sl.excluded(), load("capability.json")
    out = {}
    for provider, plan in load("providers.json", "providers").items():
        if plan.get("active") is False:      # fold 1 never prices a prepared plan
            continue
        for row in sl.model_rows(plan, catalog, table, scores):
            row["provider"] = provider
            bucket, why = sl.classify(row, float(gates["cost_max"]),
                                      float(gates["capability_min"]), judged)
            out[(provider, row["model"])] = (row, bucket, why)
    return out


def rewrite(node, fn):
    """Scale every number in a cost block, tiers included."""
    if isinstance(node, dict):
        return {k: rewrite(v, fn) for k, v in node.items()}
    if isinstance(node, list):
        return [rewrite(v, fn) for v in node]
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return fn(node)
    return node


def mutate(table: dict, fn) -> dict:
    """Rewrite every models.dev price. `None` drops the block entirely."""
    out = copy.deepcopy(table)
    for rec in out.values():
        if fn is None:
            rec["cost"] = None
        elif isinstance(rec.get("cost"), dict):
            rec["cost"] = rewrite(rec["cost"], fn)
    return out


def same_price(base: dict, other: dict, label: str) -> int:
    problems = []
    for key, (row, bucket, why) in base.items():
        alt_row, alt_bucket, alt_why = other[key]
        for field in PRICED:
            if row[field] != alt_row[field]:
                problems.append(f"{key[0]}/{key[1]} {field}: {row[field]} -> {alt_row[field]}")
        if (bucket, why) != (alt_bucket, alt_why):
            problems.append(f"{key[0]}/{key[1]} verdict: {bucket!r} -> {alt_bucket!r}")
    print(f"  {'ok  ' if not problems else 'FAIL'} {label:22s} {len(base)} rows, "
          f"{len(problems)} movements")
    for line in problems[:8]:
        print(f"         {line}")
    return len(problems)


def main() -> int:
    table = load("models.dev.json")
    base = priced_rows(table)
    if not base:
        print("FAIL: no rows priced, nothing to prove")
        return 1
    failures = 0

    print(f"price independence ({len(base)} rows):")
    scaled = priced_rows(mutate(table, lambda v: v * 1000))
    failures += same_price(base, scaled, "cost x1000")
    failures += same_price(base, priced_rows(mutate(table, lambda v: 0.0)), "cost zeroed")
    failures += same_price(base, priced_rows(mutate(table, None)), "cost removed")

    moved = sum(1 for k, (row, _, _) in base.items()
                if row[COLUMN] != scaled[k][0][COLUMN])
    print(f"  {'ok  ' if moved else 'FAIL'} the mutation landed     "
          f"{moved} cross-check figures moved")
    failures += 0 if moved else 1

    print("\nsignal dependence:")
    muted = copy.deepcopy(table)
    for rec in muted.values():
        rec["reasoning"] = False
    off = priced_rows(muted)
    changed = [k for k in base if base[k][1] != off[k][1]]
    good = changed and all(off[k][1] == "out" and "does not reason" in off[k][2] for k in changed)
    print(f"  {'ok  ' if good else 'FAIL'} reasoning off          "
          f"{len(changed)} verdicts moved, as they should")
    failures += 0 if good else 1
    no_money = sum(1 for k in base if base[k][0]["real_turn_usd"] != off[k][0]["real_turn_usd"])
    print(f"  {'ok  ' if not no_money else 'FAIL'} and no price moved either  "
          f"{no_money} priced columns changed")
    failures += 0 if not no_money else 1

    print("\nstructure:")
    readers = [p.name for p in sorted(BENCH.glob("*.py"))
               if p.name not in (Path(__file__).name, "shortlist.py")
               and COLUMN in p.read_text(encoding="utf-8")]
    print(f"  {'ok  ' if not readers else 'FAIL'} only shortlist.py names the column"
          f"{'  -> ' + ', '.join(readers) if readers else ''}")
    failures += 0 if not readers else 1
    decision = inspect.getsource(sl.classify)
    print(f"  {'ok  ' if COLUMN not in decision and 'crosscheck' not in decision else 'FAIL'} "
          f"classify never looks at it")
    failures += 0 if COLUMN not in decision and "crosscheck" not in decision else 1

    print(f"\n{'OK: models.dev is identity, never price' if not failures else 'FAIL: ' + str(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
