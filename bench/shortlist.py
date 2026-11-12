#!/usr/bin/env python3
"""Fold 1: everything a provider sells, priced, then filtered by what it is. Free.

    python bench/modelsdb.py            # refresh what models.dev says
    python bench/shortlist.py           # price, then signals, then the buckets
    python bench/shortlist.py --write   # and save shortlist-<today>.csv

Three steps, in this order, and each can only remove rows:

  1. price    every model the provider sells, in every lane, with the plan's
              discount or credit multiplier applied. Free.
  2. signals  reasoning and tool calling from models.dev, a third party. A model
              no source describes is not thrown away, it is named for the owner.
  3. decision what survives goes to bench/evaluate.py, the battery. A row missing
              a decisive signal waits for the owner, one by one.

There is no capability score in this fold. The sources that publish one grade a
model on tasks of their own choosing, and a number like that sitting next to a
price invites a comparison that does not hold. Capability is what the battery
measures, and what the owner decides when a measurement is not the whole story.

Nothing here calls a model.
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
MODELSDEV = BENCH / "models.dev.json"
CAPABILITY = BENCH / "capability.json"
LANES = ("fast", "eco", "ultrafast", "preview", "latest", "sync", "max", "high", "xhigh")
LABEL = {"command-code": "Command Code", "open-design": "OpenDesign"}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def excluded() -> list[tuple[str, str | None]]:
    """(model, provider or None) the policy has already judged.

    A reason earned on one lane says nothing about another: the same model is a
    different route somewhere else, with its own speed and its own failures.
    """
    text = (BENCH / "models-policy.yml").read_text(encoding="utf-8")
    block = text.split("excluded:", 1)[-1]
    out = []
    for line in block.splitlines():
        m = re.search(r"- \{\s*id:\s*([^,}]+)", line)
        if not m:
            continue
        # A missing datum is never a reason to exclude: that call belongs to the
        # owner. If somebody writes one here anyway, ignore it and let the row
        # surface as a question instead of disappearing.
        if GAP_WORDS.search(line):
            print(f"  ignoring an exclusion based on missing data: {m.group(1).strip()}")
            continue
        prov = re.search(r"provider:\s*([a-z-]+)", line)
        out.append((norm(m.group(1).split("/")[-1]), prov.group(1) if prov else None))
    return out


def gaps(row: dict) -> list[str]:
    """The facts a decision needs and this row does not have."""
    missing = []
    if row["reasoning"] is None:
        missing.append("reasoning")
    if row["tool_call"] is None:
        missing.append("tools")
    if row["aa"] is None:
        missing.append("capability")
    return missing


GAP_WORDS = re.compile(r"no (capability|data|score|ficha)|unmeasured|unranked|sin ficha",
                       re.IGNORECASE)


def is_excluded(judged, model: str, provider: str) -> bool:
    key = norm(model.split("/")[-1])
    return any(k == key and (p is None or p == provider) for k, p in judged)


def scores() -> dict:
    """AA: how good. A row without a score is not assumed good."""
    if not CAPABILITY.exists():
        raise SystemExit("no capability.json. run: python bench/capability.py")
    return json.loads(CAPABILITY.read_text(encoding="utf-8"))["models"]


def facts() -> dict:
    if not MODELSDEV.exists():
        raise SystemExit("no models.dev.json. run: python bench/modelsdb.py")
    return json.loads(MODELSDEV.read_text(encoding="utf-8"))["models"]


def fact_of(table: dict, model_id: str, catalog_slug: str) -> dict:
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
        if any(p and (k.startswith(p[:12]) or p.startswith(k[:12])) for p in probes):
            return rec
    return {}


def score_of(table: dict, model_id: str, catalog_slug: str) -> dict:
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
    return {}


def model_rows(plan: dict, catalog: dict, table: dict, scores_table: dict) -> list[dict]:
    entries = ([{"id": slug, "catalog": slug} for slug in catalog]
               if plan["models"] == "catalog" else plan["models"])
    out = []
    for m in entries:
        cat = catalog.get(m.get("catalog") or "", {})
        fact = fact_of(table, m["id"], m.get("catalog") or "")
        score = score_of(scores_table, m["id"], m.get("catalog") or "")
        bare = m["id"].split("/")[-1]
        listed = m["list_turn_usd"] if "list_turn_usd" in m else cat.get("cost")
        factor = float(m.get("factor", 1.0))
        leverage = float(plan.get("usd_per_usage_dollar", 1.0))
        usage = listed * factor if listed is not None else None
        out.append({
            "model": m["id"],
            "real_turn_usd": usage * leverage if usage is not None else None,
            "name": cat.get("name") or fact.get("name") or m["id"],
            "list_turn_usd": listed,
            "factor": factor,
            "effective_turn_usd": usage,
            "cache_write_usd_per_m": (plan.get("cache_write_usd_per_m") or {}).get(bare),
            "leverage": leverage,
            "reasoning": fact.get("reasoning"),
            "tool_call": fact.get("tool_call"),
            "context": fact.get("context"),
            "release_date": fact.get("release_date"),
            "deprecated": fact.get("deprecated"),
            "superseded_by": fact.get("superseded_by"),
            "source": fact.get("id"),
            "aa": score.get("intelligence"),
            # the same 90k/1k/1.5k turn, priced from models.dev, to check the shop
            "dev_turn_usd": dev_turn(fact.get("cost")),
        })
    return out


def dev_turn(cost: dict | None) -> float | None:
    """A turn of 89k cached, 1k fresh and 1.5k written, at models.dev prices."""
    if not cost:
        return None
    try:
        cached = float(cost.get("cache_read") or cost.get("input") or 0)
        fresh = float(cost.get("input") or 0)
        out = float(cost.get("output") or 0)
    except (TypeError, ValueError):
        return None
    return (89_000 * cached + 1_000 * fresh + 1_500 * out) / 1_000_000


CTX = 60_000          # the context a turn is priced at


def cold_call(row: dict) -> float | None:
    """The first call of a session also writes the prefix, and that is not free."""
    write = row.get("cache_write_usd_per_m")
    if not write or row["real_turn_usd"] is None:
        return None
    usage = row["effective_turn_usd"] + CTX * write / 1_000_000 * row["factor"]
    return usage * float(row.get("leverage", 1.0))


def classify(row: dict, cost_max: float, cap_min: float, judged,
             oldest: str | None = None) -> tuple[str, str]:
    if is_excluded(judged, row["model"], row["provider"]):
        return "out", "excluded in the policy"
    cost = row["effective_turn_usd"]
    if cost is None:
        return "human", "no price on record"
    if row["real_turn_usd"] is None:
        return "human", "no price on record"
    if row["real_turn_usd"] > cost_max:
        return "out", f"cost {row['real_turn_usd']:.6f} > {cost_max:.6f}"
    if cost == 0:
        return "out", "free: not of interest"
    if row["reasoning"] is False:
        return "out", "models.dev: does not reason"
    if row["tool_call"] is False:
        return "out", "models.dev: no tool calling"
    if row["reasoning"] is None and row["tool_call"] is None:
        return "human", "models.dev has no row: reasoning and tools unknown"
    if row["reasoning"] is None:
        return "human", "reasoning unreported"
    if row["tool_call"] is None:
        return "human", "tool support unreported"
    if row["aa"] is None:
        # An unranked model is a question, not a verdict — unless it was already
        # old when the menu's oldest row shipped. Then nobody is going to score it
        # and waiting is just noise.
        released = row.get("release_date")
        if oldest and released and released < oldest:
            return "out", f"no score and released {released}, before the menu's oldest ({oldest})"
        return "human", "no AA score: capability unknowable"
    if row["aa"] < cap_min:
        return "out", f"capability {row['aa']:.1f} < {cap_min:.1f}"
    return "battery", ""


def main() -> int:
    plans = json.loads(PROVIDERS.read_text(encoding="utf-8"))["providers"]
    gates = ev.load_policy()[0]["static"]
    cost_max = float(gates["cost_max"])
    cap_min = float(gates["capability_min"])
    catalog = ev.load_catalog()
    table, scores_table, judged = facts(), scores(), excluded()
    admitted_ids = ev.load_policy()[1]
    dates = [fact_of(table, i.split("/")[-1], "").get("release_date") for i in admitted_ids]
    oldest = min([d for d in dates if d], default=None)

    print(f"fold 1 · price <= ${cost_max:.4f}/turn · reasoning and tools from models.dev\n")
    rows = []
    for pname, plan in plans.items():
        if plan.get("active") is False:
            print(f"\n{pname}  [prepared, not enabled] {plan.get('note', '')[:90]}")
            continue
        money = f"${plan['fee_usd']:.0f}/{plan.get('billing', 'mo')}" if plan.get("fee_usd") else "prepaid"
        credits = f" + ${plan['credits_usd']:.0f} credits" if plan.get("credits_usd") else ""
        print(f"{pname}  [{plan['plan']} {money}{credits}]")

        buckets = {"battery": [], "human": [], "out": []}
        for row in model_rows(plan, catalog, table, scores_table):
            row["provider"] = pname        # before the gates: an exclusion is per lane
            bucket, why = classify(row, cost_max, cap_min, judged, oldest)
            row.update(plan=plan["plan"], plan_fee_usd=plan.get("fee_usd"),
                       plan_credits_usd=plan.get("credits_usd"), bucket=bucket, why=why,
                       cold_call_usd=cold_call(row))
            buckets[bucket].append(row)
            rows.append(row)

        for row in sorted(buckets["battery"], key=lambda r: r["effective_turn_usd"]):
            cold = cold_call(row)
            extra = f"  1.a ${cold:.5f}" if cold else ""
            print(f"  run   {LABEL[row['provider']]:13s} {row['model'][:28]:28s} "
                  f"uso ${row['effective_turn_usd']:.5f}  real ${row['real_turn_usd']:.6f}{extra}")
        for row in sorted(buckets["human"], key=lambda r: r["effective_turn_usd"]):
            aa = "-" if row["aa"] is None else f"{row['aa']:.1f}"
            money = row["real_turn_usd"]
            print(f"  ????  {LABEL[row['provider']]:13s} {row['model'][:28]:28s} "
                  f"real ${money:.6f}  AA {aa:>5}  {row['why']}")
        print(f"  ({len(buckets['out'])} out)")

    battery = [r for r in rows if r["bucket"] == "battery"]
    human = [r for r in rows if r["bucket"] == "human"]
    print(f"\n{len(rows)} models: {len(battery)} to the battery, {len(human)} need a human, "
          f"{len(rows) - len(battery) - len(human)} out.\n")

    gaps_rows = [r for r in rows if r["bucket"] != "out" and gaps(r)]
    if gaps_rows:
        print("PARA TI — falta un dato, y eso no lo decide el programa:")
        for r in sorted(gaps_rows, key=lambda x: x["effective_turn_usd"] or 0):
            print(f"  {LABEL[r['provider']]:13s} {r['model'][:30]:30s} "
                  f"real ${r['real_turn_usd']:.6f}  falta: {', '.join(gaps(r))}")
        print()

    if human:
        print("waiting on a decision:")
        for r in sorted(human, key=lambda x: x["effective_turn_usd"] or 0):
            print(f"  {LABEL[r['provider']]:13s} {r['model']:30s} real ${r['real_turn_usd']:.6f}  {r['why']}")

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
