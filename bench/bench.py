#!/usr/bin/env python3
"""bench — one script, two data files, three questions.

    python bench/bench.py refresh            # re-read the providers and both catalogues
    python bench/bench.py refresh --write    # store what it parsed in data/
    python bench/bench.py plan               # what a subscription costs per token
    python bench/bench.py plan --today 2026-10-22
    python bench/bench.py plan --model deepseek-v4-pro
    python bench/bench.py select             # fold 1: what is worth calling at all
    python bench/bench.py measure            # fold 2: the stored table against the gates
    python bench/bench.py agentic --provider opendesign --model deepseek-v4.1-flash
    python bench/bench.py test               # models.dev cannot move a price

Three questions, in the order they cost money:

  plan     what a plan really charges per million tokens: the fee, the model's
           multiplier, the promo inside its window, and the peak share of the
           week. Free, calls no model.
  select   fold 1: price, identity (models.dev), capability (AA), then the policy.
           Free, calls no model.
  measure  fold 2: speed, latency, cache, prefill, retention, errors, tool calls.
           fold 3: agentic.py's task — a real bug, a real repository, pytest.

data/plans.json   the plans, what they publish, and the catalogue they price from
data/models.json  what a model is, and how good it is

Nothing here edits the DSH configuration; that is a separate change in ../dsh/.
"""

from __future__ import annotations

import argparse
import copy
import csv
import inspect
import json
import re
import shutil
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from urllib.request import Request, urlopen

BENCH = Path(__file__).resolve().parent
REPO = BENCH.parent
DATA = BENCH / "data"
PLANS_FILE = DATA / "plans.json"
MODELS_FILE = DATA / "models.json"
POLICY = BENCH / "models-policy.yml"
MEASURED = BENCH / "models.csv"
CONFIG = REPO / "dsh" / "cordis.patch.yml"
SNAPSHOTS = BENCH / "snapshots"
CREDS = Path.home() / ".dsh" / ".credentials.yaml"

TURN = 91_500          # 89k cache + 1k fresh + 1.5k written, one agent turn
FX = 6.714             # CNY per USD, the rate a Chinese price list is read at
DAYS = 30.0            # a month, for the windows
LANES = ("fast", "eco", "ultrafast", "preview", "latest", "sync", "max", "high", "xhigh")
UA = {"User-Agent": "curl/8.5.0"}
AA_URL = "https://artificialanalysis.ai/models"
MODELS_URL = "https://models.dev/api.json"
GATEWAYS = {
    "command-code": ("https://api.commandcode.ai/provider/v1", "COMMANDCODE_API_KEY"),
    "opendesign": ("https://amr-link.open-design.ai/v1", "OPENDESIGN_API_KEY"),
}

sys.stdout.reconfigure(encoding="utf-8")


# --------------------------------------------------------------------------- core

def norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch(url: str, headers: dict | None = None, timeout: int = 120) -> str:
    req = Request(url, headers={**UA, **(headers or {})})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def text_of(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html))


def plans() -> dict:
    return read_json(PLANS_FILE)


def catalogue() -> dict:
    """slug -> the three things fold 1 asks of a price row."""
    return {slug: {"name": row["name"], "capability": row.get("intelligence"),
                   "cost": row.get("turn")}
            for slug, row in plans()["catalog"].items()}


def identities() -> dict:
    return read_json(MODELS_FILE)["models.dev"]["models"]


def scores() -> dict:
    return read_json(MODELS_FILE)["capability"]["models"]


def load_policy() -> tuple[dict, set]:
    """The gates and the admitted ids, as models-policy.yml states them."""
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


def capability_overrides() -> dict[str, tuple[float, str]]:
    """Scores the sources cannot give, written down by the owner with a basis."""
    out: dict[str, tuple[float, str]] = {}
    inside = False
    for line in POLICY.read_text(encoding="utf-8").splitlines():
        if line.startswith("capability_overrides:"):
            inside = True
            continue
        if inside and line and not line.startswith((" ", "#")):
            break
        m = re.match(r"\s*-?\s*\{id:\s*([^,]+),\s*score:\s*([\d.]+)", line)
        if inside and m:
            basis = re.search(r'basis:\s*"([^"]*)"', line)
            out[norm(m.group(1))] = (float(m.group(2)), basis.group(1) if basis else "")
    return out

# --------------------------------------------------------------------------- refresh

MONTHS = {name: i for i, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}


def promo_block(text: str, today: date | None = None) -> dict | None:
    """A dated offer, as a window plus the multiplier it drops to.

    A promo whose end date nobody stored is indistinguishable from a price, and
    that is how a one-week offer ends up quoted as a standing one. The multiplier
    is the value it drops *to*: 0,5x -> 0,25x is a 0,25x week, not a plan.
    """
    m = re.search(r"((?:[A-Z][A-Za-z0-9.\-]*)(?:\s+[A-Z0-9][A-Za-z0-9.\-]*){0,4})"
                  r"\s+Off-peak promo\s*\?(.{0,320})", text)
    if not m:
        return None
    model, rest = m.group(1).strip(), m.group(2)
    mult = re.search(r"from\s+([\d.]+)\s*[×x]\s*to\s+([\d.]+)\s*[×x]", rest)
    days = re.findall(r"([A-Z][a-z]+)\s+(\d{1,2})\s+at\s+\d{1,2}:\d{2}", rest)
    if not (mult and len(days) == 2):
        return None
    today = today or date.today()

    def iso(month: str, day: str) -> str | None:
        try:
            when = date(today.year, MONTHS[month], int(day))
        except (KeyError, ValueError):
            return None
        if (when - today).days > 30:          # a December end read in January
            when = when.replace(year=when.year - 1)
        if (when - today).days < -300:        # a January end read in December
            when = when.replace(year=when.year + 1)
        return when.isoformat()

    start, end = iso(*days[0]), iso(*days[1])
    if not (start and end):
        return None
    seen = re.sub(r"\s+", " ", f"{model} — {rest}").strip()[:200]
    seen = seen[:seen.rfind(".") + 1] if "." in seen else seen
    return {"model": model, "multiplier": float(mult.group(2)),
            "from": start, "until": end, "seen": seen}


def find_model(entries: list, name: str):
    """Exact key first, then the loosest substring: Flash and Flash-X differ by one
    letter and must not be confused."""
    target = norm(name)
    for m in entries:
        if norm(m["id"]) == target:
            return m
    for m in entries:
        a = norm(m["id"])
        if a.endswith(target) or target in a or a in target:
            return m
    return None


