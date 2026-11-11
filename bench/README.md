# bench — choosing the models

Two folds, and only the second one costs money.

```bash
python bench/refresh.py              # read the providers' pages, report the diff
python bench/refresh.py --write      # store what it parsed in providers.json
python bench/shortlist.py            # fold 1: what is worth calling at all, free
python bench/shortlist.py --write    # same, and save shortlist-<today>.csv
python bench/evaluate.py             # fold 2: the stored table against the gates
python bench/evaluate.py --model <id> --capability 42 --cost 0.0024   # a live run
```

Prices, credit windows and multipliers move without notice, so `refresh.py` reads
Command Code's pricing page, OpenDesign's pricing and credits pages, and the
OpenGateway API with your key. It prints every value next to the stored one and
writes nothing unless you pass `--write`. When a pattern does not match it says
so and keeps the old number: a guess is worse than a stale value you know is
stale. Run it before a selection, not on a schedule nobody reads.

## The funnel

```
providers.json + catalog  ── fold 1  shortlist   capability and price per plan,
                                                  with each provider's discount or
                                                  credit multiplier. No tokens.
        └─ IN rows ── fold 2  evaluate  phase 2  measured   speed, latency, cache
                                        phase 3  fitness   prefill, cache in a loop,
                                                           parallelism, errors, tools
              └─ admitted, and only then written to the config
```

The limits live in [`models-policy.yml`](models-policy.yml); they are not copied
here, because they move whenever a row enters or leaves. Both folds read them
from there, so a gate moves in one place and both change.

Fold 1 costs nothing and belongs to the provider, not the model: the same
DeepSeek costs $0,0013 a turn on Command Code, $0,0007 on OpenDesign and $0,0003
on an OpenGateway promotion, because each plan applies its own discount or credit
multiplier. [`providers.json`](providers.json) is where that lives.

`evaluate.py` exits non-zero if an admitted row misses a gate, has no fitness
data, or is not in the config.

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
| `refresh.py` | Reads the providers' own pages and reports what changed: plan fee, credits, windows, multipliers, and which models the key can see. |
| `shortlist.py` | Fold 1. Reads `providers.json` and the catalog, applies the static gates, prints what is worth calling. |
| `providers.json` | The providers, their plans and each model's discount or credit multiplier. One block per provider; no code to add one. |
| `shortlist-<date>.csv` | A dated snapshot of fold 1, one row per provider × model. |
| `evaluate.py` | Fold 2: phases, gates, live measurement, config sync. |
| `models-policy.yml` | Decisions: the gates, which ids are admitted, which are excluded and why. No per-model metrics. |
| `models.csv` | The only place metrics live. Admitted rows are medians of three rounds; the `rounds` column says so. |
| `catalog-2026-11-10.csv` | Frozen snapshot of the priced catalog, used by phase 1. |

## Adding a model

1. **Static, free.** Add the provider block to `providers.json` if it is new, and
   the model with its `catalog` slug or its own `list_turn_usd` and `capability`.
   Run `python bench/shortlist.py`: if the row says `out`, add the id to
   `excluded:` with the number that killed it and stop.
2. **Live, only for the rows fold 1 marks `IN`.**

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
