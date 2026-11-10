#!/usr/bin/env python3
"""Provider fitness: is this model served well enough for agent work?

TTFT and tok/s answer "how fast is one call". This answers "is the route behind
the model fit for a loop": prefill scaling, cache under a real loop, throughput
under parallel load, and error budget.

Usage:
    python scripts/provider_fitness.py deepseek/deepseek-v4.1-flash-fast
    python scripts/provider_fitness.py --all

Stdlib only. Token counts come from the response's `usage`, never estimated.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CREDS = Path.home() / ".dsh" / ".credentials.yaml"
BASE = "https://api.commandcode.ai/provider/v1"

FILLER = ("Line {i} of the reference corpus: the quick brown fox jumps over the lazy dog "
          "while the engineer reviews patch number {i} and notes that the cache behaviour "
          "of model {i} remains under observation.\n")


def api_key() -> str:
    text = CREDS.read_text(encoding="utf-8")
    m = re.search(r'COMMANDCODE_API_KEY:\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("no COMMANDCODE_API_KEY in ~/.dsh/.credentials.yaml")
    return m.group(1)


KEY = api_key()


def chat(model: str, prompt: str, max_tokens: int = 16, timeout: int = 240) -> dict:
    """OpenAI chat for most rows, Anthropic messages for claude-* (they refuse chat)."""
    if model.startswith("claude-"):
        body = json.dumps({"model": model, "max_tokens": max_tokens,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        url = f"{BASE}/messages"
        headers = {"x-api-key": KEY, "anthropic-version": "2023-06-01",
                   "Content-Type": "application/json", "User-Agent": "curl/8.5.0"}
    else:
        body = json.dumps({"model": model, "max_tokens": max_tokens,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        url = f"{BASE}/chat/completions"
        headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
                   "User-Agent": "curl/8.5.0", "Accept": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def chat_messages_cached(model: str, prefix_text: str) -> int:
    """One Anthropic turn with a cache breakpoint; returns cached tokens."""
    body = json.dumps({
        "model": model, "max_tokens": 16,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prefix_text, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Reply with OK."}]}],
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/messages", data=body,
        headers={"x-api-key": KEY, "anthropic-version": "2023-06-01",
                 "Content-Type": "application/json", "User-Agent": "curl/8.5.0"},
        method="POST")
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = json.loads(resp.read().decode())
    return data.get("usage", {}).get("cache_read_input_tokens", 0)


TOOLS = [
    {"name": "get_weather", "description": "Current weather for a city",
     "params": {"city": {"type": "string"}}},
    {"name": "get_time", "description": "Current local time for a city",
     "params": {"city": {"type": "string"}}},
]

TOOL_PROMPT = ("Call get_weather for Seville and get_time for Seville. "
               "Use both tools in this single reply. Do not answer in prose.")


def _openai_tools():
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": {"type": "object",
                                         "properties": {k: {"type": v["type"]} for k, v in t["params"].items()},
                                         "required": list(t["params"])}}}
            for t in TOOLS]


def _anthropic_tools():
    return [{"name": t["name"], "description": t["description"],
             "input_schema": {"type": "object",
                              "properties": {k: {"type": v["type"]} for k, v in t["params"].items()},
                              "required": list(t["params"])}}
            for t in TOOLS]


def phase_tools(model: str, attempts: int = 2) -> dict:
    """Two tools in one reply, valid names and parseable arguments."""
    good = 0
    for _ in range(attempts):
        if model.startswith("claude-"):
            body = {"model": model, "max_tokens": 512, "tools": _anthropic_tools(),
                    "messages": [{"role": "user", "content": TOOL_PROMPT}]}
            url, headers = f"{BASE}/messages", {"x-api-key": KEY, "anthropic-version": "2023-06-01"}
        else:
            body = {"model": model, "max_tokens": 512, "tools": _openai_tools(),
                    "tool_choice": "auto",
                    "messages": [{"role": "user", "content": TOOL_PROMPT}]}
            url, headers = f"{BASE}/chat/completions", {"Authorization": f"Bearer {KEY}"}
        headers.update({"Content-Type": "application/json", "User-Agent": "curl/8.5.0"})
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            continue

        calls = []
        if model.startswith("claude-"):
            calls = [(b.get("name"), b.get("input")) for b in data.get("content", [])
                     if b.get("type") == "tool_use"]
        else:
            msg = data["choices"][0]["message"]
            for c in msg.get("tool_calls") or []:
                fn = c.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = None
                calls.append((fn.get("name"), args))

        names = {n for n, _ in calls}
        valid = (len(calls) >= 2 and names == {"get_weather", "get_time"}
                 and all(isinstance(a, dict) and "city" in a for _, a in calls))
        good += 1 if valid else 0
    return {"attempts": attempts, "valid": good / attempts if attempts else 0.0}


def prefix(lines: int, salt: str = "") -> str:
    return "".join(FILLER.format(i=i) for i in range(lines)) + salt


def timed(model: str, prompt: str, max_tokens: int = 16):
    start = time.perf_counter()
    data = chat(model, prompt, max_tokens)
    elapsed = time.perf_counter() - start
    usage = data.get("usage", {})
    out = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    if cached is None:
        cached = usage.get("cache_read_input_tokens", 0)
    return elapsed, out, cached


def phase_prefill(model: str) -> dict:
    """TTFT against prompt size. The slope is the provider's prefill cost."""
    points = []
    for lines in (120, 480, 1400):  # roughly 5k, 20k, 60k tokens
        salt = f"\nnonce {time.time_ns()}"
        elapsed, _, _ = timed(model, prefix(lines, salt))
        points.append((lines, elapsed))
    (l1, t1), (_, t2), (l3, t3) = points
    tokens = [l * 40 for l, _ in points]  # approx tokens per line
    slope_ms = (t3 - t1) / (tokens[2] - tokens[0]) * 1_000_000  # ms per 1k tokens
    return {"ttft_by_size_s": [round(t, 2) for _, t in points],
            "prefill_ms_per_1k": round(slope_ms, 2),
            "approx_tokens": tokens}