def command_code_page() -> dict:
    clean = text_of(fetch("https://commandcode.ai/pricing"))
    out: dict = {}
    goat = re.search(r"GOAT\s*\$\s*(\d+)\s*/\s*month.*?Up to \$(\d+)\s*in credits", clean)
    if goat:
        out["fee_usd"] = float(goat.group(1))
        out["credits_usd"] = float(goat.group(2))
    row = re.search(r"Monthly credits(.{0,160})", clean)
    if row:
        out["credits_row"] = [int(n or m) for n, m in
                              re.findall(r"\$(\d+)|Up to \$(\d+)", row.group(1))][:5]
    deals = re.search(r"(Limited-time bonus[^.]{0,160})", clean)
    if deals:
        out["note_seen"] = deals.group(1).strip()
    return out


def open_design_page() -> dict:
    clean = text_of(fetch("https://open-design.ai/pricing/"))
    out: dict = {}
    row = re.search(r"Go\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)", clean)
    if row:
        out["fee_usd"] = float(row.group(1))
        out["credits_usd"] = float(row.group(2))
        out["windows"] = {"week_usd": float(row.group(5)), "five_hours_usd": float(row.group(6))}

    html = fetch("https://open-design.ai/model-credits/")
    credits_text = text_of(html)
    go_row = re.search(r"Go\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)\s*\$(\d+)", credits_text)
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
        if name.lower() in {"go", "go plus", "go pro", "go max", "plus", "pro", "max"}:
            continue
        if not re.search(r"[A-Za-z]", name):
            continue
        mults[name] = float(value)
    if mults:
        out["multipliers"] = mults
    promo = promo_block(text_of(html))
    if promo:
        out["promos"] = [promo]
    return out


def refresh_plans(store: dict, write: bool) -> None:
    for name, page in (("command-code", command_code_page), ("open-design", open_design_page)):
        plan = store["providers"][name]
        try:
            fresh = page()
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
                hit = find_model(plan["models"], model)
                if hit is None:
                    print(f"    {model[:30]:30s} {value:<5} not in plans.json")
                    continue
                old = hit.get("factor", 1.0)
                mark = "" if old == value else f"   <- stored {old}"
                print(f"    {model[:30]:30s} {value:<5}{mark}")
                if write:
                    hit["factor"] = value
        for promo in fresh.get("promos", []):
            print(f"  promo: {promo['model']} {promo['multiplier']:g}x  "
                  f"{promo['from']} -> {promo['until']}")
        for field in ("credits_row", "note_seen", "error"):
            if field in fresh:
                value = fresh[field]
                shown = f"{value[:100]}…" if isinstance(value, str) and len(value) > 100 else value
                print(f"  {field}: {shown}")
        if write:
            for field in ("fee_usd", "credits_usd", "windows", "credits_row", "promos"):
                if field in fresh:
                    plan[field] = fresh[field]
        print()


def wanted_ids(store: dict) -> set[str]:
    names = {norm(slug) for slug in store["catalog"]}
    for plan in store["providers"].values():
        if isinstance(plan["models"], list):
            names |= {norm(m["id"].split("/")[-1]) for m in plan["models"]}
    return {n for n in names if n}


def lane_stripped(key: str) -> str:
    base = key
    for lane in LANES:
        base = base.replace(lane, "")
    return base


def build_models(store: dict) -> dict:
    body = json.loads(fetch(MODELS_URL, timeout=180))
    want = wanted_ids(store)
    rows, seen = {}, set()

    for provider, data in body.items():
        for mid, meta in (data.get("models") or {}).items():
            bare = norm(mid.split("/")[-1])
            if bare not in want and lane_stripped(bare) not in want:
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
                prev["deprecated"] = deprecated or prev["deprecated"]
                if replacement and (cross_generation or not prev["cross_generation"]):
                    prev["superseded_by"] = replacement
                    prev["cross_generation"] = cross_generation
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
    index = {mid: meta for data in body.values() for mid, meta in (data.get("models") or {}).items()}
    for rec in rows.values():
        by = rec.get("superseded_by")
        if not by or rec.get("cross_generation"):
            continue
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
        "source": MODELS_URL,
        "fetched": datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated": date.today().isoformat(),
        "models": rows,
    }


def aa_joined(raw: str) -> str:
    text = re.sub(r'"\]\)</script><script>self\.__next_f\.push\(\[1,"', "", raw)
    return text.replace('\\"', '"').replace("\\\\", "\\")


def aa_page_record(text: str, slug: str) -> dict | None:
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


def build_capability(store: dict) -> dict:
    text = aa_joined(fetch(AA_URL))
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
        models[norm(slug)] = {
            "aa_slug": slug,
            "aa_name": m.get("name"),
            "intelligence": m.get("intelligenceIndex"),
            "engineering": (m.get("capabilities") or {}).get("engineering"),
            "is_reasoning": m.get("isReasoning"),
        }

    # rows AA scores but does not chart: their own page carries one record
    for slug, row in store["catalog"].items():
        cost = row.get("turn")
        if cost is None or cost > 0.0026:
            continue
        k = norm(slug)
        if k in models:
            continue
        try:
            rec = aa_page_record(aa_joined(fetch(f"{AA_URL}/{slug}")), slug)
        except Exception:  # noqa: BLE001
            continue
        if rec:
            models[k] = rec

    return {
        "source": AA_URL,
        "index": "Artificial Analysis Intelligence Index",
        "variant": "AA chart default selection, plus the model's own page",
        "fetched": datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated": date.today().isoformat(),
        "models": models,
    }


FORCEBENCH_URL = "https://forcebench.ai/leaderboard.json"


