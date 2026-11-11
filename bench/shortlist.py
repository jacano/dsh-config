#!/usr/bin/env python3
"""First fold: which models a provider is even worth testing.

    python bench/shortlist.py           # the table, on screen
    python bench/shortlist.py --write   # also save shortlist-<today>.csv

Reads the gates from models-policy.yml and the plans from providers.json, so
adding a provider is one block of data and no code. Nothing here calls an API:
a row that fails this fold is never measured, and costs nothing.

The second fold is bench/evaluate.py, the test battery: speed, latency, cache,
prefill, concurrency, errors and tool calls. Only the rows this file marks IN
go there.
"""

from __future__ import annotations

import csv
import datetime
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
REPO = BENCH.parent
sys.path.insert(0, str(BENCH))

import evaluate as ev  # noqa: E402  (same folder: shares the policy and catalog readers)

import re  # noqa: E402

PROVIDERS = BENCH / "providers.json"
CAPABILITY = BENCH / "capability.json"


def aa() -> dict:
    """Capability and reasoning, from Artificial Analysis, never the vendor."""
    if not CAPABILITY.exists():
        raise SystemExit("no capability.json. run: python bench/capability.py")
    return json.loads(CAPABILITY.read_text(encoding="utf-8"))["models"]


LANES = ("fast", "eco", "ultrafast", "preview", "latest", "sync", "max", "high", "xhigh")


def key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def rate_of(ratings: dict, model_id: str, catalog_slug: str) -> dict:
    """A serving lane is the same model: match it to its base row."""
    candidates = []
    for raw in (catalog_slug, model_id.split("/")[-1], model_id):
        if not raw:
            continue
        candidates.append(key(raw))
        base = raw
        for lane in LANES:
            base = base.replace(f"-{lane}", "").replace(f"/{lane}", "")
        candidates.append(key(base))
    for c in candidates:
        if c in ratings:
            return ratings[c]
    for k, rec in ratings.items():
        if any(c and (k.startswith(c[:12]) or c.startswith(k[:12])) for c in candidates):
            return rec
    return {}


def load_providers() -> dict:
    return json.loads(PROVIDERS.read_text(encoding="utf-8"))


def rows():
    plans = load_providers()
    gates = ev.load_policy()[0]["static"]
    cap_min, cost_max = gates["capability_min"], gates["cost_max"]
    need_reasoning = str(gates.get("require_reasoning", "false")).lower() == "true"
    catalog = ev.load_catalog()
    ratings = aa()

    out = []
    for name, plan in plans["providers"].items():
        for m in plan["models"]:
            cat = catalog.get(m.get("catalog") or "", {})
            rate = rate_of(ratings, m["id"], m.get("catalog") or "")
            capability = rate.get("intelligence")
            reasons = rate.get("is_reasoning")
            listed = m["list_turn_usd"] if "list_turn_usd" in m else cat.get("cost")
            factor = float(m.get("factor", 1.0))
            effective = listed * factor if listed is not None else None

            if capability is None:
                passes, reason = False, "no AA row: unranked"
            elif need_reasoning and reasons is not True:
                passes, reason = False, "no reasoning flag from AA"
            elif capability < cap_min:
                passes, reason = False, f"capability {capability:.1f} < {cap_min:.1f}"
            elif effective is None:
                passes, reason = False, "no price on record"
            elif effective > cost_max:
                passes, reason = False, f"cost {effective:.4f} > {cost_max:.4f}"
            else:
                passes, reason = True, ""

            out.append({
                "provider": name, "plan": plan["plan"], "billing": plan["billing"],
                "plan_fee_usd": plan["fee_usd"], "plan_credits_usd": plan["credits_usd"],
                "model": m["id"], "capability": capability, "is_reasoning": reasons,
                "list_turn_usd": listed, "factor": factor, "effective_turn_usd": effective,
                "passes_static": passes, "reason": reason,
            })
    return out, gates


def table(data) -> None:
    by_provider = {}
    for r in data:
        by_provider.setdefault(r["provider"], []).append(r)

    for name, group in by_provider.items():
        head = group[0]
        money = ""
        if head["plan_fee_usd"] is not None:
            money = f"${head['plan_fee_usd']:.0f}/mo"
        if head["plan_credits_usd"] is not None:
            money += f" + ${head['plan_credits_usd']:.0f} credits"
        print(f"\n{name}  [{head['plan']} - {money or 'prepaid'}]")
        ordered = sorted(group, key=lambda x: (x["effective_turn_usd"] is None,
                                               x["effective_turn_usd"] or 0))
        for r in ordered:
            cap = "-" if r["capability"] is None else f"{r['capability']:.1f}"
            eff = "-" if r["effective_turn_usd"] is None else f"${r['effective_turn_usd']:.4f}"
            mark = "IN " if r["passes_static"] else "out"
            tail = "" if r["passes_static"] else f"  {r['reason']}"
            print(f"  {mark} {r['model'][:34]:34s} x{r['factor']:<4.2f} cap {cap:>5}  {eff:>9}{tail}")


def main() -> int:
    data, gates = rows()
    print(f"fold 1 - static: capability >= {gates['capability_min']:.1f}, "
          f"cost <= ${gates['cost_max']:.4f}/turn")
    table(data)

    inside = sorted((r for r in data if r["passes_static"]),
                    key=lambda x: x["effective_turn_usd"])
    print(f"\n{len(inside)} of {len(data)} rows go to the test battery, cheapest first: "
          + ", ".join(f"{r['provider']}:{r['model']}" for r in inside))

    if "--write" in sys.argv:
        today = datetime.date.today().isoformat()
        path = BENCH / f"shortlist-{today}.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)
        print(f"\nwritten: {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
