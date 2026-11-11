#!/usr/bin/env python3
"""Capability only: how good a model is, from Artificial Analysis.

    python bench/capability.py           # refresh capability.json

There is no public AA API (404 and 410), so this reads the dataset AA embeds in
its pages. One coherent set: the array AA marks as its chart default, plus a
per-model page for the rows AA does not chart but does score.

What this file does NOT do: decide whether a model reasons, calls tools, or what
it costs. That is identity, not quality, and it comes from models.dev through
bench/modelsdb.py. Two sources, two questions, no overlap.

A model AA has not scored keeps an empty capability and goes to the owner instead
of being assumed.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.request import Request, urlopen

BENCH = Path(__file__).resolve().parent
OUT = BENCH / "capability.json"
CATALOG = BENCH / "catalog-2026-11-10.csv"
AA = "https://artificialanalysis.ai/models"
UA = {"User-Agent": "curl/8.5.0"}

sys.stdout.reconfigure(encoding="utf-8")


def fetch(url: str) -> str:
    with urlopen(Request(url, headers=UA), timeout=120) as resp:
        return resp.read().decode("utf-8", "replace")


def joined(raw: str) -> str:
    text = re.sub(r'"\]\)</script><script>self\.__next_f\.push\(\[1,"', "", raw)
    return text.replace('\\"', '"').replace("\\\\", "\\")


def page_record(text: str, slug: str) -> dict | None:
    at = text.find(f'"slug":"{slug}"')
    while at >= 0:
        window = text[at:at + 4000]
        score = re.search(r'"intelligenceIndex":([\d.]+)', window)
        flag = re.search(r'"isReasoning":(true|false)', window)
        if score:
            return {"aa_slug": slug, "intelligence": float(score.group(1)),
                    "is_reasoning": (flag.group(1) == "true") if flag else None}
        at = text.find(f'"slug":"{slug}"', at + 1)
    return None


def build() -> dict:
    text = joined(fetch(AA))
    at = text.find('"initialModels":[')
    if at < 0:
        raise SystemExit("AA payload changed: no initialModels array")
    start = text.index("[", at)
    depth, i = 0, start
    while i < len(text):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                break
        i += 1

    models = {}
    for m in json.loads(text[start:i + 1]):
        slug = m.get("slug")
        if not slug:
            continue
        models[re.sub(r"[^a-z0-9]", "", slug.lower())] = {
            "aa_slug": slug,
            "aa_name": m.get("name"),
            "intelligence": m.get("intelligenceIndex"),
            "engineering": (m.get("capabilities") or {}).get("engineering"),
            "is_reasoning": m.get("isReasoning"),
        }

    # rows AA scores but does not chart: their own page carries one record
    for r in csv.DictReader(open(CATALOG, encoding="utf-8")):
        try:
            cost = float(r["best_turn"]) if r["best_turn"] else None
        except ValueError:
            continue
        if cost is None or cost > 0.0026:
            continue
        k = re.sub(r"[^a-z0-9]", "", r["slug"].lower())
        if k in models:
            continue
        try:
            rec = page_record(joined(fetch(f"{AA}/{r['slug']}")), r["slug"])
        except Exception:  # noqa: BLE001
            continue
        if rec:
            models[k] = rec

    return {
        "source": AA,
        "index": "Artificial Analysis Intelligence Index",
        "variant": "AA chart default selection, plus the model's own page",
        "fetched": datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated": date.today().isoformat(),
        "models": models,
    }


def main() -> int:
    data = build()
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    scored = sum(1 for m in data["models"].values() if m["intelligence"] is not None)
    print(f"{len(data['models'])} models, {scored} with a score")
    print(f"written: {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
