#!/usr/bin/env python3
"""Fold 1: everything a provider sells, priced, then filtered. Free.

    python bench/shortlist.py                 # the whole funnel, on screen
    python bench/shortlist.py --write         # and save shortlist-<today>.csv

Three steps, in this order, and each one can only remove rows:

  1. price      every model the provider sells, in every lane, with the plan's
                discount or credit multiplier applied. Free.
  2. signals    capability from Artificial Analysis; reasoning and tool support
                from models.dev and AA. A row AA has never scored is not judged
                here: it is not thrown away either, it goes to the human.
  3. decision   what survives step 2 goes to bench/evaluate.py, the battery. What
                is missing a decisive signal waits for the owner, named one by one.

Nothing here calls a model. Fold 2 is bench/evaluate.py.
"""

from __future__ import annotations

import csv
import datetime
import json
import re
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
REPO = BENCH.parent
sys.path.insert(0, str(BENCH))

import evaluate as ev  # noqa: E402

PROVIDERS = BENCH / "providers.json"
CAPABILITY = BENCH / "capability.json"
LANES = ("fast", "eco", "ultrafast", "preview", "latest", "sync", "max", "high", "xhigh")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def ratings() -> dict:
    if not CAPABILITY.exists():
        raise SystemExit("no capability.json. run: python bench/capability.py")
    return json.loads(CAPABILITY.read_text(encoding="utf-8"))["models"]


def rate_of(table: dict, model_id: str, catalog_slug: str) -> dict:
    """A serving lane is the same model: match it to its base row."""
    probes = []
    for raw in (catalog_slug, model_id.split("/")[-1], model_id):
        if not raw:
            continue
        probes.append(norm(raw))
        base = raw
        for lane in LANES:
            base = base.replace(f"-{lane}", "")
        probes.append(norm(base))
    for probe in probes:
        if probe in table:
            return table[probe]
    for k, rec in table.items():
        if any(pr and (k.startswith(pr[:12]) or pr.startswith(k[:12])) for pr in probes):
            return rec
    return {}


def model_rows(plan: dict, catalog: dict, cap_table: dict) -> list[dict]:
    """Every model a provider sells, with its effective price on this plan."""
    listed = plan["models"]
    if listed == "catalog":
        entries = [{"id": slug, "catalog": slug} for slug in catalog]
    else:
        entries = listed

    out = []
    for m in entries:
        cat = catalog.get(m.get("catalog") or "", {})
        rate = rate_of(cap_table, m["id"], m.get("catalog") or "")
        listed_price = m["list_turn_usd"] if "list_turn_usd" in m else cat.get("cost")
        factor = float(m.get("factor", 1.0))
        out.append({
            "model": m["id"],
            "name": cat.get("name") or rate.get("aa_name") or m["id"],
            "list_turn_usd": listed_price,
            "factor": factor,
            "effective_turn_usd": listed_price * factor if listed_price is not None else None,
            "aa": rate.get("intelligence"),
            "aa_reasoning": rate.get("is_reasoning"),
            "dev_reasoning": (rate.get("modelsdev") or {}).get("reasoning"),
            "dev_tools": (rate.get("modelsdev") or {}).get("tool_call"),
        })
    return out


def classify(row: dict, cap_min: float, cost_max: float) -> tuple[str, str]:
    """price first, then the signals. Returns (bucket, why)."""
    cost = row["effective_turn_usd"]
    if cost is None:
        return "human", "no price on record"
    if cost > cost_max:
        return "out", f"cost {cost:.4f} > {cost_max:.4f}"

    reasons = [r for r in (row["aa_reasoning"], row["dev_reasoning"]) if r is not None]
    tools = row["dev_tools"]
    cap = row["aa"]

    if reasons and not any(reasons):
        return "out", "no source says it reasons"
    if tools is False:
        return "out", "models.dev: no tool calling"
    if cap is None:
        return "human", "no AA score: capability unknown"
    if cap < cap_min:
        return "out", f"capability {cap:.1f} < {cap_min:.1f}"
    if not reasons:
        return "human", "capability clear, reasoning unreported by any source"
    if tools is None:
        return "human", "capability clear, tool support unreported"
    return "battery", ""


def main() -> int:
    plans = json.loads(PROVIDERS.read_text(encoding="utf-8"))["providers"]
    gates = ev.load_policy()[0]["static"]
    cap_min = float(gates["capability_min"])
    cost_max = float(gates["cost_max"])
    catalog = ev.load_catalog()
    cap_table = ratings()

    print(f"fold 1 · price <= ${cost_max:.4f}/turn · capability >= {cap_min:.1f} (AA)\n")
    rows = []
    for pname, plan in plans.items():
        money = f"${plan['fee_usd']:.0f}/{plan.get('billing', 'mo')}" if plan.get("fee_usd") else "prepaid"
        credits = f" + ${plan['credits_usd']:.0f} credits" if plan.get("credits_usd") else ""
        print(f"{pname}  [{plan['plan']} {money}{credits}]")

        group = model_rows(plan, catalog, cap_table)
        buckets = {"battery": [], "human": [], "out": []}
        for row in group:
            bucket, why = classify(row, cap_min, cost_max)
            row.update(provider=pname, plan=plan["plan"], plan_fee_usd=plan.get("fee_usd"),
                       plan_credits_usd=plan.get("credits_usd"), bucket=bucket, why=why)
            buckets[bucket].append(row)
            rows.append(row)

        for row in sorted(buckets["battery"], key=lambda r: r["effective_turn_usd"]):
            print(f"  run   {row['model'][:32]:32s} x{row['factor']:<4.2f} "
                  f"AA {row['aa']:5.1f}  ${row['effective_turn_usd']:.4f}")
        for row in sorted(buckets["human"], key=lambda r: r["effective_turn_usd"]):
            print(f"  ????  {row['model'][:32]:32s} x{row['factor']:<4.2f} "
                  f"AA {row['aa'] if row['aa'] is not None else '-':>5}  "
                  f"${row['effective_turn_usd']:.4f}  {row['why']}")
        print(f"  ({len(buckets['out'])} out)")

    battery = [r for r in rows if r["bucket"] == "battery"]
    human = [r for r in rows if r["bucket"] == "human"]
    print(f"\n{len(rows)} models: {len(battery)} to the battery, {len(human)} need a human,\n"
          f"{len(rows) - len(battery) - len(human)} out.\n")

    if human:
        print("the battery cannot run until these are decided:")
        for r in sorted(human, key=lambda x: (x["effective_turn_usd"] or 0)):
            print(f"  {r['provider']}:{r['model']}  ${r['effective_turn_usd']:.4f}  {r['why']}")

    if "--write" in sys.argv:
        today = datetime.date.today().isoformat()
        path = BENCH / f"shortlist-{today}.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nwritten: {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