def build_forcebench(store: dict) -> dict:
    """Forcebench: how often a model does real Salesforce work, executed and graded.

    A different question from AA's index - Apex, Flow, LWC and SOQL that has to
    pass hidden tests in a scratch org - so it is stored as its own scale and no
    gate reads it. Best configuration per model, with its interval.
    """
    data = json.loads(fetch(FORCEBENCH_URL, timeout=120))
    want = wanted_ids(store)
    best: dict[str, dict] = {}
    for entry in data.get("entries") or []:
        mid = entry.get("model_id") or entry.get("model") or ""
        overall = entry.get("overall") or {}
        score = overall.get("score")
        if score is None:
            continue
        key = norm(mid)
        if key not in want and lane_stripped(key) not in want:
            continue
        if key in best and best[key]["score"] >= score:
            continue
        best[key] = {
            "name": entry.get("model"), "model_id": mid, "score": score,
            "ci_low": overall.get("ci_low"), "ci_high": overall.get("ci_high"),
            "provider": entry.get("provider"), "effort": entry.get("effort"),
            "open_weights": entry.get("open_weights"),
        }
    return {
        "source": FORCEBENCH_URL, "benchmark": data.get("benchmark"),
        "version": data.get("version"), "generated_at": data.get("generated_at"),
        "domain": "Salesforce engineering: Apex, Flow, LWC, SOQL, packaging",
        "tasks": len(data.get("tasks") or []),
        "suites": [(s.get("id"), s.get("n_tasks")) for s in data.get("suites") or []],
        "fetched": datetime.now().astimezone().isoformat(timespec="seconds"),
        "models": best,
    }


def cmd_refresh(args) -> int:
    store = plans()
    only = {s.strip() for s in (args.only or "plans,models,capability,forcebench").split(",") if s.strip()}
    data = read_json(MODELS_FILE)

    if "plans" in only:
        refresh_plans(store, args.write)

    if "models" in only:
        try:
            fresh = build_models(store)
            gone = sum(1 for m in fresh["models"].values() if m["deprecated"])
            reasons = sum(1 for m in fresh["models"].values() if m["reasoning"])
            tools = sum(1 for m in fresh["models"].values() if m["tool_call"])
            print(f"models.dev: {len(fresh['models'])} of our models, {gone} deprecated, "
                  f"{reasons} reason, {tools} call tools")
            if args.write:
                data["models.dev"] = fresh
                write_json(MODELS_FILE, data)
                print(f"written: {MODELS_FILE.relative_to(REPO)}")
        except Exception as exc:  # noqa: BLE001
            print(f"models.dev unreadable ({exc!r}). Stored rows kept.")

    if "capability" in only:
        try:
            fresh = build_capability(store)
            scored = sum(1 for m in fresh["models"].values() if m["intelligence"] is not None)
            print(f"artificial analysis: {len(fresh['models'])} models, {scored} with a score")
            if args.write:
                data["capability"] = fresh
                write_json(MODELS_FILE, data)
                print(f"written: {MODELS_FILE.relative_to(REPO)}")
        except Exception as exc:  # noqa: BLE001
            print(f"artificial analysis unreadable ({exc!r}). Stored rows kept.")

    if "forcebench" in only:
        try:
            fresh = build_forcebench(store)
            print(f"forcebench: {len(fresh['models'])} of our models, {fresh['tasks']} tasks, "
                  f"v{fresh['version']} ({fresh['generated_at'][:10]})")
            if args.write:
                data["forcebench"] = fresh
                write_json(MODELS_FILE, data)
                print(f"written: {MODELS_FILE.relative_to(REPO)}")
        except Exception as exc:  # noqa: BLE001
            print(f"forcebench unreadable ({exc!r}). Stored rows kept.")

    if args.write and "plans" in only:
        store["updated"] = date.today().isoformat()
        store["refreshed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        write_json(PLANS_FILE, store)
        print(f"written: {PLANS_FILE.relative_to(REPO)}")
    else:
        print("nothing written. run with --write to store these numbers.")
    return 0


# --------------------------------------------------------------------------- plan: money

def blend_of(row: dict) -> float:
    """The week, weighted: peak hours are a share of it, and they cost more.

    The catalogue carries the shop's own words ("Off-peak shown (17h/day) · peak
    $0.30 / $1.20") already reduced to `peak_hours_per_day` and
    `peak_multiplier`; a row with neither has one price, and 1,0 is not a guess.
    """
    hours, mult = row.get("peak_hours_per_day"), row.get("peak_multiplier")
    if not hours or not mult:
        return 1.0
    return 1.0 + (hours / 24) * (5 / 7) * (mult - 1.0)


def plan_caps(plan: dict, monthly: float | None) -> tuple[float | None, str]:
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


def live_promo(plan: dict, model_id: str, day: date) -> float | None:
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


def plan_lookup(cat: dict, model_id: str) -> dict:
    """The catalogue's row for this model, whatever lane the plan calls it."""
    target = norm(re.sub(r"\([^)]*\)", "", model_id))
    for slug, row in cat.items():
        if norm(slug) == target:
            return row
    return {}


def plan_rows(day: date, want: str) -> list[dict]:
    store = plans()
    cat = store["catalog"]
    target = norm(want)
    out: list[dict] = []

    for provider, plan in store["providers"].items():
        entries = ([{"id": slug, "catalog": slug} for slug in cat]
                   if plan["models"] == "catalog" else plan["models"])
        # A plan that sells the peak lane as its own row is telling us the price
        # moves with the hour; the blend weighs it, so that row is not a second
        # purchase and is not counted twice.
        moves = any("(peak)" in e["id"].lower() for e in entries)
        for m in entries:
            if "(peak)" in m["id"].lower():
                continue
            bare = norm(re.sub(r"\([^)]*\)", "", m["id"]))
            if target not in (norm(m["id"]), norm(m["id"].split("/")[-1]), bare):
                continue
            row = cat.get(m.get("catalog") or "") or plan_lookup(cat, m["id"])
            listed = m["list_turn_usd"] if "list_turn_usd" in m else row.get("turn")
            if listed is None:
                continue
            monthly = m.get("monthly_limit_usd")
            monthly = monthly if isinstance(monthly, (int, float)) else plan.get("credits_usd")
            usable, bound = plan_caps(plan, monthly)
            offer = live_promo(plan, m["id"], day)
            hourly = blend_of(row) if (moves or "list_turn_usd" not in m) else 1.0
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
    if row and row.get("turn"):
        per_turn = float(row["turn"]) * blend_of(row)
        name = row["name"]
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


def cmd_plan(args) -> int:
    day = args.today or date.today()
    got = plan_rows(day, args.model)
    if not got:
        print(f"no plan serves {args.model}; try an id from data/plans.json")
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

    blend = blend_of(plans()["catalog"].get(args.model, {}))
    print(f"\n  turn {TURN:,} tokens (89k cache + 1k fresh + 1.5k written) · "
          f"peak {blend - 1:.1%} of the week, priced x{blend:.2f} on the blend · "
          f"1 ¥ = ${1 / FX:.4f}")
    print("  tokens/¥ = what 1 CNY buys at that plan's blended marginal price")

    if args.write:
        path = snapshot(f"plan-cost-{day.isoformat()}.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(got[0].keys()))
            w.writeheader()
            w.writerows(got)
        print(f"\nwritten: {path.relative_to(REPO)}")
    return 0


# --------------------------------------------------------------------------- select: fold 1

GAP_WORDS = re.compile(r"no (capability|data|score|ficha)|unmeasured|unranked|sin ficha",
                       re.IGNORECASE)


def judged_models() -> list[tuple[str, str | None]]:
    """(model, provider or None) the policy has already judged.

    A reason earned on one lane says nothing about another: the same model is a
    different route somewhere else, with its own speed and its own failures.
    """
    text = POLICY.read_text(encoding="utf-8")
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


def is_excluded(judged, model: str, provider: str) -> bool:
    key = norm(model.split("/")[-1])
    return any(k == key and (p is None or p == provider) for k, p in judged)


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
    for probe in probes:
        if not probe:
            continue
        for key, rec in table.items():
            rest = key[len(probe):] if key.startswith(probe) else ""
            if rest.isdigit():
                return rec
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
            # What models.dev says the same turn costs, next to what the shop
            # charges. A cross-check for a human, never an input: no gate reads
            # this column, and `bench.py test` fails if one ever does.
            "crosscheck_turn_usd": crosscheck_turn(fact.get("cost")),
        })
    return out