def phase_cache(model: str) -> dict:
    """Five identical turns. Real loops re-read the same prefix every turn."""
    fixed = prefix(480)
    hits = []
    for turn in range(5):
        if model.startswith("claude-"):
            data = chat_messages_cached(model, fixed)
            hits.append((0, data))
            continue
        elapsed, _, cached = timed(model, fixed + "\n\nReply with OK.")
        hits.append((round(elapsed, 2), cached))
    warm = hits[2:]
    hit_rate = sum(1 for _, c in warm if c > 0) / len(warm)
    return {"per_turn": hits, "hit_rate_from_turn3": round(hit_rate, 2)}


def phase_concurrency(model: str, workers: int = 4) -> dict:
    """Aggregate throughput versus one request, under parallel tool calls."""
    prompt = prefix(120)
    solo_start = time.perf_counter()
    data = chat(model, prompt, 200)
    solo_elapsed = time.perf_counter() - solo_start
    usage = data["usage"]
    solo_tps = (usage.get("completion_tokens") or usage.get("output_tokens") or 0) / solo_elapsed

    lock = threading.Lock()
    total_tokens = 0

    def one():
        nonlocal total_tokens
        d = chat(model, prompt + "\n\nWrite 200 words.", 200)
        with lock:
            u = d["usage"]
            total_tokens += u.get("completion_tokens") or u.get("output_tokens") or 0

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda _: one(), range(workers)))
    wall = time.perf_counter() - start
    aggregate = total_tokens / wall
    return {"solo_tps": round(solo_tps, 0), "aggregate_tps": round(aggregate, 0),
            "retention": round(aggregate / (solo_tps * workers), 2)}


def phase_errors(model: str, calls: int = 10) -> dict:
    """A route that fails one call in ten is not usable in a loop."""
    failures = 0
    for _ in range(calls):
        try:
            chat(model, "Reply with OK.", 16, timeout=60)
        except Exception:
            failures += 1
    return {"calls": calls, "failures": failures}


GATES = {
    "tools_valid": (">=", 0.9),
    "prefill_ms_per_1k": ("<=", 20),
    "hit_rate_from_turn3": (">=", 0.8),
    "retention": (">=", 0.6),
    "failures": ("<=", 1),
}


def verdict(name: str, value: float) -> str:
    op, limit = GATES[name]
    ok = value <= limit if op == "<=" else value >= limit
    return "pass" if ok else "FAIL"


def measure(model: str) -> int:
    print(f"\n=== {model} ===")
    problems = 0

    prefill = phase_prefill(model)
    print(f"prefill   ttft {prefill['ttft_by_size_s']} s at ~5k/20k/60k tokens")
    print(f"          slope {prefill['prefill_ms_per_1k']} ms per 1k tokens "
          f"[{verdict('prefill_ms_per_1k', prefill['prefill_ms_per_1k'])}]")
    problems += prefill["prefill_ms_per_1k"] > 20

    cache = phase_cache(model)
    print(f"cache     hit rate from turn 3: {cache['hit_rate_from_turn3']:.0%} "
          f"[{verdict('hit_rate_from_turn3', cache['hit_rate_from_turn3'])}]")
    problems += cache["hit_rate_from_turn3"] < 0.8

    conc = phase_concurrency(model)
    print(f"parallel  4x: solo {conc['solo_tps']:.0f} -> aggregate {conc['aggregate_tps']:.0f} "
          f"tok/s, retention {conc['retention']:.2f} "
          f"[{verdict('retention', conc['retention'])}]")
    problems += conc["retention"] < 0.6

    tools = phase_tools(model)
    print(f"tools     {tools['valid']:.0%} of {tools['attempts']} replies carried both calls "
          f"[{verdict('tools_valid', tools['valid'])}]")
    problems += tools["valid"] < 0.9

    err = phase_errors(model)
    print(f"errors    {err['failures']}/{err['calls']} failed "
          f"[{verdict('failures', err['failures'])}]")
    problems += err["failures"] > 1

    print(f"\n{'FIT' if problems == 0 else 'NOT FIT'}: {problems} gate(s) failed")
    return problems


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--tools":
        for m in args[1:]:
            r = phase_tools(m)
            print(f"{m}: tools_valid={r['valid']:.2f} ({r['attempts']} attempts)")
        return 0
    if not args:
        raise SystemExit("usage: provider_fitness.py <model-id> | --all")
    models = args
    if args == ["--all"]:
        policy = (ROOT / "models-policy.yml").read_text(encoding="utf-8")
        models = re.findall(r"^  - id:\s*(\S+)", policy.split("admitted:")[1].split("excluded:")[0],
                            re.M)
    total = sum(measure(m) for m in models)
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
