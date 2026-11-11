#!/usr/bin/env python3
"""Capability and reasoning, from a third party instead of the vendor.

    python bench/capability.py           # refresh capability.json from AA
    python bench/capability.py --fit      # join it with the models that fit the price
    python bench/capability.py --probe <id>
                                          # ask the model itself whether it reasons

A provider's page is a sales page. Artificial Analysis publishes the index
everybody quotes, and ships it inside its model page as JSON, with `isReasoning`
and a score per effort variant. This reads the array AA marks as its own default
selection, which is one coherent set: same index, same variant policy.

Deliberately not done here: scraping every variant and keeping the best. AA scores
"Haiku 5.5" at 29.9 bare and 36.5 at max effort, and mixing the two scales is how
a comparison stops meaning anything. One set, one date, quoted with its variant.

A model AA does not list keeps an empty capability and stays out of the shortlist.
Unranked, not assumed. When the vendor and AA disagree on whether a model reasons,
`--probe` asks the model itself and looks for reasoning tokens.
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
CREDS = Path.home() / ".dsh" / ".credentials.yaml"
AA = "https://artificialanalysis.ai/models"
UA = {"User-Agent": "curl/8.5.0"}

sys.stdout.reconfigure(encoding="utf-8")


def fetch(url: str) -> str:
    with urlopen(Request(url, headers=UA), timeout=120) as resp:
        return resp.read().decode("utf-8", "replace")


def record(text: str, slug: str) -> dict | None:
    """One model on its own page: score, and the reasoning flag from nearby."""
    at = text.find(f'"slug":"{slug}"')
    while at >= 0:
        window = text[at:at + 4000]
        score = re.search(r'"intelligenceIndex":([\d.]+)', window)
        flag = re.search(r'"isReasoning":(true|false)', window)
        if score:
            return {"aa_slug": slug,
                    "aa_name": (re.search(r'"name":"([^"]{1,90})"', window) or [None, slug])[1],
                    "intelligence": float(score.group(1)),
                    "is_reasoning": (flag.group(1) == "true") if flag else None,
                    "engineering": None, "context_window": None, "release_date": None}
        at = text.find(f'"slug":"{slug}"', at + 1)
    return None


def page_text(slug: str) -> str | None:
    try:
        raw = fetch(f"https://artificialanalysis.ai/models/{slug}")
    except Exception:  # noqa: BLE001
        return None
    text = re.sub(r'"\]\)</script><script>self\.__next_f\.push\(\[1,"', "", raw)
    return text.replace('\\"', '"').replace("\\\\", "\\")


def build() -> dict:
    """AA's own default selection: the models its charts show by default."""
    raw = fetch(AA)
    text = re.sub(r'"\]\)</script><script>self\.__next_f\.push\(\[1,"', "", raw)
    text = text.replace('\\"', '"').replace("\\\\", "\\")

    at = text.find('"initialModels":[')
    if at < 0:
        raise SystemExit("AA payload changed: no initialModels array on the page")
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
            "context_window": m.get("contextWindowTokens"),
            "release_date": m.get("releaseDate"),
        }
    # Fill the models AA does not chart by default: their own page carries one
    # record, which is the whole point of using a page per model.
    wanted = set()
    for r in csv.DictReader(open(CATALOG, encoding="utf-8")):
        try:
            cost = float(r["best_turn"]) if r["best_turn"] else None
        except ValueError:
            continue
        if cost is not None and cost <= 0.0026:
            wanted.add(r["slug"])

    for slug in sorted(wanted):
        k = re.sub(r"[^a-z0-9]", "", slug.lower())
        if k in models:
            continue
        text = page_text(slug)
        if text is None:
            continue
        rec = record(text, slug)
        if rec:
            models[k] = rec

    return {
        "source": AA,
        "index": "Artificial Analysis Intelligence Index",
        "variant": "AA chart default selection (per-model highest-effort variant)",
        "fetched": datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated": date.today().isoformat(),
        "models": models,
    }