def crosscheck_turn(cost: dict | None) -> float | None:
    """A turn of 89k cached, 1k fresh and 1.5k written, at models.dev prices.

    Not a price of anything this fold buys: models.dev is a third party with its
    own lane and its own mix. This exists so a reader can see the shop's figure
    next to somebody else's, and it stops there.
    """
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
             oldest: str | None = None, require_aa: bool = False) -> tuple[str, str]:
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
        # The policy may refuse to buy what it cannot compare. That is a purchase
        # rule, not a judgement about the model: AA covers a subset, and a row it
        # has not scored is not assumed bad.
        if require_aa:
            return "out", "policy: AA does not rank it, and this policy buys ranked rows only"
        # Otherwise an unranked model is a question, not a verdict — unless it was
        # already old when the menu's oldest row shipped. Then nobody is going to
        # score it and waiting is just noise.
        released = row.get("release_date")
        if oldest and released and released < oldest:
            return "out", f"no score and released {released}, before the menu's oldest ({oldest})"
        return "human", "no AA score: capability unknowable"
    if row["aa"] < cap_min:
        return "out", f"capability {row['aa']:.1f} < {cap_min:.1f}"
    return "battery", ""


def cmd_select(args) -> int:
    store = plans()
    gates = load_policy()[0]["static"]
    cost_max = float(gates["cost_max"])
    cap_min = float(gates["capability_min"])
    catalog = catalogue()
    table, score_table, judged = identities(), scores(), judged_models()
    overrides = capability_overrides()
    fb = read_json(MODELS_FILE).get("forcebench", {}).get("models", {})

    def fb_of(model_id: str) -> float | None:
        # Forcebench names the same model, sometimes with its build: same probes
        # as the AA lookup, and the same rule about a suffix of digits.
        bare = norm(model_id.split("/")[-1])
        for probe in (bare, lane_stripped(bare)):
            hit = fb.get(probe)
            if hit:
                return hit["score"] * 100
            for key, rec in fb.items():
                rest = key[len(probe):] if key.startswith(probe) else ""
                if rest.isdigit():
                    return rec["score"] * 100
        return None
    admitted_ids = load_policy()[1]
    dates = [fact_of(table, i.split("/")[-1], "").get("release_date") for i in admitted_ids]
    oldest = min([d for d in dates if d], default=None)

    print(f"fold 1 · price <= ${cost_max:.4f}/turn · reasoning and tools from models.dev\n")
    rows = []
    for pname, plan in store["providers"].items():
        if plan.get("active") is False:
            print(f"\n{pname}  [prepared, not enabled] {plan.get('note', '')[:90]}")
            continue
        money = f"${plan['fee_usd']:.0f}/{plan.get('billing', 'mo')}" if plan.get("fee_usd") else "prepaid"
        credits = f" + ${plan['credits_usd']:.0f} credits" if plan.get("credits_usd") else ""
        print(f"{pname}  [{plan['plan']} {money}{credits}]")

        buckets = {"battery": [], "human": [], "out": []}
        for row in model_rows(plan, catalog, table, score_table):
            row["provider"] = pname        # before the gates: an exclusion is per lane
            if row["aa"] is None:
                borrowed = overrides.get(norm(row["model"].split("/")[-1]))
                if borrowed:
                    row["aa"], row["aa_basis"] = borrowed
            bucket, why = classify(row, cost_max, cap_min, judged, oldest,
                                   require_aa=bool(gates.get("require_aa")))
            row.update(plan=plan["plan"], plan_fee_usd=plan.get("fee_usd"),
                       plan_credits_usd=plan.get("credits_usd"), bucket=bucket, why=why,
                       cold_call_usd=cold_call(row))
            buckets[bucket].append(row)
            rows.append(row)

        for row in sorted(buckets["battery"], key=lambda r: r["effective_turn_usd"]):
            cold = cold_call(row)
            extra = f"  1.a ${cold:.5f}" if cold else ""
            mark = "*" if row.get("aa_basis") else ""
            score = fb_of(row["model"])
            print(f"  run   {pname:13s} {row['model'][:28]:28s} "
                  f"fb {(f'{score:5.1f}' if score is not None else '    -')}  "
                  f"uso ${row['effective_turn_usd']:.5f}  real ${row['real_turn_usd']:.6f}{extra}{mark}")
        for row in sorted(buckets["human"], key=lambda r: r["effective_turn_usd"]):
            aa = "-" if row["aa"] is None else f"{row['aa']:.1f}"
            score = fb_of(row["model"])
            print(f"  ????  {pname:13s} {row['model'][:28]:28s} "
                  f"fb {(f'{score:5.1f}' if score is not None else '    -')}  "
                  f"real ${row['real_turn_usd']:.6f}  AA {aa:>5}  {row['why']}")
        print(f"  ({len(buckets['out'])} out)")

    for row in rows:
        if row.get("aa_basis"):
            print(f"  * {row['model']}: AA {row['aa']:.1f} is the owner's, not AA's — {row['aa_basis']}")

    if fb:
        print(f"  fb = Forcebench v{read_json(MODELS_FILE)['forcebench']['version']}, 272 Salesforce "
              f"tasks run against hidden tests — another question, not the AA scale")

    battery = [r for r in rows if r["bucket"] == "battery"]
    human = [r for r in rows if r["bucket"] == "human"]
    print(f"\n{len(rows)} models: {len(battery)} to the battery, {len(human)} need a human, "
          f"{len(rows) - len(battery) - len(human)} out.\n")

    gap_rows = [r for r in rows if r["bucket"] != "out" and gaps(r)]
    if gap_rows:
        print("PARA TI — falta un dato, y eso no lo decide el programa:")
        for r in sorted(gap_rows, key=lambda x: x["effective_turn_usd"] or 0):
            print(f"  {r['provider']:13s} {r['model'][:30]:30s} "
                  f"real ${r['real_turn_usd']:.6f}  falta: {', '.join(gaps(r))}")
        print()

    if human:
        print("waiting on a decision:")
        for r in sorted(human, key=lambda x: x["effective_turn_usd"] or 0):
            print(f"  {r['provider']:13s} {r['model']:30s} real ${r['real_turn_usd']:.6f}  {r['why']}")

    if args.write:
        path = snapshot(f"shortlist-{date.today().isoformat()}.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nwritten: {path.relative_to(REPO)}")
    return 0


