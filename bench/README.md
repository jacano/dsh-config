# bench — choosing the models

One process decides which models go in the menu. It never edits the DSH
configuration; that is a separate change in [`../dsh/`](../dsh/).

```bash
python bench/evaluate.py                  # the stored table against the gates
python bench/evaluate.py --static         # phase 1 only, over the catalog, free
python bench/evaluate.py --model <id> --capability 42 --cost 0.0024   # live run
```

## The funnel

```
catalog  ── phase 1  static     capability and price, no tokens spent
              └─ survivors ── phase 2  measured   speed, latency, cache
                   └─ measured ── phase 3  fitness   prefill, cache in a loop,
                                                     parallelism, errors, tool calls
                        └─ admitted, and only then written to the config
```

The limits live in [`models-policy.yml`](models-policy.yml); they are not copied
here, because they move whenever a row enters or leaves. `evaluate.py` prints them
with the table, and exits non-zero if an admitted row misses a gate, has no
fitness data, or is not in the config.

Phase 1 costs nothing: a row that fails capability or price is never called.

## The phases, and what a failure means

**Measured.** Speed is the median of three 1,600-token generations; latency is
the median of three warm passes after two priming requests; cache must read back
on those passes. A route that does not cache re-bills the context every turn.

**Fitness.** How the route behaves, not the model:

- *Prefill cost* — extra time per 1k prompt tokens, `(ttft_60k - ttft_5k) / 55k`.
  A provider that does not batch prefill makes every long context pay for it.
- *Cache in a loop* — five identical turns, counting from the third. The first is
  always cold, and a probe that includes it can never look healthy.
- *Parallel retention* — four requests at once, aggregate throughput over
  `4 × solo`. A route that folds under four makes a session crawl.
- *Error budget* — ten short calls, counting non-200 responses.
- *Tool calls* — one reply must carry two tools at once, right names, parseable
  arguments. The closest thing to the real loop.

Claude rows go through `/messages` with a `cache_control` breakpoint: they refuse
`/chat/completions` and cache nothing without it.

## Files

| File | What it is |
| --- | --- |
| `evaluate.py` | The whole process: phases, gates, live measurement, config sync. |
| `models-policy.yml` | Decisions: the gates, which ids are admitted, which are excluded and why. No per-model metrics. |
| `models.csv` | The only place metrics live. Admitted rows are medians of three rounds; the `rounds` column says so. |
| `catalog-2026-11-10.csv` | Frozen snapshot of the priced catalog, used by phase 1. |

## Adding a model

1. **Static, free.** Get capability and price per turn. If either fails, add the
   id to `excluded:` with the number that killed it and stop.
2. **Live.**

   ```bash
   python bench/evaluate.py --model <id> --capability <score> --cost <usd-per-turn>
   ```

   It runs the phases in order, stops at the first failure, and prints a CSV row.
3. **If it clears everything:** append the row to `models.csv`, add the id to
   `admitted:`, and add the model to `models:` in
   [`../dsh/cordis.patch.yml`](../dsh/cordis.patch.yml).
4. **Prove it:** `python bench/evaluate.py` must exit 0.

A new subscription needs no new code: the URL, `api` and headers live in the DSH
config, and the scripts only take a model id. For comparing two gateways serving
the same model — transport, short and long calls, concurrency — use
[jacano/llm-endpoint-bench](https://github.com/jacano/llm-endpoint-bench).

## Re-baselining

The gates are the envelope of the admitted rows: nothing enters without a
threshold moving on purpose, in a commit that names the number. Re-run the funnel
when a provider changes something, and replace the round medians in `models.csv`.

## Still open

- A candidate is measured once; admitted rows are re-measured in three rounds.
- Transport TTFB lives in the endpoint bench, not here.
- Image input and structured output beyond tool calls.
