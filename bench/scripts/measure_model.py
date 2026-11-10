#!/usr/bin/env python3
"""Phase 2: measure one model the way the policy expects.

Prints a CSV row ready for measurements-*.csv: speed (median of three
1,600-token generations), warm latency (median of three passes after two
priming calls) and whether the prefix cache is honoured.

Usage:
    python scripts/measure_model.py deepseek/deepseek-v4.1-flash-fast
    python scripts/measure_model.py claude-haiku-5-5

Stdlib only. Token counts come from `usage`.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CREDS = Path.home() / ".dsh" / ".credentials.yaml"
BASE = "https://api.commandcode.ai/provider/v1"

CORPUS = ("Line {i} of the reference corpus: the quick brown fox jumps over the lazy dog "
          "while the engineer reviews patch number {i} and notes that the cache behaviour "
          "of model {i} remains under observation.\n")
PROMPT = ("Write a continuous 1500-word essay on the history of writing instruments, "
          "from stylus to ballpoint. Plain prose, no lists, no headings. Do not stop early.")


def key() -> str:
    m = re.search(r'COMMANDCODE_API_KEY:\s*"([^"]+)"', CREDS.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("no COMMANDCODE_API_KEY")
    return m.group(1)


KEY = key()


def call(model: str, prompt: str, max_tokens: int, cache: bool = False) -> dict:
    if model.startswith("claude-"):
        content = [{"type": "text", "text": prompt}]
        if cache:
            content[0]["cache_control"] = {"type": "ephemeral"}
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content if cache else prompt}]}
        url, headers = f"{BASE}/messages", {"x-api-key": KEY, "anthropic-version": "2023-06-01"}
    else:
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        url, headers = f"{BASE}/chat/completions", {"Authorization": f"Bearer {KEY}"}
    headers.update({"Content-Type": "application/json", "User-Agent": "curl/8.5.0"})
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


def out_tokens(data: dict) -> int:
    u = data.get("usage", {})
    return u.get("completion_tokens") or u.get("output_tokens") or 0


def cached_tokens(data: dict) -> int:
    u = data.get("usage", {})
    c = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
    return c if c is not None else u.get("cache_read_input_tokens", 0)


def measure(model: str) -> None:
    speeds = []
    for _ in range(3):
        start = time.perf_counter()
        data = call(model, PROMPT, 1600)
        speeds.append(out_tokens(data) / (time.perf_counter() - start))

    corpus = "".join(CORPUS.format(i=i) for i in range(900))
    for _ in range(2):  # prime, so the cache is warm before measuring
        call(model, corpus + "\n\nReply with OK.", 16, cache=True)

    ttfts, hits = [], 0
    for _ in range(3):
        start = time.perf_counter()
        data = call(model, corpus + "\n\nReply with OK.", 16, cache=True)
        ttfts.append(time.perf_counter() - start)
        hits += 1 if cached_tokens(data) else 0

    speed = round(statistics.median(speeds))
    ttft = round(statistics.median(ttfts), 2)
    print(f"speed_tps={speed}  ttft_warm_s={ttft}  cache_hits={hits}/3")
    print(f"{model},,{model},{speed},{ttft},{hits/3:.3f},3,,,,")


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: measure_model.py <model-id>")
    measure(sys.argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