def snapshot(name: str) -> Path:
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    return SNAPSHOTS / name

# --------------------------------------------------------------------------- measure: fold 2

CORPUS = ("Line {i} of the reference corpus: the quick brown fox jumps over the lazy dog "
          "while the engineer reviews patch number {i} and notes that the cache behaviour "
          "of model {i} remains under observation.\n")
ESSAY = ("Write a continuous 1500-word essay on the history of writing instruments, "
         "from stylus to ballpoint. Plain prose, no lists, no headings. Do not stop early.")

TOOLS = [
    {"name": "get_weather", "description": "Current weather for a city", "param": "city"},
    {"name": "get_time", "description": "Current local time for a city", "param": "city"},
]
TOOL_PROMPT = ("Call get_weather for Seville and get_time for Seville. "
               "Use both tools in this single reply. Do not answer in prose.")

AA_LANES = ("fast", "eco", "ultrafast", "preview", "latest", "sync")
CONTEXT_K = 60
ANSWER_TOKENS = 1500

GATES: dict[str, dict[str, float]] = {}
ADMITTED: set[str] = set()
BASE = ""
KEY_ENV = ""
KEY = ""


def load_measured() -> dict:
    out = {}
    for r in csv.DictReader(open(MEASURED, encoding="utf-8")):
        def num(k):
            v = r.get(k) or ""
            return float(v) if v else None
        out[r["slug"]] = {
            "id": r["slug"], "catalog": r["catalog_slug"], "name": r["name"],
            "speed": num("speed_tps"), "ttft": num("ttft_s"), "cache": num("cache_hit"),
            "prefill": num("prefill_ms_per_1k"), "cache_loop": num("cache_loop_hit"),
            "retention": num("retention_4x"), "errors": num("errors_10"),
            "tools": num("tools_valid"), "override": num("intel_override"),
            "cost_override": num("cost_override"),
        }
    return out


def aa_of(ratings: dict, model_id: str, catalog_slug: str):
    probes = []
    for raw in (catalog_slug, model_id.split("/")[-1], model_id):
        if not raw:
            continue
        probes.append(norm(raw))
        base = raw
        for lane in AA_LANES:
            base = base.replace(f"-{lane}", "")
        probes.append(norm(base))
    for probe in probes:
        if probe in ratings:
            rec = ratings[probe]
            return rec.get("intelligence"), rec.get("is_reasoning")
    # AA names a build, not a lane: "deepseek-v4.1-flash-1017" is the model with
    # a build number glued on. A suffix of bare digits is that and nothing else;
    # "deepseekv41flash" must not reach "deepseekv41flashfast".
    for probe in probes:
        if not probe:
            continue
        for key, rec in ratings.items():
            rest = key[len(probe):] if key.startswith(probe) else ""
            if rest.isdigit():
                return rec.get("intelligence"), rec.get("is_reasoning")
    return None, None


def fails_static(capability, cost, g):
    f = []
    if capability is None or capability < g["capability_min"]:
        f.append(f"capability {capability or 0:.1f} < {g['capability_min']:.1f}")
    if cost is None or cost > g["cost_max"]:
        f.append(f"cost {cost or 0:.4f} > {g['cost_max']:.4f}")
    return f


def at_context(m, tokens=CONTEXT_K * 1000):
    """Time to first token once the prefix is `tokens` long."""
    if m["ttft"] is None or m["prefill"] is None:
        return None
    return m["ttft"] + m["prefill"] * tokens / 1_000_000


def turn_time(m):
    """First token plus the writing of a typical answer, at 60k."""
    ttft = at_context(m)
    if ttft is None or not m["speed"]:
        return None
    return ttft + ANSWER_TOKENS / m["speed"]


def fails_measured(m, capability, cost, g, include_static=True):
    f = fails_static(capability, cost, GATES["static"]) if include_static else []
    if m["speed"] is None or m["speed"] < g["speed_min"]:
        f.append(f"speed {m['speed'] or 0:.0f} < {g['speed_min']:.0f}")
    if m["ttft"] is None or m["ttft"] > g["latency_max"]:
        f.append(f"latency {m['ttft'] or 0:.2f} > {g['latency_max']:.2f}")
    if m["cache"] is None or m["cache"] < g["cache_min"]:
        f.append(f"cache {m['cache'] or 0:.0%}")
    # The 60k figures are printed, not enforced: a real agent greps and reads
    # fragments, so a long-prefix turn is the exception, not the rule. Fold 3 is
    # what decides now.
    ttft = at_context(m)
    if "latency_60k_max" in g and ttft is not None and ttft > g["latency_60k_max"]:
        f.append(f"ttft@60k {ttft:.2f} > {g['latency_60k_max']:.2f}")
    turn = turn_time(m)
    if "turn_60k_max" in g and turn is not None and turn > g["turn_60k_max"]:
        f.append(f"turn@60k {turn:.1f} > {g['turn_60k_max']:.1f}")
    return f


