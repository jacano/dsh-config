# Agentic fitness: is the route good enough, not just the model?

TTFT and tok/s answer how fast one call is. They do not answer whether the
provider serves the model well enough to survive a loop of twenty calls. Two
models with identical tok/s can differ 5x in how long they take to read a 60k
prefix, and that difference is invisible in the headline numbers.

This file records the third phase and the numbers behind it. It is **enforced**
by `evaluate_gates.py`: an admitted row without fitness data fails the run.

## The gates

| Gate | Limit | What a failure means |
| --- | --- | --- |
| Prefill cost | ≤ 25 ms per 1k prompt tokens | the provider is not batching prefill; every long context pays it |
| Cache from turn 3 | ≥ 80% | the route is not honouring the prefix cache; every turn re-bills |
| Parallel retention | ≥ 0.60 | four concurrent calls collapse the throughput; subagents and tool fan-out suffer |
| Errors in 10 calls | ≤ 1 | the route is unstable; a loop that fails one call in ten is unusable |
| Tool calls valid | ≥ 90% | two tools in one reply, right names, parseable arguments — the closest thing to the real loop |

The prefill number is a slope, not a time: `(ttft_60k - ttft_5k) / 55k tokens`.
It separates the fixed gateway cost from the cost of reading the context, and it
does not depend on which prompt size you happen to test.

## How it is measured

`python scripts/provider_fitness.py <model-id>` runs four phases against
Command Code and prints the gates:

- **prefill**: three unique prompts at ~5k, ~20k and ~60k tokens, so the cache
  cannot hide the cost.
- **cache**: five identical turns; the hit rate counts from turn 3, because turn
  1 is always cold and a 5-pass probe that includes it can never exceed 80%.
- **parallel**: four requests at once, aggregate throughput divided by
  `4 × solo` throughput.
- **errors**: ten short calls, counting non-200 responses.
- **tools**: one reply must carry `get_weather` and `get_time` together, with
  parseable arguments. Two attempts; the rate is what counts.

Claude rows go through `/messages` with a `cache_control` breakpoint, because
they refuse `/chat/completions` and do not cache without it.

## Measured 2026-11-10

One run per model, same host, same hour.

| Model | Prefill ms/1k | Cache from t3 | 4x retention | Errors | Tools | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| DeepSeek V4.1 Flash Fast | 19.1 | 100% | 0.96 | 0/10 | 2/2 | **fit** |
| Claude Haiku 5.5 | 22.7 | 100% | 0.74 | 0/10 | 2/2 | fit at 25 |
| MiniMax M3.1 Flash | 23.1 | 100% | 0.84 | 0/10 | 2/2 | fit at 25 |
| GPT-6 Luna | **1.6** | 100% | 1.61 | 0/10 | 2/2 | **fit** |
| Muse Spark 1.2 Contributor | 60.2 | 100% | 1.29 | 0/10 | — | **prefill** |
| Muse Ember | 36.3 | 67% | 0.37 | 0/10 | — | **prefill, cache, parallel** |
| Muse Spark 1.3 Contributor | 115.2 | 33% | 1.18 | 0/10 | — | **prefill, cache** |

## What the numbers say

The three Muse rows are a different class of service, not a different class of
model. Spark 1.3 Contributor reads a 60k prompt in 6.8 s against 1.6 s for Luna,
and its cache honours one turn in three. Ember's aggregate throughput *falls* to
37% of its solo rate under four parallel calls: the route is the bottleneck, not
the model.

Luna is the surprise: 1.6 ms/1k makes it the cheapest route to read a long
context in the whole set, which is worth more in an agent loop than its 89 tok/s
suggests.

## Applied

The menu is DeepSeek, Haiku, MiniMax and Luna — four rows, all on providers that
prefill, cache and hold under load. Ember and both Spark Contributors were dropped
on 2026-11-10, whatever their sticker price said, because the service behind them
is what makes a session feel slow.
