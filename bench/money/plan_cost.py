#!/usr/bin/env python3
"""What a subscription really costs per million tokens, blend included.

    python bench/money/plan_cost.py                 # every plan, today's promos
    python bench/money/plan_cost.py --model v4.1-flash    # another model
    python bench/money/plan_cost.py --today 2026-10-22    # a day a promo was live
    python bench/money/plan_cost.py --write               # save plan-cost-<day>.csv

Three things are folded in, so the number on screen is the number to compare:

  money   what the fee buys, times the model's own multiplier;
  promo   applied while it is live, dropped the day its window closes;
  week    weekday peak hours at the peak price, weighted by their share of it.

A window (weekly, five-hour) caps the rate, not the total. When one bites, the
plan buys less than its credits and the price per token climbs here — that is
the difference between a quota and a price, and it is why `caps at` is a column.

Every figure comes from a file in this folder. Nothing is typed in twice: the
peak schedule is read from the catalogue's own wording, the promo from the
window refresh.py stored, the fee and credits from providers.json.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
REPO = BENCH.parent

TURN = 91_500          # bench/README.md: 89k cache + 1k fresh + 1.5k written
FX = 6.714             # CNY per USD, the rate a Chinese price list is read at
DAYS = 30.0            # a month, for the windows
DEFAULT = "deepseek-v4-1-flash"

OFF_HOURS = re.compile(r"\((\d+)h/day\)")
PEAK_PRICE = re.compile(r"peak\s*\$([\d.]+)\s*/\s*\$?([\d.]+)")


def norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def catalog() -> dict:
    with open(HERE / "catalog-2026-11-10.csv", encoding="utf-8") as fh:
        rows = [dict(r) for r in csv.DictReader(fh)]
    for r in rows:                       # the fold-1 name for the same figure
        r["cost"] = float(r["best_turn"]) if r.get("best_turn") else None
    return {r["slug"]: r for r in rows}


def blend(row: dict) -> float:
    """Peak share of the week, as a multiplier on the off-peak price.

    The catalogue says it itself: "Off-peak shown (17h/day) · peak $0.30 / $1.20
    01-04 & 06-10 UTC, Mon-Fri". Seven hours of five weekdays is 20,8 % of the
    week, and the ratio between the two listed prices is the multiplier. A row
    with no such wording has one price, and 1,0 is not a guess: it is the truth.
    """
    hours, peak = OFF_HOURS.search(row.get("name") or ""), PEAK_PRICE.search(row.get("name") or "")
    try:
        listed = float(row.get("input") or "")
    except ValueError:
        return 1.0
    if not (hours and peak and listed):
        return 1.0
    share = (24 - int(hours.group(1))) * 5 / (24 * 7)
    return 1.0 + share * (float(peak.group(1)) / listed - 1.0)


def caps(plan: dict, monthly: float | None) -> tuple[float | None, str]:
    """The usage the plan can actually be spent at, and what stops it first."""
    limit: dict[str, float] = {}
    if monthly:
        limit["credits"] = monthly
    w = plan.get("windows") or {}
    if "week_usd" in w:
        limit["week"] = w["week_usd"] * DAYS / 7
    if "five_hours_usd" in w:
        limit["5 h"] = w["five_hours_usd"] * DAYS * 24 / 5
    if monthly and "week_pct" in w:
        limit["week"] = monthly * w["week_pct"] / 100 * DAYS / 7
    if monthly and "five_hours_pct" in w:
        limit["5 h"] = monthly * w["five_hours_pct"] / 100 * DAYS * 24 / 5
    if not limit:
        return None, "-"
    bound = min(limit, key=lambda k: limit[k])
    return limit[bound], bound


def promo(plan: dict, model_id: str, day: date) -> float | None:
    """The multiplier a live offer drops this model to, or nothing."""
    for p in plan.get("promos") or []:
        if norm(p.get("model")) not in (norm(model_id.split("/")[-1]), norm(model_id)):
            continue
        try:
            first, last = date.fromisoformat(p["from"]), date.fromisoformat(p["until"])
        except (KeyError, ValueError):
            continue
        if first <= day <= last:
            return float(p["multiplier"])
    return None


def lookup(cat: dict, model_id: str) -> dict:
    """The catalogue's row for this model, whatever lane the plan calls it."""
    target = norm(re.sub(r"\([^)]*\)", "", model_id))
    for slug, row in cat.items():
        if norm(slug) == target:
            return row
    return {}


def wanted(model_id: str, want: str) -> bool:
    """A serving lane is the same model: "(Off-Peak)" or "(> 512K)" is a lane."""
    bare = re.sub(r"\([^)]*\)", "", model_id)
    return want in (norm(model_id), norm(model_id.split("/")[-1]), norm(bare))