def fails_fitness(m, g):
    f = []
    checks = (
        ("prefill", "prefill_ms_per_1k_max", ">", "ms/1k", 1),
        ("cache_loop", "cache_hit_min", "<", "", 100),
        ("retention", "retention_4x_min", "<", "", 1),
        ("errors", "errors_per_10_max", ">", "/10", 1),
        ("tools", "tools_valid_min", "<", "", 100),
    )
    for key, gate, op, unit, scale in checks:
        value = m[key]
        if value is None:
            f.append(f"no {key} data")
            continue
        limit = g[gate]
        bad = value > limit if op == ">" else value < limit
        if bad:
            shown = value * scale if scale != 1 else value
            f.append(f"{key} {shown:.1f}{unit}")
    return f


def config_ids() -> set[str]:
    """Model ids in the patch file, in either block or flow style."""
    text = CONFIG.read_text(encoding="utf-8")
    block = text.split("models:", 1)[1]
    return set(re.findall(r"^\s+- (?:\{\s*)?id:\s*([^,\s}]+)", block, re.M))


def check() -> int:
    models, catalog = load_measured(), catalogue()
    problems = []

    # A measured row with no price is invisible to the gates: it fails static for
    # a cost of nothing and never says so, because it is not admitted either.
    for m in models.values():
        if m["cost_override"] is None and not m["catalog"]:
            problems.append(f"{m['id']} is measured but has no price: add a "
                            f"cost_override, or the catalog_slug it is sold under")

    print("phase 1 - static (free):  " + "  ".join(f"{k}={v}" for k, v in GATES["static"].items()))
    overrides = {m["catalog"]: m["override"] for m in models.values() if m["override"] is not None}
    survivors = []
    for slug, row in catalog.items():
        capability = row["capability"] if row["capability"] is not None else overrides.get(slug)
        if not fails_static(capability, row["cost"], GATES["static"]):
            survivors.append(slug)
    print(f"  {len(catalog)} catalog rows -> {len(survivors)} worth measuring")

    print("phase 2 - measured:       " + "  ".join(f"{k}={v}" for k, v in GATES["measured"].items()))
    print("phase 3 - fitness:        " + "  ".join(f"{k}={v}" for k, v in GATES["fitness"].items()))

    RATINGS = scores()
    for m in models.values():
        row = catalog.get(m["catalog"], {})
        # AA first: it is the only comparable scale. The measured override is the
        # bridge for a row AA has not scored.
        capability, _ = aa_of(RATINGS, m["id"], m["catalog"])
        if capability is None and m["override"] is not None:
            capability = m["override"]
        if capability is None and norm(m["id"].split("/")[-1]) in capability_overrides():
            capability = capability_overrides()[norm(m["id"].split("/")[-1])][0]
        if capability is None:
            capability = row.get("capability")
        # a model sold on another plan has its own price: the catalogue is Command Code's
        cost = m["cost_override"] if m["cost_override"] is not None else row.get("cost")
        f2 = fails_measured(m, capability, cost, GATES["measured"])
        f3 = fails_fitness(m, GATES["fitness"])
        admitted = m["id"] in ADMITTED
        verdict = "PASS" if not f2 and not f3 else "FAIL"
        if admitted:
            shown = (f"{m['speed']:.0f} t/s  {m['ttft']:.2f} s  "
                     f"{m['prefill']:.1f} ms/1k  {turn_time(m):.1f} s  ${cost:.4f}") if all(
                         m[k] is not None for k in ("speed", "ttft", "prefill")) else ""
            print(f"  {verdict:4s} {m['name'][:30]:30s} {shown:46s} {', '.join(f2 + f3)}")
            if f2 or f3:
                problems.append(f"{m['name']} is admitted but misses: {', '.join(f2 + f3)}")
        elif not f2 and not f3:
            print(f"  ENTER {m['name'][:32]:32s} clears every gate but is not admitted")
            problems.append(f"{m['name']} clears every gate but is not admitted")

    for admitted_id in ADMITTED:
        if admitted_id not in models:
            problems.append(f"{admitted_id} is admitted but has no row in models.csv")

    configured = config_ids()
    for missing in ADMITTED - configured:
        problems.append(f"{missing} is in the policy but not in dsh/cordis.patch.yml")
    # Only rows this repo has measured are governed here. An id the benchmark
    # has never measured is the owner's arrangement, not this file's business.
    for extra in configured - ADMITTED:
        if extra in models:
            problems.append(f"{extra} is configured but not admitted")
    if not problems:
        print(f"\nOK: {len(ADMITTED)} rows clear all three phases, and the menu matches the policy")
    else:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
    return 1 if problems else 0


def api_key() -> str:
    if not CREDS.exists():
        raise SystemExit(f"no {CREDS}. A live run needs {KEY_ENV} there; every free "
                         f"subcommand works without it.")
    m = re.search(KEY_ENV + r':\s*"([^"]+)"', CREDS.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"no {KEY_ENV} in {CREDS}")
    return m.group(1)


def call(model: str, prompt: str, max_tokens: int, tools: list | None = None,
         cache: bool = False) -> dict:
    anthropic = model.startswith("claude-")
    if anthropic:
        content = [{"type": "text", "text": prompt}]
        if cache:
            content[0]["cache_control"] = {"type": "ephemeral"}
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content if cache else prompt}]}
        if tools:
            body["tools"] = [{"name": t["name"], "description": t["description"],
                              "input_schema": {"type": "object",
                                               "properties": {t["param"]: {"type": "string"}},
                                               "required": [t["param"]]}} for t in tools]
        url, headers = f"{BASE}/messages", {"x-api-key": KEY, "anthropic-version": "2023-06-01"}
    else:
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        if tools:
            body["tools"] = [{"type": "function",
                              "function": {"name": t["name"], "description": t["description"],
                                           "parameters": {"type": "object",
                                                          "properties": {t["param"]: {"type": "string"}},
                                                          "required": [t["param"]]}}} for t in tools]
            body["tool_choice"] = "auto"
        url, headers = f"{BASE}/chat/completions", {"Authorization": f"Bearer {KEY}"}
    headers.update({"Content-Type": "application/json", "User-Agent": "curl/8.5.0"})
    req = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


def usage_tokens(data: dict) -> tuple[int, int]:
    u = data.get("usage", {})
    out = u.get("completion_tokens") or u.get("output_tokens") or 0
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
    if cached is None:
        cached = u.get("cache_read_input_tokens", 0)
    return out, cached


