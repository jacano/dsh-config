#!/usr/bin/env python3
"""bench — one script, what a subscription costs and what it can do.

    python bench/bench.py plan               # what a million tokens costs
    python bench/bench.py plan --model claude-haiku-5.5
    python bench/bench.py plan --today 2026-10-22
    python bench/bench.py chart              # the Pareto picture of the same table
    python bench/bench.py measure            # the stored table against the gates
    python bench/bench.py agentic --provider opendesign --model deepseek-v4.1-flash

Four questions, in the order they cost money:

  plan     what a million tokens of each kind costs, after the plan's multiplier,
           its ceiling and its windows. Free, calls no model.
  chart    price against Terminal-Bench, and the frontier through whatever nothing
           beats. Free, writes a png or a page.
  measure  speed, latency, cache, prefill, retention, errors, tool calls - and the
           menu has to agree with the policy.
  agentic  a real bug in a real repository, pytest decides.

data/plans.json    the plans, what they publish, and the catalogue they price from
data/tbench.json   the board: what each model does on Terminal-Bench, and through
                   which agent
models.csv         what each route measured on the wire, one line per route
models-policy.yml  the gates, and which ids are admitted

Nothing here edits the DSH configuration; that is a separate change in ../dsh/.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BENCH = Path(__file__).resolve().parent
REPO = BENCH.parent
DATA = BENCH / "data"
PLANS_FILE = DATA / "plans.json"
TBENCH_FILE = DATA / "tbench.json"
POLICY = BENCH / "models-policy.yml"
MEASURED = BENCH / "models.csv"
CONFIG = REPO / "dsh" / "cordis.patch.yml"
CREDS = Path.home() / ".dsh" / ".credentials.yaml"

DAYS = 30.0            # a month, for the windows
LANES = ("fast", "eco", "ultrafast", "preview", "latest", "sync", "max", "high", "xhigh")
GATEWAYS = {
    "command-code": ("https://api.commandcode.ai/provider/v1", "COMMANDCODE_API_KEY"),
    "opendesign": ("https://amr-link.open-design.ai/v1", "OPENDESIGN_API_KEY"),
    "opengateway": ("https://apis.opengateway.ai/v1", "OPENGATEWAY_API_KEY"),
}

sys.stdout.reconfigure(encoding="utf-8")


# --------------------------------------------------------------------------- core

def norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def probes_for(model_id: str, catalog_slug: str, lanes=LANES) -> list[str]:
    """The keys a model may be filed under: its bare name, its lane, its build."""
    probes = []
    for raw in (catalog_slug, model_id.split("/")[-1], model_id):
        if not raw:
            continue
        probes.append(norm(raw))
        base = raw
        for lane in lanes:
            base = base.replace(f"-{lane}", "")
        probes.append(norm(base))
    return probes


def by_build(table: dict, probes: list[str]) -> dict | None:
    """A source may name a build, not a lane: "x-1017" is the model with a number
    glued on. Bare digits only, or "flash" would reach "flash-fast" - and at least
    two of them, because a build is a date (1017, 0902) while "glm-5" followed by a
    single 3 is the next version, a different model with a different score."""
    for probe in probes:
        if not probe:
            continue
        for key, rec in table.items():
            rest = key[len(probe):] if key.startswith(probe) else ""
            if rest.isdigit() and len(rest) >= 2:
                return rec
    return None


def board_score(board: dict, model_id: str) -> float | None:
    """What the board gives this model, or nothing at all if it does not rank it."""
    hit = by_label(board, model_id, "")
    return None if hit is None else hit["score"]


def by_label(table: dict, model_id: str, catalog_slug: str) -> dict | None:
    """Some boards write "Haiku 5.5" where we write "claude-haiku-5-5": the label
    may drop the maker, or carry the build. Exact first, then the shorter name
    inside the longer one, then bare digits."""
    probes = probes_for(model_id, catalog_slug)
    for probe in probes:
        if probe in table:
            return table[probe]
    for probe in probes:
        if not probe:
            continue
        for key, rec in table.items():
            if key.endswith(probe) or probe.endswith(key):
                return rec
    return by_build(table, probes)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def plans() -> dict:
    return read_json(PLANS_FILE)


def tbench() -> dict:
    """The board: model + agent, one row per model, the best run it got."""
    return read_json(TBENCH_FILE)["models"]


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
        m = re.match(r"^  - id:\s*(\S+)", line)
        if m and section == "admitted":
            admitted.add(m.group(1))
    # A gate that fails to parse is worse than no gate: the helper that reads it
    # crashes on the key and the crash says nothing about the file. Say it here.
    for phase in ("static", "measured", "fitness"):
        if not gates.get(phase):
            raise SystemExit(f"{POLICY.name}: no '{phase}' gates. The file is indented "
                             f"with two spaces per level; the parser expects that.")
    return gates, admitted


# Read once at import: the gate helpers below use them, and so does anything that
# imports this file rather than running it.
GATES, ADMITTED = load_policy()
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


def allowance(plan: dict, name: str) -> float | None:
    """A plan may cap a single model below its total: "an allowance"."""
    best = None
    target = norm(name)
    for model, usd in (plan.get("allowances_usd") or {}).items():
        if norm(model) and norm(model) in target and (best is None or len(model) > len(best[0])):
            best = (model, float(usd))
    return best[1] if best else None


def plan_caps(plan: dict, monthly: float | None, name: str = "") -> tuple[float | None, str]:
    """The usage the plan can actually be spent at, and what stops it first."""
    limit: dict[str, float] = {}
    if monthly:
        limit["credits"] = monthly
    per_model = allowance(plan, name)
    if per_model:
        limit["allowance"] = per_model
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


def plan_rows(store: dict, day: date, want: str | None = None) -> list[dict]:
    """What a million of each kind of token costs on each plan that sells it.

    No mix, no turn, no assumed shape: the multiplier, the ceiling and the hour are
    already in the number, and the rest is the caller's business.
    """
    cat = store["catalog"]
    target = norm(want) if want else None
    out: list[dict] = []

    for provider, plan in store["providers"].items():
        entries = ([{"id": slug, "catalog": slug} for slug in cat]
                   if plan["models"] == "catalog" else plan["models"])
        for m in entries:
            if target:
                bare = norm(re.sub(r"\([^)]*\)", "", m["id"]))
                if target not in (norm(m["id"]), norm(m["id"].split("/")[-1]), bare):
                    continue
            row = cat.get(m.get("catalog") or "") or plan_lookup(cat, m["id"])
            rates = m if "input" in m else row
            if "input" not in rates:
                continue
            monthly = m.get("monthly_limit_usd")
            monthly = monthly if isinstance(monthly, (int, float)) else plan.get("credits_usd")
            usable, bound = plan_caps(plan, monthly, row.get("name") or m["id"])
            fee = plan.get("fee_usd")
            scale = (float(fee) / usable) if usable and fee else 1.0
            offer = live_promo(plan, m["id"], day)
            hourly = 1.0 if "input" in m else blend_of(row)
            factor = float(m.get("billed_factor") or m.get("factor", 1.0))
            factor *= (offer or 1.0) * hourly * scale
            out.append({"provider": provider, "model": m["id"], "caps at": bound,
                        "list": {k: float(rates[k]) for k in
                                 ("input", "cache", "output", "cache_write")
                                 if rates.get(k) is not None},
                        **{k: float(rates[k]) * factor for k in ("input", "cache", "output")
                           if rates.get(k) is not None},
                        **({"cache_write": float(rates["cache_write"]) * factor}
                           if rates.get("cache_write") is not None else {})})
    return out


def cmd_plan(args) -> int:
    """The price of a million tokens of each kind, after every multiplier."""
    store, boards = plans(), tbench()
    day = args.today or date.today()
    rows = plan_rows(store, day, args.model)
    if args.model:
        rows = [r for r in rows if r["model"] == args.model or
                norm(r["model"].split("/")[-1]) == norm(args.model)]
        if not rows:
            print(f"no plan serves {args.model}; try an id from data/plans.json")
            return 1
    else:
        floor = GATES["static"]["tbench_min"]
        rows = [r for r in rows if (board_score(boards, r["model"]) or 0) >= floor]

    print(f"dollars per million tokens, on {day.isoformat()}")
    print("  the multiplier, the ceiling and the hour are already in these numbers\n")
    print(f"  {'model':34s} {'tb':>4s} {'plan':14s} {'input':>10s} {'cache read':>11s} "
          f"{'cache write':>12s} {'output':>10s}")
    for r in sorted(rows, key=lambda x: (x["input"], x["provider"])):
        tb = board_score(boards, r["model"])
        write = f"{r['cache_write']:>12.5f}" if "cache_write" in r else f"{'-':>12s}"
        print(f"  {r['model'][:34]:34s} {('%.1f' % tb) if tb else '-':>4s} {r['provider']:14s} "
              f"{r['input']:>10.5f} {r['cache']:>11.5f} {write} {r['output']:>10.5f}")
    return 0


# --------------------------------------------------------------------------- chart

CHART_COLOURS = {"open-design": (96, 165, 250), "opengateway": (167, 139, 250),
                 "command-code": (251, 146, 60)}


def chart_rows(store: dict, boards: dict, day: date, mix=None) -> list[dict]:
    """Every priced model of every plan, with its board score and one cost."""
    out = []
    measured = load_measured()
    for r in plan_rows(store, day):
        tb = board_score(boards, r["model"])
        if tb is None:
            continue
        if mix:
            fresh, cache, written = mix
            cost = (fresh * r["input"] + cache * r["cache"] + written * r["output"]) / 1e6
        else:
            cost = r["input"]
        m = measured.get(r["model"])
        if r["model"] in ADMITTED:
            state = "admitted"
        elif m is None:
            state = "unmeasured"
        elif fails_measured(m, tb, GATES["measured"]) + fails_fitness(m, GATES["fitness"]):
            state = "measured, fails"
        else:
            state = "measured, passes"
        out.append({**r, "tb": tb, "cost": cost, "state": state})
    return out


def pareto(rows: list[dict]) -> list[dict]:
    """Nothing beats these on both axes: cheaper and at least as capable."""
    def beats(a, b):
        return (a["tb"] >= b["tb"] and a["cost"] <= b["cost"]
                and (a["tb"] > b["tb"] or a["cost"] < b["cost"]))
    # A model under the floor is not a candidate, so it cannot be on the frontier:
    # a line that recommends what the chart rules out is a line nobody trusts.
    eligible = [r for r in rows if r["tb"] >= GATES["static"]["tbench_min"]]
    return sorted((r for r in eligible
                   if not any(beats(o, r) for o in eligible if o is not r)),
                  key=lambda r: r["cost"])


PAGE_FILE = BENCH / "page.html"



def write_page(rows: list[dict], store: dict, floor: float, subject: str,
               path: Path) -> None:
    """Fill the template and write it: the page the site serves."""
    payload = []
    for r in rows:
        plan = store["providers"][r["provider"]]
        payload.append({
            "model": r["model"], "provider": r["provider"],
            "plan": plan["plan"], "fee": plan.get("fee_usd"),
            "tb": round(r["tb"], 2), "state": r.get("state", "unmeasured"),
            "cost": round(r["input"], 6),
            "eff": {k: round(v, 6) for k, v in r.items()
                    if k in ("input", "cache", "cache_write", "output")},
        })
    template = PAGE_FILE.read_text(encoding="utf-8")
    html = (template.replace("__DATA__", json.dumps(payload))
                .replace("__COLOURS__", json.dumps({k: "#%02x%02x%02x" % v
                                                    for k, v in CHART_COLOURS.items()}))
                .replace("__FLOOR__", f"{floor:.1f}")
                .replace("__PLANS__", json.dumps(
                    {name: {"plan": p["plan"], "fee": p.get("fee_usd")}
                     for name, p in store["providers"].items()}))
                .replace("__SUBJECT__", json.dumps(subject))
                .replace("__GENERATED__", date.today().isoformat()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    print(f"written: {path}  ({len(rows)} models)")



def draw_png(rows: list[dict], front: list[dict], store: dict, floor: float,
             subject: str, path: Path) -> None:
    """The same table as a picture, with Pillow and no other dependency."""
    import math

    from PIL import Image, ImageDraw, ImageFont

    W, H, M = 1600, 1060, 178
    bg, ink, dim = (13, 17, 23), (230, 237, 243), (110, 118, 129)
    img = Image.new("RGB", (W, H), bg)
    dr = ImageDraw.Draw(img)

    def font(size, bold=False):
        # Windows first, then the usual Linux paths: the png is also drawn on a
        # machine that is not this one, and a bitmap fallback is not a chart.
        names = (("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf") if bold
                 else ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"))
        for folder in ("C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/",
                       "/usr/share/fonts/truetype/liberation/"):
            for name in names:
                try:
                    return ImageFont.truetype(folder + name, size)
                except OSError:
                    continue
        return ImageFont.load_default()

    f_title, f_lab, f_tick, f_dot = font(30, True), font(17), font(15), font(14)

    costs = [r["cost"] for r in rows]
    lo, hi = min(costs), max(costs)
    x0, x1 = math.log10(lo * 0.7), math.log10(hi * 1.4)
    tbs = [r["tb"] for r in rows]
    y0, y1 = min(tbs) - 6, max(tbs) + 6

    px = lambda c: M + (math.log10(c) - x0) / (x1 - x0) * (W - 2 * M)
    py = lambda t: H - M - (t - y0) / (y1 - y0) * (H - 2 * M)

    dr.text((M, 44), "Terminal-Bench against price, every model every plan sells",
            font=f_title, fill=ink)
    dr.text((M, 84), subject, font=f_lab, fill=dim)
    dr.text((M, 112), "our cost: the plan's list rate x its multiplier, divided by the ceiling "
                      "that plan puts on the model", font=f_tick, fill=dim)

    for tb in range(int(y0) // 10 * 10, int(y1) + 1, 10):
        if tb < y0:
            continue
        y = py(tb)
        dr.line([(M, y), (W - M, y)], fill=(30, 36, 44))
        dr.text((M - 18, y), f"{tb:.0f}", font=f_tick, fill=dim, anchor="rm")

    decade = 10 ** math.floor(x0)
    while decade < 10 ** x1:
        for mult in (1, 2, 5):
            c = decade * mult
            if lo * 0.7 <= c <= hi * 1.4:
                x = px(c)
                dr.line([(x, M), (x, H - M)], fill=(30, 36, 44))
                shown = f"${c:g}" if c >= 0.001 else f"${c:.5f}"
                dr.text((x, H - M + 14), shown, font=f_tick, fill=dim, anchor="mt")
        decade *= 10

    y_floor = py(floor)
    for x in range(M, W - M, 16):
        dr.line([(x, y_floor), (min(x + 9, W - M), y_floor)], fill=(248, 113, 113), width=2)
    dr.text((W - M - 8, y_floor - 10), f"Terminal-Bench floor {floor:.1f}", font=f_tick,
            fill=(248, 113, 113), anchor="rb")

    if len(front) > 1:
        pts = [(px(r["cost"]), py(r["tb"])) for r in front]
        for width, shade in ((13, (18, 44, 32)), (7, (30, 74, 51)), (3, (74, 222, 128))):
            dr.line(pts, fill=shade, width=width, joint="curve")

    for r in rows:
        x, y = px(r["cost"]), py(r["tb"])
        colour = CHART_COLOURS.get(r["provider"], (200, 200, 200))
        on = any(r is f for f in front)
        d = 9 if on else 6
        dr.ellipse([x - d, y - d, x + d, y + d], fill=colour,
                   outline=(255, 255, 255) if on else None, width=2 if on else 0)

    placed: list[tuple[float, float, float, float]] = []
    for r in sorted(front, key=lambda r: r["tb"]):
        x, y = px(r["cost"]), py(r["tb"])
        text = f"{r['model'].split('/')[-1]}  {r['tb']:.1f}"
        box = dr.textbbox((0, 0), text, font=f_dot)
        w, h = box[2] - box[0], box[3] - box[1]
        bx = min(x + 16, W - M - w - 20)
        by = max(y - h - 18, M + 40)
        for _ in range(12):                     # baja hasta encontrar hueco
            clash = any(not (bx + w + 8 < l or bx - 8 > r2 or by + h + 6 < t or by - 6 > b)
                        for l, t, r2, b in placed)
            if not clash:
                break
            by += h + 14
        placed.append((bx - 8, by - 6, bx + w + 8, by + h + 6))
        dr.rounded_rectangle([bx - 8, by - 6, bx + w + 8, by + h + 6], radius=6,
                             fill=(22, 27, 34), outline=(74, 222, 128))
        dr.text((bx, by), text, font=f_dot, fill=ink)

    # The legend is the subscriptions: which colour is which, and what it costs a month.
    entries = []
    for name, plan in store["providers"].items():
        fee = plan.get("fee_usd")
        label = f"{name}  {plan['plan']}  ${fee:.0f}/mo" if fee else f"{name}  pay as you go"
        entries.append((label, CHART_COLOURS.get(name, (200, 200, 200))))
    lx = M
    for text, colour in entries:
        dr.ellipse([lx, 145, lx + 13, 158], fill=colour)
        dr.text((lx + 20, 151), text, font=f_tick, fill=dim, anchor="lm")
        lx += dr.textbbox((0, 0), text, font=f_tick)[2] + 60


    dr.line([(M, H - 78), (W - M, H - 78)], fill=(30, 38, 50))
    dr.text((M, H - 62), "Every model every plan in data/plans.json that Terminal-Bench "
            "ranks. The chart and its controls are borrowed from linearbench.", font=f_tick,
            fill=(110, 118, 129))
    dr.text((W - M, H - 62), f"dsh-config · {date.today().isoformat()}", font=f_tick,
            fill=(110, 118, 129), anchor="ra")

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    print(f"written: {path}  ({len(rows)} models, {len(front)} on the frontier)")


def cmd_chart(args) -> int:
    """Draw the two axes that decide it: what a token costs, and what the board says."""
    store, boards = plans(), tbench()
    mix = None
    if args.mix:
        parts = args.mix.replace(" ", "").split(",")
        try:
            mix = tuple(int(x) for x in parts)
        except ValueError:
            raise SystemExit("--mix wants fresh,cache,out as three integers")
        if len(mix) != 3 or min(mix) < 0:
            raise SystemExit("--mix wants three token counts, fresh,cache,out")
    rows = chart_rows(store, boards, args.today or date.today(), mix)
    if not rows:
        print("nothing to draw")
        return 1
    front = pareto(rows)
    floor = GATES["static"]["tbench_min"]

    subject = ("dollars per million input tokens" if not mix else
               f"dollars per request of {mix[0]:,} fresh + {mix[1]:,} cache + {mix[2]:,} out")

    if args.html:
        write_page(rows, store, floor, subject, Path(args.html))
        return 0
    draw_png(rows, front, store, floor, subject, Path(args.out))
    return 0


# --------------------------------------------------------------------------- measure

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


def corpus(start: int, lines: int) -> str:
    """The reference text, from line `start`, `lines` lines long."""
    return "".join(CORPUS.format(i=i) for i in range(start, start + lines))

CONTEXT_K = 60
ANSWER_TOKENS = 1500

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
            "id": r["slug"], "name": r["name"],
            "speed": num("speed_tps"), "ttft": num("ttft_s"), "cache": num("cache_hit"),
            "prefill": num("prefill_ms_per_1k"), "cache_loop": num("cache_loop_hit"),
            "retention": num("retention_4x"), "errors": num("errors_10"),
            "tools": num("tools_valid"),
        }
    return out


def fails_static(tb, g):
    f = []
    if tb is None:
        f.append("not on Terminal-Bench")
    elif tb < g["tbench_min"]:
        f.append(f"tbench {tb:.1f} < {g['tbench_min']:.1f}")
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


def fails_measured(m, tb, g):
    f = fails_static(tb, GATES["static"])
    if m["speed"] is None or m["speed"] < g["speed_min"]:
        f.append(f"speed {m['speed'] or 0:.0f} < {g['speed_min']:.0f}")
    if m["ttft"] is None or m["ttft"] > g["latency_max"]:
        f.append(f"latency {m['ttft'] or 0:.2f} > {g['latency_max']:.2f}")
    if m["cache"] is None or m["cache"] < g["cache_min"]:
        f.append(f"cache {m['cache'] or 0:.0%}")
    # The 60k figures are printed, not enforced: a real agent greps and reads
    # fragments, so a long-prefix turn is the exception, not the rule. The agentic run is
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


def config_routes() -> dict[str, list[str]]:
    """Model id -> the provider blocks that serve it.

    The id is the route only while it is unique: the same id in two blocks would
    make `admitted:` mean two different things, so this counts them.
    """
    routes: dict[str, list[str]] = {}
    provider = ""
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        block = re.match(r"^      ([a-z][a-z0-9-]*):$", line)
        if block:
            provider = block.group(1)
            continue
        model = re.match(r"^\s+- (?:\{\s*)?id:\s*([^,\s}]+)", line)
        if model and provider:
            routes.setdefault(model.group(1), []).append(provider)
    return routes


def measured_gates(models: dict) -> list[str]:
    """Measured and fitness, row by row, against the admitted set."""
    print("measured:  " + "  ".join(f"{k}={v}" for k, v in GATES["measured"].items()))
    print("fitness:   " + "  ".join(f"{k}={v}" for k, v in GATES["fitness"].items()))
    problems = []
    board = tbench()
    for m in models.values():
        tb = board_score(board, m["id"])
        f2 = fails_measured(m, tb, GATES["measured"])
        f3 = fails_fitness(m, GATES["fitness"])
        admitted = m["id"] in ADMITTED
        verdict = "PASS" if not f2 and not f3 else "FAIL"
        if admitted:
            shown = ""
            if all(m[k] is not None for k in ("speed", "ttft", "prefill")):
                shown = (f"{m['speed']:.0f} t/s  {m['ttft']:.2f} s  "
                         f"{m['prefill']:.1f} ms/1k  {turn_time(m):.1f} s  tb {tb or 0:.1f}")
            print(f"  {verdict:4s} {m['name'][:30]:30s} {shown:44s} {', '.join(f2 + f3)}")
            if f2 or f3:
                problems.append(f"{m['name']} is admitted but misses: {', '.join(f2 + f3)}")
        elif not f2 and not f3:
            print(f"  ENTER {m['name'][:32]:32s} clears every gate but is not admitted")
            problems.append(f"{m['name']} clears every gate but is not admitted")
    return problems

def menu(models: dict) -> list[str]:
    """The policy, the measured table and the DSH config must name the same rows."""
    problems = [f"{i} is admitted but has no row in models.csv"
                for i in ADMITTED if i not in models]
    routes = config_routes()
    configured = set(routes)
    problems += [f"{i} is served by {', '.join(p)}: an id has to name one route"
                 for i, p in routes.items() if len(p) > 1]
    problems += [f"{i} is in the policy but not in dsh/cordis.patch.yml"
                 for i in set(ADMITTED) - configured]
    # Only rows this repo has measured are governed here. An id the benchmark has
    # never measured is the owner's arrangement, not this file's business.
    problems += [f"{i} is configured but not admitted"
                 for i in configured - set(ADMITTED) if i in models]
    return problems


def check() -> int:
    models = load_measured()
    problems = measured_gates(models)
    problems += menu(models)
    if not problems:
        print(f"\nOK: {len(ADMITTED)} rows clear every gate, and the menu matches the policy")
        return 0
    print("\nFAIL:")
    for problem in problems:
        print(f"  - {problem}")
    return 1


def api_key() -> str:
    from_env = os.environ.get(KEY_ENV)
    if from_env:
        return from_env
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
    headers.update({"Content-Type": "application/json",
                   "User-Agent": "curl/8.5.0"})
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
    prefix = corpus(0, 900)  # ~36k tokens

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
        call(model, corpus(9000, lines) + f"\nnonce {time.time_ns()}", 16)
        points.append(time.perf_counter() - start)
    # A negative slope means the 60k call came back faster than the 5k one:
    # queue noise, not a negative cost. Clamp it, or the gate reads nonsense.
    slope = max(0.0, (points[2] - points[0]) / ((1400 - 120) * 40) * 1_000_000)

    fixed = corpus(20000, 480)
    loop_hits = 0
    for turn in range(5):
        data = call(model, fixed + "\n\nReply with OK.", 16, cache=True)
        loop_hits += 1 if turn >= 2 and usage_tokens(data)[1] else 0
    loop_rate = loop_hits / 3

    # Retention is the noisiest number here: four parallel calls against one solo
    # call, and a single round moved 0,74 to 0,99 within ten minutes. Three rounds,
    # median, or the gate is reading the scheduler rather than the route.
    retention = []
    for _ in range(3):
        solo_start = time.perf_counter()
        data = call(model, corpus(30000, 120) + "\n\nWrite 200 words.", 200)
        solo = usage_tokens(data)[0] / (time.perf_counter() - solo_start)

        total = []

        def one():
            d = call(model, corpus(40000, 120) + "\n\nWrite 200 words.", 200)
            total.append(usage_tokens(d)[0])
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: one(), range(4)))
        aggregate = sum(total) / (time.perf_counter() - start)
        retention.append(aggregate / (solo * 4))

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
        "retention": round(statistics.median(retention), 2),
        "errors": errors,
        "tools": good / 2,
    }


def live(model: str, tbench_score: float) -> int:
    global KEY
    # Phase 1 first, and it is free: a row that fails it costs nothing to reject,
    # so it must not need a credential to be rejected.
    static_fail = fails_static(tbench_score, GATES["static"])
    if static_fail:
        print(f"{model}: the board does not clear it - {', '.join(static_fail)}. Nothing measured.")
        return 1

    KEY = api_key()
    print(f"{model}: clears the floor (tbench {tbench_score:.1f})")
    try:
        values = measure_route(model)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace").strip()[:200]
        raise SystemExit(f"{model}: the route refused the call ({exc.code}). {body}")
    row = {"id": model, "name": model, **values, "catalog": ""}

    f2 = fails_measured({**row, "cache": values["cache"]}, tbench_score, GATES["measured"])
    f3 = fails_fitness(row, GATES["fitness"])
    print(f"\n  speed {values['speed']} tok/s   ttft {values['ttft']} s   cache {values['cache']:.0%}")
    print(f"  prefill {values['prefill']} ms/1k   loop cache {values['cache_loop']:.0%}   "
          f"retention {values['retention']}   errors {values['errors']}/10   tools {values['tools']:.0%}")
    if f2 or f3:
        print(f"\n  NOT FIT: {', '.join(f2 + f3)}")
        return 1
    print("\n  FIT")
    print(f"\n  {model},,{model},{values['speed']},{values['ttft']},{values['cache']:.3f},"
          f"{values['prefill']},{values['cache_loop']:.2f},{values['retention']},"
          f"{values['errors']},{values['tools']:.2f}")
    return 0


def cmd_measure(args) -> int:
    global GATES, ADMITTED, BASE, KEY_ENV
    GATES, ADMITTED = load_policy()
    BASE, KEY_ENV = GATEWAYS[args.provider]
    if not args.model:
        return check()
    if args.tbench is None:
        raise SystemExit("--model needs --tbench: it is the floor this model has to clear")
    return live(args.model, args.tbench)


# --------------------------------------------------------------------------- agentic

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

WORK = Path.home() / "workspace" / "agentic-run"


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
    # Out of the repo and out of WORK: agentic_reset wipes WORK every round, and a
    # stray file in bench/ is one `git add` away from being committed.
    scratch = Path(tempfile.mkdtemp(prefix="bench-agentic-"))
    patch = scratch / "patch.yml"
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
        shutil.rmtree(scratch, ignore_errors=True)

    times.sort()
    median = times[len(times) // 2]
    verdict = "PASS" if wins == args.rounds else "FAIL"
    print(f"\n{verdict}: {wins}/{args.rounds} solved, median {median:.1f} s")
    return 0 if wins == args.rounds else 1


# --------------------------------------------------------------------------- main

def main() -> int:
    p = argparse.ArgumentParser(prog="bench.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("plan", help="what a million tokens costs")
    pl.add_argument("--today", type=date.fromisoformat,
                   help="a date (YYYY-MM-DD), for the promos of that day")
    pl.add_argument("--model", help="one model; without it, everything the board ranks")
    pl.set_defaults(fn=cmd_plan)

    ch = sub.add_parser("chart", help="the Pareto picture: price against the board")
    ch.add_argument("--out", default="bench/frontier.png", help="where to write the png")
    ch.add_argument("--html", help="write an interactive page instead of the png")
    ch.add_argument("--mix", help="fresh,cache,out - price a request of that shape")
    ch.add_argument("--today", type=date.fromisoformat,
                    help="a date (YYYY-MM-DD), for the promos of that day")
    ch.set_defaults(fn=cmd_chart)

    m = sub.add_parser("measure", help="the stored table against the gates, or one route")
    m.add_argument("--model", help="one route to measure live; without it, the stored table "
                                   "is checked against the gates")
    m.add_argument("--tbench", type=float, help="that model's board score, for the floor")
    m.add_argument("--provider", default="command-code", choices=sorted(GATEWAYS),
                   help="which plan serves it")
    m.set_defaults(fn=cmd_measure)

    a = sub.add_parser("agentic", help="a real task, judged by pytest")
    a.add_argument("--provider", required=True, help="which plan serves the model")
    a.add_argument("--model", required=True, help="the id to run the task through")
    a.add_argument("--rounds", type=int, default=3,
                   help="fresh workspace every round; all of them must pass")
    a.set_defaults(fn=cmd_agentic)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
