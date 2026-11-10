# Agentic fitness: is the route good enough, not just the model?

TTFT and tok/s answer how fast one call is. They do not answer whether the
provider serves the model well enough to survive a loop of twenty calls. Two
models with identical tok/s can differ 5x in how long they take to read a 60k
prefix, and that difference is invisible in the headline numbers.

This file explains the third phase. The limits live in
[`models-policy.yml`](models-policy.yml) and the numbers in
[`models.csv`](models.csv); neither is repeated here, so nothing here can go
stale. To see both applied, run `python bench/evaluate.py`.

## The five gates, and what a failure means

- **Prefill cost.** How much longer a call takes for every extra thousand prompt
  tokens. A provider that does not batch prefill makes every long context pay for
  it. It is a slope, not a time: `(ttft_60k - ttft_5k) / 55k tokens`, so it does
  not depend on which prompt size you happen to test.
- **Cache in a loop.** Five identical turns; the rate counts from the third,
  because the first is always cold and a probe that includes it can never look
  healthy. A route that does not honour the prefix cache re-bills the context on
  every turn.
- **Parallel retention.** Four requests at once, aggregate throughput divided by
  `4 × solo`. Harnesses run subagents and fan out tool calls; a route that folds
  under four requests makes the session crawl.
- **Error budget.** Ten short calls, counting non-200 responses. A loop that fails
  one call in ten is unusable regardless of how fast it writes.
- **Tool calls.** One reply must carry two tools at once, with the right names and
  parseable arguments. It is the closest thing to the real loop in this file.

Claude rows go through `/messages` with a `cache_control` breakpoint: they refuse
`/chat/completions`, and without the breakpoint they cache nothing at all.

## Why it is separate from speed

The per-call numbers describe one answer. An agent turn is a chain: read, plan,
edit, run, read again. In that chain the prefix is re-read on every step and
several calls may be in flight at once, so prefill and caching dominate the wall
clock, and a cheap model on a badly served route feels slower than an expensive
one on a good route.

That is the finding that removed three rows from the menu on 2026-11-10: they were
cheaper on sticker price and failed prefill or cache by a wide margin. The numbers
that justified each drop are in the `excluded:` list of
[`models-policy.yml`](models-policy.yml), dated, next to the model they killed.

## What it still does not cover

- One run per model in this phase; speed uses a median of three, fitness does not.
- Transport time to first byte lives in
  [llm-endpoint-bench](https://github.com/jacano/llm-endpoint-bench), not here.
- Image input and structured output beyond tool calls.