def measure_route(model: str) -> dict:
    print(f"\n=== {model} ===")
    prefix = "".join(CORPUS.format(i=i) for i in range(900))  # ~36k tokens

    speeds = []
    for _ in range(3):
        start = time.perf_counter()
        data = call(model, ESSAY, 1600)
        speeds.append(usage_tokens(data)[0] / (time.perf_counter() - start))
    for _ in range(2):  # prime the cache
        call(model, prefix + "\n\nReply with OK.", 16, cache=True)
    ttfts, hits = [], 0
    for _ in range(3):
        start = time.perf_counter()
        data = call(model, prefix + "\n\nReply with OK.", 16, cache=True)
        ttfts.append(time.perf_counter() - start)
        hits += 1 if usage_tokens(data)[1] else 0

    points = []
    for lines in (120, 480, 1400):
        start = time.perf_counter()
        call(model, "".join(CORPUS.format(i=i + 9000) for i in range(lines)) + f"\nnonce {time.time_ns()}", 16)
        points.append(time.perf_counter() - start)
    # A negative slope means the 60k call came back faster than the 5k one:
    # queue noise, not a negative cost. Clamp it, or the gate reads nonsense.
    slope = max(0.0, (points[2] - points[0]) / ((1400 - 120) * 40) * 1_000_000)

    fixed = "".join(CORPUS.format(i=i + 20000) for i in range(480))
    loop_hits = 0
    for turn in range(5):
        data = call(model, fixed + "\n\nReply with OK.", 16, cache=True)
        loop_hits += 1 if turn >= 2 and usage_tokens(data)[1] else 0
    loop_rate = loop_hits / 3

    solo_start = time.perf_counter()
    data = call(model, "".join(CORPUS.format(i=i + 30000) for i in range(120)) + "\n\nWrite 200 words.", 200)
    solo = usage_tokens(data)[0] / (time.perf_counter() - solo_start)

    total = []

    def one():
        d = call(model, "".join(CORPUS.format(i=i + 40000) for i in range(120)) + "\n\nWrite 200 words.", 200)
        total.append(usage_tokens(d)[0])
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: one(), range(4)))
    aggregate = sum(total) / (time.perf_counter() - start)

    errors = 0
    for _ in range(10):
        try:
            call(model, "Reply with OK.", 16)
        except Exception:  # noqa: BLE001
            errors += 1

    good = 0
    for _ in range(2):
        try:
            data = call(model, TOOL_PROMPT, 512, tools=TOOLS)
            if model.startswith("claude-"):
                calls = [(b.get("name"), b.get("input")) for b in data.get("content", [])
                         if b.get("type") == "tool_use"]
            else:
                calls = []
                for c in data["choices"][0]["message"].get("tool_calls") or []:
                    fn = c.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = None
                    calls.append((fn.get("name"), args))
            ok = (len(calls) >= 2 and {n for n, _ in calls} == {"get_weather", "get_time"}
                  and all(isinstance(a, dict) for _, a in calls))
            good += 1 if ok else 0
        except Exception:  # noqa: BLE001
            pass

    return {
        "speed": round(statistics.median(speeds)),
        "ttft": round(statistics.median(ttfts), 2),
        "cache": hits / 3,
        "prefill": round(slope, 1),
        "cache_loop": loop_rate,
        "retention": round(aggregate / (solo * 4), 2),
        "errors": errors,
        "tools": good / 2,
    }


def live(model: str, capability: float, cost: float) -> int:
    global KEY
    # Phase 1 first, and it is free: a row that fails it costs nothing to reject,
    # so it must not need a credential to be rejected.
    static_fail = fails_static(capability, cost, GATES["static"])
    if static_fail:
        print(f"{model}: fails phase 1 - {', '.join(static_fail)}. Nothing measured.")
        return 1

    KEY = api_key()
    print(f"{model}: phase 1 clear (capability {capability:.1f}, ${cost:.4f}/turn)")
    values = measure_route(model)
    row = {"id": model, "name": model, "override": capability, **values, "catalog": ""}

    f2 = fails_measured({**row, "cache": values["cache"]}, capability, cost, GATES["measured"])
    f3 = fails_fitness(row, GATES["fitness"])
    print(f"\n  speed {values['speed']} tok/s   ttft {values['ttft']} s   cache {values['cache']:.0%}")
    print(f"  prefill {values['prefill']} ms/1k   loop cache {values['cache_loop']:.0%}   "
          f"retention {values['retention']}   errors {values['errors']}/10   tools {values['tools']:.0%}")
    if f2 or f3:
        print(f"\n  NOT FIT: {', '.join(f2 + f3)}")
        return 1
    print("\n  FIT")
    print(f"\n  {model},,,{values['speed']},{values['ttft']},{values['cache']:.3f},"
          f"{values['prefill']},{values['cache_loop']:.2f},{values['retention']},"
          f"{values['errors']},{values['tools']:.2f},{capability}")
    return 0


def cmd_measure(args) -> int:
    global GATES, ADMITTED, BASE, KEY_ENV
    GATES, ADMITTED = load_policy()
    BASE, KEY_ENV = GATEWAYS[args.provider]
    if not args.model:
        return check()
    if args.capability is None or args.cost is None:
        raise SystemExit("--model needs --capability and --cost (the static phase)")
    return live(args.model, args.capability, args.cost)


# --------------------------------------------------------------------------- fold 3

MODULE = '''"""Small pricing helpers. Three behaviours are expected; one is broken."""


def add_tax(amount, rate):
    """Return amount plus tax at `rate` percent (rate=21 means 21%)."""
    return amount + rate


def format_price(value):
    """Two decimals, with the euro sign and a dot as the decimal separator."""
    return f"{value:.2f} EUR"


def split_bill(total, people):
    """The share each person pays, rounded to cents."""
    return round(total / people, 2)
'''

TESTS = '''def test_add_tax_adds_a_percentage():
    from pricing import add_tax
    assert add_tax(100, 21) == 121
    assert add_tax(50, 10) == 55


def test_format_price_keeps_two_decimals():
    from pricing import format_price
    assert format_price(3.5) == "3.50 EUR"


def test_split_bill_rounds_to_cents():
    from pricing import split_bill
    assert split_bill(10, 3) == 3.33
'''

TASK = ("The repository in the current directory has a failing test suite. "
        "Make `python -m pytest -q` pass by fixing pricing.py. "
        "Do not change test_pricing.py. Run the tests to confirm before you finish.")

