# bench — choosing the models

Two folds: one costs nothing, the other spends tokens. Nothing here edits the
DSH configuration; that is a separate change in [`../dsh/`](../dsh/).

```bash
python bench/refresh.py          # read the providers' pages, report the diff
python bench/refresh.py --write  # store what it parsed in providers.json
python bench/modelsdb.py         # refresh what models.dev says about our models
python bench/capability.py       # refresh the AA scores
python bench/shortlist.py        # fold 1: what is worth calling at all
python bench/shortlist.py --write  # and save shortlist-<today>.csv
python bench/evaluate.py         # fold 2: the stored table against the gates
python bench/evaluate.py --model <id> --capability 30 --cost 0.0013   # a live run
```

## The funnel

```
prices ──── fold 1 ── price     every model a provider sells, in every lane, with
   │                            that plan's discount or credit multiplier
   ├────── fold 1 ── identity  models.dev: does it reason, does it call tools
   ├────── fold 1 ── capability Artificial Analysis: how good it is
   │           └─ IN rows ── fold 2 ── measured  speed, latency, cache
   │                              └── fitness   prefill, cache in a loop,
   │                                            retention, errors, tool calls
   └────────────────────────────────── admitted, and only then in the config
```

Each step can only remove rows. The gates live in
[`models-policy.yml`](models-policy.yml) and both folds read them from there, so a
threshold moves in one place.

## Where every number comes from

| Question | Source | File |
| --- | --- | --- |
| What does the plan cost, and what does it give? | `commandcode.ai/pricing`, `open-design.ai` | `providers.json` |
| What does a token cost on that provider? | Command Code: its own catalogue. OpenDesign: its own price catalogue | `catalog-2026-11-10.csv`, `open-design-prices.csv` |
| Does it reason? Does it call tools? Context? | models.dev, a third party | `models.dev.json` |
| How good is it? | Artificial Analysis | `capability.json` |
| How does it behave on the wire? | measured here | `models.csv` |

The provider is never asked to grade itself. Prices do come from the provider,
because nobody else can know them — but the *capability* and the *shape* of a
model come from catalogues that are not selling anything.

## Fold 1 in detail

A turn is assumed to be **89.000 tokens read from cache + 1.000 fresh + 1.500
written**, which is what an agent call looks like after the prefix is warm:

```
cost = (89.000 × cache_read + 1.000 × input + 1.500 × output) / 1.000.000
```

Then the plan's multiplier applies. The same model is not the same price twice:
DeepSeek V4.1 Flash is $0,0013 a turn on Command Code and $0,001317 on OpenDesign,
because OpenDesign lists double and then halves it with a 0,5× multiplier. The eco
lane there is 0,27×, which is the only real saving.

What fold 1 will not do:

- price a model from another provider's catalogue, unless no catalogue exists and
  that is written down;
- judge capability from a provider's own claim;
- reopen a model the policy has already judged. That list is
  [`models-policy.yml`](models-policy.yml) `excluded:`, and a reason there can be
  scoped to one provider, because a measurement on one route says nothing about
  another.

A model with no AA score and no models.dev row is neither rejected nor accepted:
it is printed as a question. That is the difference between a measurement and a
decision, and the second one is not this script's to make.

Missing data is never a reason to exclude, and the program enforces it: an entry in
`excluded:` whose reason is a gap is ignored with a warning, so the row surfaces as
a question instead of disappearing. A datum that is absent cannot be a verdict.

## Fold 2, and what a failure means

**Measured.** Speed is the median of three 1.600-token generations; latency is the
median of three warm passes after two priming requests; cache must read back on
those passes. Two more gates encode what a person actually feels on a long
context: the first token with 60k of prefix, and the whole turn at that size, so a
route that reads slowly cannot hide behind a fast short prompt.

**Fitness.** How the route behaves, not the model:

- *Prefill cost* — extra time per 1k prompt tokens, `(ttft_60k - ttft_5k) / 55k`.
- *Cache in a loop* — five identical turns, counting from the third. The first is
  always cold, and a probe that includes it can never look healthy.
- *Parallel retention* — four requests at once, aggregate throughput over
  `4 × solo`.
- *Error budget* — ten short calls, counting non-200 responses.
- *Tool calls* — one reply must carry two tools at once, right names, parseable
  arguments.

Claude rows go through `/messages` with a `cache_control` breakpoint: they refuse
`/chat/completions` and cache nothing without it.

## Files

| File | What it is |
| --- | --- |
| `refresh.py` | Reads the providers' own pages and reports what changed: fee, credits, windows, multipliers. |
| `modelsdb.py` | Reads models.dev: reasoning, tool calling, context, and the price per token. `--probe <id>` asks a model whether it reasons. |
| `capability.py` | Reads Artificial Analysis for the intelligence score. |
| `providers.json` | The plans: fee, credits, windows, and each model's multiplier or own price. One block per provider, no code. |
| `shortlist.py` | Fold 1: price, identity, capability, then the policy. Free. |
| `shortlist-<date>.csv` | A dated snapshot of fold 1, one row per provider × model. |
| `evaluate.py` | Fold 2: the gates, the live measurement, the config sync. |
| `models-policy.yml` | Decisions: the gates, what is admitted, what is excluded and why. |
| `models.csv` | The measured rows, medians of three rounds. The `rounds` column says so. |
| `catalog-2026-11-10.csv` | Command Code's priced catalogue, frozen. |
| `open-design-prices.csv` | OpenDesign's price catalogue, as its console shows it. |
| `capability.json` | The AA snapshot, with its date. |
| `models.dev.json` | The models.dev snapshot, with its date. |

## Adding a model or a provider

1. **A new provider** is a block in `providers.json`: plan, fee, credits, and its
   models with either a `catalog` slug or its own `list_turn_usd` plus a `factor`.
   Run `python bench/refresh.py` to see whether the pages agree with you.
2. **A new model on an existing provider** is one entry in that list. Run
   `python bench/shortlist.py`: if the row says `out`, the reason is printed —
   record it in `excluded:` only if a gate could not have known it.
3. **Live, only for rows fold 1 marks `run`:**

   ```bash
   python bench/evaluate.py --model <id> --capability <AA score> --cost <usd per turn>
   ```

4. **If it clears everything:** append the row to `models.csv`, add the id to
   `admitted:`, and add the model to `models:` in
   [`../dsh/cordis.patch.yml`](../dsh/cordis.patch.yml).
5. **Prove it:** `python bench/evaluate.py` must exit 0.

For comparing two gateways serving the same model — transport, short and long
calls, concurrency — use [jacano/llm-endpoint-bench](https://github.com/jacano/llm-endpoint-bench).

## Re-baselining

The gates are the envelope of the admitted rows. When the source of a gate
changes, the floor moves with it: the capability floor went from 38 to 30,0 the
day it stopped coming from the catalog and started coming from AA, because the two
scales are not the same thing and pretending otherwise would have admitted nothing.

## Still open

- A candidate is measured once; admitted rows are re-measured in three rounds.
- Transport TTFB lives in the endpoint bench, not here.
- Image input and structured output beyond tool calls.
