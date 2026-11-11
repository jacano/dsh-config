#!/usr/bin/env python3
"""Refresh what each provider charges today, from the provider's own pages.

    python bench/refresh.py            # fetch and report, change nothing
    python bench/refresh.py --write    # store the parsed numbers in providers.json

Prices, credit windows and multipliers move without notice, and a plan is not the
same shape as the model it serves: the same DeepSeek is cheap on one and dear on
another. This reads the pages, prints what it found next to what is stored, and
only writes with --write. When a value cannot be parsed it says so and leaves the
stored one alone: a guessed number is worse than a stale one you know is stale.

Run it before a selection, not on a schedule nobody watches.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

BENCH = Path(__file__).resolve().parent
PROVIDERS = BENCH / "providers.json"
CREDS = Path.home() / ".dsh" / ".credentials.yaml"
UA = {"User-Agent": "curl/8.5.0"}
PLAN_TABS = {"go", "go plus", "go pro", "go max", "plus", "pro", "max"}

sys.stdout.reconfigure(encoding="utf-8")


def fetch(url: str, headers: dict | None = None) -> str:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def text_of(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html))


def key(name: str) -> str:
    """Letters and digits only, so a display name can meet a model id."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find(models: list, name: str):
    """Exact key first, then the loosest substring. GLM-5.3 Flash and Flash-X
    differ by one letter and must not be confused."""
    target = key(name)
    for m in models:
        if key(m["id"]) == target:
            return m
    for m in models:
        a = key(m["id"])
        if a.endswith(target) or target in a or a in target:
            return m
    return None


# --------------------------------------------------------------------------- command code

def command_code() -> dict:
    clean = text_of(fetch("https://commandcode.ai/pricing"))
    out: dict = {}

    goat = re.search(r"GOAT\s*\$\s*(\d+)\s*/\s*month.*?Up to \$(\d+)\s*in credits", clean)
    if goat:
        out["fee_usd"] = float(goat.group(1))
        out["credits_usd"] = float(goat.group(2))

    row = re.search(r"Monthly credits(.{0,160})", clean)
    if row:
        out["credits_row"] = [int(n or m) for n, m in re.findall(r"\$(\d+)|Up to \$(\d+)", row.group(1))][:5]

    deals = re.search(r"(Limited-time bonus[^.]{0,80})", clean)
    if deals:
        out["note_seen"] = deals.group(1)[:70]
    return out


# --------------------------------------------------------------------------- open design

def open_design() -> dict:
    clean = text_of(fetch("https://open-design.ai/pricing/"))
    out: dict = {}

    # Go | regular price | monthly max | top models | design plan | per 7 days | per 5 h
    row = re.search(r"Go\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)", clean)
    if row:
        out["fee_usd"] = float(row.group(1))
        out["credits_usd"] = float(row.group(2))
        out["windows"] = {"week_usd": float(row.group(5)), "five_hours_usd": float(row.group(6))}

    html = fetch("https://open-design.ai/model-credits/")
    credits_text = text_of(html)
    go_row = re.search(
        r"Go\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)",
        credits_text)
    if go_row:
        out["fee_usd"] = float(go_row.group(1))
        out["credits_usd"] = float(go_row.group(2))
        out["windows"] = {"week_usd": float(go_row.group(5)),
                          "five_hours_usd": float(go_row.group(6))}
    pairs = re.findall(
        r'<th scope="row"[^>]*>\s*([^<]{2,40}?)\s*</th>.*?class="multiplier-value"[^>]*>\s*([\d.]+)x?',
        html, re.S)
    mults = {}
    for name, value in pairs:
        name = name.strip()
        if name.lower() in PLAN_TABS or not re.search(r"[A-Za-z]", name):
            continue
        mults[name] = float(value)
    if mults:
        out["multipliers"] = mults

    promo = re.search(r"(Off-peak promo[^.]{0,60})", text_of(html))
    if promo:
        out["promo_seen"] = promo.group(1)[:70]
    return out


# --------------------------------------------------------------------------- opengateway

def opengateway() -> dict:
    m = re.search(r'OPENGATEWAY_API_KEY:\s*"([^"]+)"', CREDS.read_text(encoding="utf-8"))
    if not m:
        return {"error": "no OPENGATEWAY_API_KEY in credentials"}
    try:
        body = fetch("https://apis.opengateway.ai/v1/models",
                     {"Authorization": f"Bearer {m.group(1)}"})
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}
    return {"models_available": [d.get("id") for d in json.loads(body).get("data", [])]}


# --------------------------------------------------------------------------- report

def main() -> int:
    stored = json.loads(PROVIDERS.read_text(encoding="utf-8"))
    write = "--write" in sys.argv
    print(f"providers.json: updated {stored.get('updated')}\n")

    for name, fn in (("command-code", command_code),
                     ("open-design", open_design),
                     ("opengateway", opengateway)):
        plan = stored["providers"][name]
        try:
            fresh = fn()
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: page unreadable ({exc!r}). Stored values kept.\n")
            continue

        print(name)
        for field in ("fee_usd", "credits_usd", "windows"):
            if field in fresh:
                old = plan.get(field)
                mark = "" if old == fresh[field] else f"   <- stored {old}"
                print(f"  {field}: {fresh[field]}{mark}")

        if "multipliers" in fresh:
            print(f"  multipliers: {len(fresh['multipliers'])} models")
            for model, value in fresh["multipliers"].items():
                hit = find(plan["models"], model)
                if hit is None:
                    print(f"    {model[:30]:30s} {value:<5} not in providers.json")
                    continue
                old = hit.get("factor", 1.0)
                mark = "" if old == value else f"   <- stored {old}"
                print(f"    {model[:30]:30s} {value:<5}{mark}")
                if write:
                    hit["factor"] = value

        if "models_available" in fresh:
            have = {m["id"] for m in plan["models"]}
            seen = set(fresh["models_available"])
            print(f"  the key sees {len(seen)}: {', '.join(sorted(seen))}")
            for gone in sorted(have - seen):
                print(f"    {gone}  stored but not offered to this key")

        for field in ("credits_row", "promo_seen", "note_seen", "error"):
            if field in fresh:
                print(f"  {field}: {fresh[field]}")

        if write:
            for field in ("fee_usd", "credits_usd", "windows"):
                if field in fresh:
                    plan[field] = fresh[field]
            for field in ("credits_row", "promo_seen"):
                if field in fresh:
                    plan[field] = fresh[field]
        print()

    if write:
        stored["updated"] = date.today().isoformat()
        stored["refreshed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        PROVIDERS.write_text(json.dumps(stored, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"written: providers.json (updated {stored['updated']})")
    else:
        print("nothing written. run with --write to store these numbers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