PATCH = """- id: agent-default-model
  config:
    provider: {provider}
    model: {model}
- id: session-log-deepseek
  disabled: true
- id: plugin-package-inventory-deepseek
  disabled: true
"""

WORK = Path.home() / "workspace" / "agentic-fold3"


def dsh_command(patch: Path, task: str) -> list[str]:
    """`dsh` is an npm shim on Windows: a .cmd needs cmd /c to start."""
    exe = shutil.which("dsh")
    if not exe:
        raise SystemExit("dsh is not on PATH")
    args = [exe, "--profile", "headless", "--patch", str(patch), task]
    return ["cmd", "/c", *args] if exe.lower().endswith(".cmd") else args


def agentic_reset() -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    (WORK / "pricing.py").write_text(MODULE, encoding="utf-8")
    (WORK / "test_pricing.py").write_text(TESTS, encoding="utf-8")


def agentic_solved() -> bool:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=WORK,
                       capture_output=True, text=True)
    return r.returncode == 0


def cmd_agentic(args) -> int:
    patch = BENCH / "_agentic-patch.yml"
    patch.write_text(PATCH.format(provider=args.provider, model=args.model), encoding="utf-8")

    print(f"{args.provider}/{args.model}: {args.rounds} rounds")
    wins, times = 0, []
    try:
        for n in range(1, args.rounds + 1):
            agentic_reset()
            start = time.perf_counter()
            run = subprocess.run(dsh_command(patch, TASK), cwd=WORK, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace")
            elapsed = time.perf_counter() - start
            ok = agentic_solved()
            wins += 1 if ok else 0
            times.append(elapsed)
            tail = (run.stdout or "").strip().splitlines()
            print(f"  round {n}: {'solved' if ok else 'FAILED'} in {elapsed:.1f} s"
                  f"   {tail[-1][:60] if tail else ''}")
    finally:
        patch.unlink(missing_ok=True)

    times.sort()
    median = times[len(times) // 2]
    verdict = "PASS" if wins == args.rounds else "FAIL"
    print(f"\n{verdict}: {wins}/{args.rounds} solved, median {median:.1f} s")
    return 0 if wins == args.rounds else 1


# --------------------------------------------------------------------------- the cost test

COLUMN = "crosscheck_turn_usd"
PRICED = ("list_turn_usd", "factor", "effective_turn_usd", "real_turn_usd", "leverage")


def priced_rows(table: dict) -> dict:
    """Fold 1 as the gates see it: no file written, no model called."""
    gates = load_policy()[0]["static"]
    catalog, judged, score_table = catalogue(), judged_models(), scores()
    out = {}
    for provider, plan in plans()["providers"].items():
        if plan.get("active") is False:      # fold 1 never prices a prepared plan
            continue
        for row in model_rows(plan, catalog, table, score_table):
            row["provider"] = provider
            bucket, why = classify(row, float(gates["cost_max"]),
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


def cmd_test(args) -> int:
    table = identities()
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

    moved = sum(1 for k, (row, _, _) in base.items() if row[COLUMN] != scaled[k][0][COLUMN])
    print(f"  {'ok  ' if moved else 'FAIL'} the mutation landed     {moved} cross-check figures moved")
    failures += 0 if moved else 1

    print("\nsignal dependence:")
    muted = copy.deepcopy(table)
    for rec in muted.values():
        rec["reasoning"] = False
    off = priced_rows(muted)
    changed = [k for k in base if base[k][1] != off[k][1]]
    good = changed and all(off[k][1] == "out" and "does not reason" in off[k][2] for k in changed)
    print(f"  {'ok  ' if good else 'FAIL'} reasoning off          {len(changed)} verdicts moved, as they should")
    failures += 0 if good else 1
    no_money = sum(1 for k in base if base[k][0]["real_turn_usd"] != off[k][0]["real_turn_usd"])
    print(f"  {'ok  ' if not no_money else 'FAIL'} and no price moved either  {no_money} priced columns changed")
    failures += 0 if not no_money else 1

    print("\nstructure:")
    users = sorted(name for name, fn in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
                   if name != "cmd_test" and COLUMN in inspect.getsource(fn))
    ok = users == ["model_rows"]
    print(f"  {'ok  ' if ok else 'FAIL'} only model_rows writes it  {', '.join(users) or 'nobody'}")
    failures += 0 if ok else 1
    decision = inspect.getsource(classify)
    ok = "crosscheck" not in decision and COLUMN not in decision
    print(f"  {'ok  ' if ok else 'FAIL'} classify never looks at it")
    failures += 0 if ok else 1

    print(f"\n{'OK: models.dev is identity, never price' if not failures else 'FAIL: ' + str(failures)}")
    return 0 if not failures else 1


# --------------------------------------------------------------------------- main

def main() -> int:
    p = argparse.ArgumentParser(prog="bench.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("refresh", help="re-read the providers and both catalogues")
    r.add_argument("--write", action="store_true", help="store what it parsed in data/")
    r.add_argument("--only", help="plans,models,capability,forcebench (default: all)")
    r.set_defaults(fn=cmd_refresh)

    pl = sub.add_parser("plan", help="what a subscription costs per token")
    pl.add_argument("--today", type=date.fromisoformat,
                   help="a date (YYYY-MM-DD), for the promos of that day")
    pl.add_argument("--model", default="deepseek-v4-1-flash")
    pl.add_argument("--write", action="store_true", help="save a snapshot")
    pl.set_defaults(fn=cmd_plan)

    s = sub.add_parser("select", help="fold 1: what is worth calling at all")
    s.add_argument("--write", action="store_true", help="save a snapshot")
    s.set_defaults(fn=cmd_select)

    m = sub.add_parser("measure", help="fold 2: the stored table against the gates")
    m.add_argument("--model")
    m.add_argument("--capability", type=float)
    m.add_argument("--cost", type=float)
    m.add_argument("--provider", default="command-code", choices=sorted(GATEWAYS))
    m.set_defaults(fn=cmd_measure)

    a = sub.add_parser("agentic", help="fold 3: a real task, judged by pytest")
    a.add_argument("--provider", required=True)
    a.add_argument("--model", required=True)
    a.add_argument("--rounds", type=int, default=3)
    a.set_defaults(fn=cmd_agentic)

    t = sub.add_parser("test", help="models.dev cannot move a price")
    t.set_defaults(fn=cmd_test)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