def rows(day: date, want: str) -> list[dict]:
    cat = catalog()
    stored = json.loads((HERE / "providers.json").read_text(encoding="utf-8"))["providers"]
    out: list[dict] = []
    target = norm(want)

    for provider, plan in stored.items():
        entries = ([{"id": slug, "catalog": slug} for slug in cat]
                   if plan.get("models") == "catalog" else plan["models"])
        # A plan that sells the peak lane as its own row is telling us the price
        # moves with the hour; the blend below weighs it, so that row is not a
        # second purchase and is not counted twice.
        moves = any(re.search(r"\(peak\)", e["id"], re.I) for e in entries)
        for m in entries:
            if re.search(r"\(peak\)", m["id"], re.I) or not wanted(m["id"], target):
                continue
            row = cat.get(m.get("catalog") or "") or lookup(cat, m["id"])
            listed = m["list_turn_usd"] if "list_turn_usd" in m else row.get("cost")
            if listed is None:
                continue
            monthly = m.get("monthly_limit_usd")
            monthly = monthly if isinstance(monthly, (int, float)) else plan.get("credits_usd")
            usable, bound = caps(plan, monthly)
            offer = promo(plan, m["id"], day)
            # A plan that publishes its own price has one price, unless it sells
            # the peak lane separately; the catalogue's wording only settles it
            # for the rows the catalogue itself prices.
            hourly = blend(row) if moves or ("list_turn_usd" not in m and row) else 1.0
            unit = float(listed) * float(m.get("factor", 1.0)) * (offer or 1.0) * hourly
            per_turn = unit if not usable else float(plan["fee_usd"]) / usable * unit
            out.append({
                "plan": f"{provider} {plan['plan']}",
                "fee": float(plan["fee_usd"]),
                "buys": usable, "caps at": bound,
                "status": "ready" if plan.get("active") is not False else "prepared",
                "promo": f"{offer:g}x" if offer else "-",
                "usd_per_turn": per_turn,
                "usd_per_m": per_turn / TURN * 1e6,
            })

    row = cat.get(want)
    if row and "best_turn" in row:
        per_turn = float(row["best_turn"]) * blend(row)
        name = row["name"].split(" Off-peak")[0].replace(" (latest)", "")
        out.append({
            "plan": f"{name} (list, pay as you go)",
            "fee": None, "buys": None, "caps at": "-", "status": "metered",
            "promo": "-", "usd_per_turn": per_turn, "usd_per_m": per_turn / TURN * 1e6,
        })

    # One line per plan: a plan that offers the model in several lanes is bought
    # once, and the lane that matters is the cheapest one it grants.
    best: dict[str, dict] = {}
    for r in out:
        cur = best.get(r["plan"])
        if cur is None or r["usd_per_m"] < cur["usd_per_m"]:
            best[r["plan"]] = r
    return sorted(best.values(), key=lambda r: r["usd_per_m"])


def main() -> int:
    args = sys.argv[1:]
    day = date.today()
    if "--today" in args:
        day = date.fromisoformat(args[args.index("--today") + 1])
    want = DEFAULT
    if "--model" in args:
        want = args[args.index("--model") + 1]

    got = rows(day, want)
    if not got:
        print(f"no plan serves {want}; try --model with an id from the catalogue")
        return 1

    print(f"what a million tokens cost on {day.isoformat()}, blend and promo inside\n")
    cheapest = got[0]["usd_per_m"]
    print(f"  {'plan':30s} {'fee':>4s} {'buys':>6s} {'caps at':>8s} {'$/M':>11s} "
          f"{'tokens/¥':>10s}  {'promo':<6s} {'vs best':>7s}  status")
    for r in got:
        fee = f"${r['fee']:.0f}" if r["fee"] else "-"
        buys = f"${r['buys']:.0f}" if r["buys"] else "-"
        tokens = 1e6 / (FX * r["usd_per_m"]) / 1e6
        print(f"  {r['plan'][:30]:30s} {fee:>4s} {buys:>6s} {r['caps at']:>8s} "
              f" ${r['usd_per_m']:>10.6f} {tokens:>9,.1f}M  {r['promo']:<6s} "
              f"{r['usd_per_m'] / cheapest:>6.1f}x  {r['status']}")

    peak = blend(catalog().get(want, {}))
    print(f"\n  turn {TURN:,} tokens (89k cache + 1k fresh + 1.5k written) · "
          f"peak {peak - 1:.1%} of the week, priced x{peak:.2f} on the blend · "
          f"1 ¥ = ${1 / FX:.4f}")
    print("  tokens/¥ = what 1 CNY buys at that plan's blended marginal price")

    if "--write" in args:
        path = BENCH / f"plan-cost-{day.isoformat()}.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(got[0].keys()))
            w.writeheader()
            w.writerows(got)
        print(f"\nwritten: {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
