#!/usr/bin/env python3
"""What a model is, from models.dev — and never from the shop selling it.

    python bench/modelsdb.py           # refresh models.dev.json
    python bench/modelsdb.py --probe <id>
                                       # ask the model itself whether it reasons

models.dev is a third-party catalogue of 3,500+ models across 235 providers, with
`reasoning`, `tool_call`, context and price per model. This keeps only the rows
this repo cares about, so the snapshot stays small and readable.

It carries no quality score, and this file does not invent one. Capability is
decided by the test battery, or by the owner when a number is not enough.
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
OUT = BENCH / "models.dev.json"
CATALOG = BENCH / "catalog-2026-11-10.csv"
PROVIDERS = BENCH / "providers.json"
CREDS = Path.home() / ".dsh" / ".credentials.yaml"
URL = "https://models.dev/api.json"
UA = {"User-Agent": "curl/8.5.0"}
LANES = ("fast", "eco", "ultrafast", "preview", "latest", "sync", "max", "high", "xhigh")

sys.stdout.reconfigure(encoding="utf-8")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def wanted() -> set[str]:
    names = set()
    for r in csv.DictReader(open(CATALOG, encoding="utf-8")):
        names.add(norm(r["slug"]))
    plans = json.loads(PROVIDERS.read_text(encoding="utf-8"))["providers"]
    for plan in plans.values():
        if isinstance(plan["models"], list):
            for m in plan["models"]:
                names.add(norm(m["id"].split("/")[-1]))
    return {n for n in names if n}


def stripped(key: str) -> str:
    base = key
    for lane in LANES:
        base = base.replace(lane, "")
    return base


def build() -> dict:
    body = json.loads(urlopen(Request(URL, headers=UA), timeout=180).read().decode())
    want = wanted()
    rows, seen = {}, set()

    for provider, data in body.items():
        for mid, meta in (data.get("models") or {}).items():
            bare = norm(mid.split("/")[-1])
            if bare not in want and stripped(bare) not in want:
                continue
            canonical = meta.get("canonical_model_id")
            replacement, cross_generation = None, False
            if canonical:
                bare_canonical = norm(canonical.split("/")[-1])
                if bare_canonical != bare:
                    replacement = canonical
                    # "v4.1-flash" -> "v4.1-flash-1017" is a newer build of the
                    # same model; "v4-flash" -> "v4.1-flash-1017" is a successor.
                    cross_generation = not bare_canonical.startswith(bare)
            deprecated = meta.get("status") == "deprecated"
            prev = rows.get(bare)
            if prev:
                # any provider saying deprecated is enough; the vendor knows first.
                # Record it before skipping, or the flag is computed and thrown away.
                prev["deprecated"] = deprecated or prev["deprecated"]
                if replacement and (cross_generation or not prev["cross_generation"]):
                    prev["superseded_by"] = replacement
                    prev["cross_generation"] = cross_generation
                # carry it into the local copy too: the commandcode entry wins the
                # row and would otherwise rebuild it without what we just learned
                deprecated = prev["deprecated"]
                replacement = prev["superseded_by"]
                cross_generation = prev["cross_generation"]
                if provider != "commandcode":
                    continue
            seen.add(bare)
            rows[bare] = {
                "deprecated": deprecated,
                "superseded_by": replacement,
                "cross_generation": cross_generation,
                "id": mid,
                "provider": provider,
                "name": meta.get("name"),
                "reasoning": meta.get("reasoning"),
                "tool_call": meta.get("tool_call"),
                "context": (meta.get("limit") or {}).get("context"),
                "cost": meta.get("cost"),
                "modalities": meta.get("modalities"),
                "release_date": meta.get("release_date"),
            }
    # A deprecated row usually names its successor. The provider serves "latest",
    # so the honest reading is the successor's facts, not dropping the model.
    index = {}
    for provider, data in body.items():
        for mid, meta in (data.get("models") or {}).items():
            index[mid] = meta
    for rec in rows.values():
        by = rec.get("superseded_by")
        if not by or rec.get("cross_generation"):
            continue        # a real successor: the row stays superseded
        target = index.get(by)
        if target is None:
            continue
        rec["resolved_to"] = by
        rec["reasoning"] = target.get("reasoning")
        rec["tool_call"] = target.get("tool_call")
        rec["context"] = (target.get("limit") or {}).get("context")
        rec["cost"] = target.get("cost")
        rec["release_date"] = target.get("release_date")
        rec["deprecated"] = False        # the chain ends somewhere alive

    return {
        "source": "https://models.dev/api.json",
        "fetched": datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated": date.today().isoformat(),
        "models": rows,
    }


def probe(model: str) -> int:
    """Ask the model a question and look for reasoning tokens in the answer."""
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
    carries = any(f in message for f in ("reasoning", "reasoning_content"))
    print(f"{model}: {'reasons' if (think or carries) else 'no reasoning tokens seen'}"
          f" (reasoning_tokens={think}, field={carries})")
    print(f"  answer: {(message.get('content') or '')[:80]!r}")
    return 0


def main() -> int:
    if "--probe" in sys.argv:
        return probe(sys.argv[sys.argv.index("--probe") + 1])
    data = build()
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    gone = sum(1 for m in data["models"].values() if m["deprecated"])
    print(f"{gone} of them are deprecated in models.dev")
    reasoning = sum(1 for m in data["models"].values() if m["reasoning"])
    tools = sum(1 for m in data["models"].values() if m["tool_call"])
    print(f"{len(data['models'])} of our models found in models.dev: "
          f"{reasoning} reason, {tools} call tools")
    print(f"written: {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
