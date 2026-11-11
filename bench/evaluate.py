#!/usr/bin/env python3
"""One process for the whole model policy: statistics first, dynamics second.

    python bench/evaluate.py                 # check the stored table against the gates
    python bench/evaluate.py --static        # phase 1 only, over the catalog, free
    python bench/evaluate.py --model <id> --capability 42 --cost 0.0024
                                             # live run: static, then measured, then fitness

Phase 1 static    capability and price from the catalog. A row that fails here is
                  never called: no tokens spent.
Phase 2 measured  speed, warm latency, cache: the per-call numbers.
Phase 3 fitness   prefill slope, cache in a loop, parallel retention, errors and
                  tool-call validity: whether the route is good enough for an agent.

Every threshold is the envelope of the admitted rows, so a new model has to beat
the worst admitted one on every axis to get in.

Stdlib only. The `--check` mode never calls the API.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BENCH = Path(__file__).resolve().parent
REPO = BENCH.parent
POLICY = BENCH / "models-policy.yml"
CATALOG = BENCH / "catalog-2026-11-10.csv"
MODELS = BENCH / "models.csv"
CONFIG = REPO / "dsh" / "cordis.patch.yml"
CREDS = Path.home() / ".dsh" / ".credentials.yaml"
BASE = "https://api.commandcode.ai/provider/v1"

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


# --------------------------------------------------------------------------- policy

def load_policy():
    gates: dict[str, dict[str, float]] = {}
    admitted: set[str] = set()
    utility: set[str] = set()
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
        if line.startswith("utility:"):
            section = "utility"
            continue
        m = re.match(r"^  - id:\s*(\S+)", line)
        if m and section == "admitted":
            admitted.add(m.group(1))
        elif m and section == "utility":
            utility.add(m.group(1))
    return gates, admitted, utility


def load_catalog():
    rows = {}
    for r in csv.DictReader(open(CATALOG, encoding="utf-8")):
        rows[r["slug"]] = {
            "name": r["name"],
            "capability": float(r["intelligence"]) if re.match(r"^[\d.]+$", r.get("intelligence") or "") else None,
            "cost": float(r["best_turn"]) if r.get("best_turn") else None,
        }
    return rows


def load_models():
    out = {}
    for r in csv.DictReader(open(MODELS, encoding="utf-8")):
        def num(k):
            v = r.get(k) or ""
            return float(v) if v else None
        out[r["slug"]] = {
            "id": r["slug"], "catalog": r["catalog_slug"], "name": r["name"],
            "speed": num("speed_tps"), "ttft": num("ttft_s"), "cache": num("cache_hit"),
            "prefill": num("prefill_ms_per_1k"), "cache_loop": num("cache_loop_hit"),
            "retention": num("retention_4x"), "errors": num("errors_10"),
            "tools": num("tools_valid"), "override": num("intel_override"),
        }
    return out


# --------------------------------------------------------------------------- gates

def fails_static(capability, cost, g):
    f = []
    if capability is None or capability < g["capability_min"]:
        f.append(f"capability {capability or 0:.1f} < {g['capability_min']:.1f}")
    if cost is None or cost > g["cost_max"]:
        f.append(f"cost {cost or 0:.4f} > {g['cost_max']:.4f}")
    return f


# A short warm prompt hides what an agent turn costs: the prefix is re-read on
# every call, so at 60k the prefill dominates and the ranking flips. These two
# derived figures are what a person feels, so they are gates of their own.
CONTEXT_K = 60
ANSWER_TOKENS = 1500


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
    ttft = at_context(m)
    if ttft is None or ttft > g["latency_60k_max"]:
        f.append(f"ttft@60k {ttft or 0:.2f} > {g['latency_60k_max']:.2f}")
    turn = turn_time(m)
    if turn is None or turn > g["turn_60k_max"]:
        f.append(f"turn@60k {turn or 0:.1f} > {g['turn_60k_max']:.1f}")
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


GATES: dict[str, dict[str, float]] = {}


# --------------------------------------------------------------------------- config sync

def config_ids():
    """Model ids in the patch file, in either block or flow style."""
    text = CONFIG.read_text(encoding="utf-8")
    block = text.split("models:", 1)[1]
    return set(re.findall(r"^\s+- (?:\{\s*)?id:\s*([^,\s}]+)", block, re.M))


# --------------------------------------------------------------------------- check mode

def check() -> int:
    models, catalog = load_models(), load_catalog()
    problems = []

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

    for m in models.values():
        row = catalog.get(m["catalog"], {})
        capability = m["override"] if m["override"] is not None else row.get("capability")
        cost = row.get("cost")
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
        elif m["id"] in UTILITY:
            # A convenience route: in the menu on purpose, never claimed to pass.
            # It does not come from the catalog, so only the measured axes apply.
            own = fails_measured(m, capability, cost, GATES["measured"], include_static=False) + f3
            if own:
                print(f"  UTIL {m['name'][:30]:30s} {', '.join(own)}")
        elif not f2 and not f3:
            print(f"  ENTER {m['name'][:32]:32s} clears every gate but is not admitted")
            problems.append(f"{m['name']} clears every gate but is not admitted")

    for admitted_id in ADMITTED:
        if admitted_id not in models:
            problems.append(f"{admitted_id} is admitted but has no row in models.csv")

    configured = config_ids()
    for missing in ADMITTED - configured:
        problems.append(f"{missing} is in the policy but not in dsh/cordis.patch.yml")
    for extra in configured - ADMITTED - UTILITY:
        problems.append(f"{extra} is configured but not admitted")
    if not problems:
        print(f"\nOK: {len(ADMITTED)} rows clear all three phases, and the menu matches the policy")
    else:
        print("\nFAIL:")
        for p in problems:
            print(f"  - {p}")
    return 1 if problems else 0


# --------------------------------------------------------------------------- static mode

def static_only() -> int:
    catalog = load_catalog()
    overrides = {m["catalog"]: m["override"] for m in load_models().values() if m["override"] is not None}
    for slug, row in catalog.items():
        if row["capability"] is None and slug in overrides:
            row["capability"] = overrides[slug]
    ok = [(s, r) for s, r in catalog.items() if not fails_static(r["capability"], r["cost"], GATES["static"])]
    print(f"{len(catalog)} catalog rows, {len(ok)} clear phase 1:")
    for slug, r in sorted(ok, key=lambda x: -(x[1]["capability"] or 0)):
        print(f"  {r['name'][:44]:44s} capability {r['capability']:.1f}  ${r['cost']:.4f}/turn")
    return 0


# --------------------------------------------------------------------------- live mode

def api_key() -> str:
    m = re.search(r'COMMANDCODE_API_KEY:\s*"([^"]+)"', CREDS.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("no COMMANDCODE_API_KEY in ~/.dsh/.credentials.yaml")
    return m.group(1)


KEY = ""


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
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


def usage_tokens(data: dict) -> tuple[int, int]:
    u = data.get("usage", {})
    out = u.get("completion_tokens") or u.get("output_tokens") or 0
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
    if cached is None:
        cached = u.get("cache_read_input_tokens", 0)
    return out, cached


def measure(model: str) -> dict:
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
        except Exception:
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
        except Exception:
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
    KEY = api_key()

    static_fail = fails_static(capability, cost, GATES["static"])
    if static_fail:
        print(f"{model}: fails phase 1 - {', '.join(static_fail)}. Nothing measured.")
        return 1

    print(f"{model}: phase 1 clear (capability {capability:.1f}, ${cost:.4f}/turn)")
    values = measure(model)
    row = {"id": model, "name": model, "override": capability,
           **values, "catalog": ""}

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


# --------------------------------------------------------------------------- main

def main() -> int:
    global GATES, ADMITTED, UTILITY
    GATES, ADMITTED, UTILITY = load_policy()

    args = sys.argv[1:]
    if not args:
        return check()
    if args[0] == "--static":
        return static_only()
    if args[0] == "--model":
        model = args[1]
        capability = cost = None
        if "--capability" in args:
            capability = float(args[args.index("--capability") + 1])
        if "--cost" in args:
            cost = float(args[args.index("--cost") + 1])
        if capability is None or cost is None:
            raise SystemExit("--model needs --capability and --cost (the static phase)")
        return live(model, capability, cost)
    raise SystemExit("usage: evaluate.py | --static | --model <id> --capability X --cost Y")


ADMITTED: set[str] = set()
UTILITY: set[str] = set()

if __name__ == "__main__":
    sys.exit(main())