def load() -> dict:
    if not OUT.exists():
        raise SystemExit("no capability.json yet. run without flags.")
    return json.loads(OUT.read_text(encoding="utf-8"))


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def lookup(data: dict, slug: str, name: str) -> dict | None:
    models = data["models"]
    for candidate in (slug, name, name.split("(")[0]):
        k = norm(candidate)
        if k in models:
            return models[k]
    for k, rec in models.items():
        kn = norm(rec.get("aa_name") or "")
        if kn and (k.startswith(norm(slug)[:14]) or kn.startswith(norm(name)[:14])):
            return rec
    return None


def fit() -> int:
    data, cap_min, cost_max = load(), 0.0, 0.0026
    print(f"capability.json: {data['updated']} · {data['variant']}\n")
    print(f'{"modelo":30s} {"$/turno":>9} {"AA":>6} {"raz.":>6}  veredicto')
    inside, unknown = [], 0
    for r in csv.DictReader(open(CATALOG, encoding="utf-8")):
        try:
            cost = float(r["best_turn"]) if r["best_turn"] else None
        except ValueError:
            continue
        if cost is None or cost > cost_max:
            continue
        rec = lookup(data, r["slug"], r["name"])
        if rec is None or rec["intelligence"] is None:
            unknown += 1
            print(f'{r["slug"][:30]:30s} ${cost:8.4f} {"-":>6} {"-":>6}  no AA row')
            continue
        score = rec["intelligence"]
        reason = rec["is_reasoning"]
        if not reason:
            verdict = "out: not a reasoning model"
        else:
            verdict = "** IN **"
            inside.append((score, cost, r["slug"], r["name"]))
        print(f'{r["slug"][:30]:30s} ${cost:8.4f} {score:6.1f} {str(reason):>6}  {verdict}')

    print(f"\ncon AA y razonamiento: {len(inside)}   sin ficha en AA: {unknown}")
    for score, cost, slug, name in sorted(inside, key=lambda x: -x[0]):
        print(f"  {score:5.1f}  ${cost:.4f}  {slug:28s} {name[:34]}")
    return 0


def probe(model: str) -> int:
    k = re.search(r'COMMANDCODE_API_KEY:\s*"([^"]+)"', CREDS.read_text(encoding="utf-8"))
    if not k:
        raise SystemExit("no COMMANDCODE_API_KEY in credentials")
    body = json.dumps({"model": model, "max_tokens": 64,
                       "messages": [{"role": "user", "content":
                                     "A bat and a ball cost 1.10. The bat costs 1.00 more than the ball. "
                                     "What does the ball cost? Answer with the number."}]}).encode()
    req = Request("https://api.commandcode.ai/provider/v1/chat/completions", data=body,
                  headers={"Authorization": f"Bearer {k.group(1)}",
                           "Content-Type": "application/json", **UA}, method="POST")
    try:
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        print(f"{model}: probe failed ({exc}). No conclusion drawn.")
        return 1
    details = (data.get("usage") or {}).get("completion_tokens_details") or {}
    think = details.get("reasoning_tokens")
    message = (data.get("choices") or [{}])[0].get("message", {})
    carries = any(k in message for k in ("reasoning", "reasoning_content"))
    print(f"{model}: {'reasons' if (think or carries) else 'no reasoning tokens seen'}"
          f" (reasoning_tokens={think}, field={carries})")
    print(f"  answer: {(message.get('content') or '')[:80]!r}")
    return 0


def main() -> int:
    if "--probe" in sys.argv:
        return probe(sys.argv[sys.argv.index("--probe") + 1])
    if "--fit" in sys.argv:
        return fit()
    data = build()
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    scored = sum(1 for m in data["models"].values() if m["intelligence"] is not None)
    reasoning = sum(1 for m in data["models"].values() if m["is_reasoning"])
    print(f"{len(data['models'])} models from AA: {scored} scored, {reasoning} flagged reasoning")
    print(f"written: {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
