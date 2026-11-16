# bench — choosing the models

One script, two data files, three questions. The script does not decide anything
by itself: it prices, it filters, it measures, and it says what it could not.

```bash
python bench/bench.py plan               # what a subscription costs per token
python bench/bench.py select             # fold 1: what is worth calling at all
python bench/bench.py measure            # fold 2: the stored table against the gates
python bench/bench.py agentic --provider opendesign --model deepseek-v4.1-flash
```

| | |
| --- | --- |
| `data/plans.json` | the plans, what they publish, and the catalogue they price from |
| `data/tbench.json` | the board: what each model does on Terminal-Bench |
| `models-policy.yml` | the gates, and what is admitted |
| `models.csv` | the measured rows: one line per route, with the eight numbers the gates read and the price it was charged at |

Nothing here edits the DSH configuration; that is a separate change in
[`../dsh/`](../dsh/).

## The funnel

```
prices   every model a provider sells, in every lane, with that plan's discount
   │     or credit multiplier — and what the plan costs per token once the blend,
   │     the promo and the window are folded in          (bench.py plan)
   ↓
fold 1   price → Terminal-Bench → policy
   │     free, calls no model                            (bench.py select)
   ↓
fold 2   speed, latency, cache, prefill, retention, errors, tool calls
fold 3   a real bug in a real repository, three rounds, pytest decides
   │                                                     (bench.py measure, agentic)
   ↓
admitted, and only then in the config
```

Each step can only remove rows. The gates live in
[`models-policy.yml`](models-policy.yml) and both folds read them from there, so a
threshold moves in one place.

## plan — how far each plan goes

A subscription costs the same whether it is used or not, and its per-model ceiling
stops the damage. So the question is not what a token costs: it is how many turns a
month buys of the model you want, and that is the whole table.

```bash
python bench/bench.py plan                        # every model worth a plan
python bench/bench.py plan --model claude-haiku-5.5
python bench/bench.py plan --today 2026-10-22     # the day a promo was live
```

One row per model, one column per plan. Two things feed a cell, and both come from
`data/plans.json`: the ceiling that model has on that plan (a per-model allowance,
or the plan's credits when the model has none), and what one turn consumes there
(the provider's list rate, its multiplier, and the hours it charges double for).
A dash means that plan does not sell the model.

The number is a ceiling, not a promise: a weekly or five-hour window can bind
before the monthly one, and `plan` takes the lowest. What it never does is let a
turn cost more than the plan's own fee divided by what that model is allowed.

### Where the numbers come from

Each provider carries the two pages that decide its cost, in `data/plans.json`
under `sources`, because the card alone does not say how far a plan goes:

| Provider | Card | The page with the detail |
| --- | --- | --- |
| `command-code` | `commandcode.ai/pricing` | `commandcode.ai/docs/plans/goat` — every model's monthly credit, plus the 5-hour and 7-day windows |
| `open-design` | `open-design.ai/pricing/` | `open-design.ai/model-credits/` — the plan's pool, its windows, and the multiplier per model |

The card is enough to know the fee; it is not enough to know how far the plan goes.
A new subscription is added by writing its two URLs and a reader for the second one
is a block with those two URLs and the numbers already filled in, which is the whole
of the work: this repo has no network call in it.

## select — fold 1

A turn is assumed to be **89.000 tokens read from cache + 1.000 fresh + 1.500
written**, which is what an agent call looks like after the prefix is warm:

```
cost = (89.000 × cache_read + 1.000 × input + 1.500 × output) / 1.000.000
```

Then the plan's multiplier applies, and the same model is not the same price twice:
one plan lists double and halves it with a 0,5× multiplier, another takes a tenth
off the list, a third charges double for a fifth of the week. The block's `factor`
and `billed_factor` are the whole of that, and no two plans have to agree.

What fold 1 will not do:

- price a model from another provider's catalogue, unless no catalogue exists and
  that is written down;
- judge capability from a provider's own claim;
- keep a list of models it has judged. There is no such list: a row the gate
  rejects is rejected again on the next run, and writing it down would be a
  snapshot of yesterday wearing a decision's clothes.

**One scale, and nothing else about the model.** Terminal-Bench 4.1 (`tb`) is the
only thing fold 1 knows about a model beyond its price: it runs terminal tasks and
grades whether they got done, and it ranks model **and agent** — "38,5 with Claude
Code" is a different claim from "38,5 alone", which is why the agent is stored with
the number. `tbench_min` is the floor.

The filter asks two questions and no more: what does it cost, and does the board
rank it. A model the board does not rank is out, with that reason printed on the
row — a purchase rule, not a judgement about the model. Everything else a model
*could* be described by (does it reason, does it call tools, how much context) was
removed on 2026-11-15: it gated nothing, and a number that gates nothing ends up
being quoted as if it did.

Two rows in the shortlist can be the same model on different routes, and the filter
does not merge them: it prices both and lets the number speak. The console is the
bill, not the page: one plan billed a model at ×2 while its own table printed ×4,
so `billed_factor` carries what was charged, `factor` keeps what was published, and
the observation is stored apart from the brochure, so neither is overwritten.

## measure — fold 2

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
  `4 × solo`, three rounds and the median: one round of this moved 0,74 to
  0,99 within ten minutes, which is the scheduler talking, not the route.
- *Error budget* — ten short calls, counting non-200 responses.
- *Tool calls* — one reply must carry two tools at once, right names, parseable
  arguments.

Claude rows go through `/messages` with a `cache_control` breakpoint: they refuse
`/chat/completions` and cache nothing without it.

```bash
python bench/bench.py measure                    # the stored table against the gates
python bench/bench.py measure --model <id> --tbench 38.5 --cost 0.0013
python bench/bench.py measure --provider opendesign --model deepseek-v4.1-flash
```

## agentic — fold 3

Synthetic numbers say nothing about whether a model can read a repository, find the
bug and fix it. This runs a 1.600-line module with two failing tests through DSH
headless, rebuilding the workspace every round, and lets pytest decide. Three of
three or it did not pass. A fixed repository makes the next round trivial and the
numbers meaningless; that mistake was made once.

## Where every number comes from

| Question | Source | Where |
| --- | --- | --- |
| What does the plan cost, and what does it give? | `commandcode.ai/pricing`, `open-design.ai` | `data/plans.json` |
| What does a token cost on that provider? | each provider's own catalogue or price list | `data/plans.json` |
| Can it do the work? | Terminal-Bench 4.1, executed and graded | `data/tbench.json` |
| How does it behave on the wire? | measured here | `models.csv` |

The provider is never asked to grade itself. Prices do come from the provider,
because nobody else can know them; whether the work gets done comes from a board
that runs it and grades the result. Two sources, and neither one is the seller.

## Adding a model or a provider

1. **A new provider** is a block in `data/plans.json` under `providers`: plan, fee,
   credits, its two pages under `sources`, and its models with either a `catalog`
   slug or their own `list_turn_usd` plus a `factor`. Then
   `python bench/bench.py plan` shows how far it goes.
2. **A new model on an existing provider** is one entry in that list. Run
   `python bench/bench.py select`: if the row says `out`, the printed reason is the
   whole story — nothing is recorded, because the gate will say it again tomorrow.
3. **Live, only for rows fold 1 marks `run`:**

   ```bash
   python bench/bench.py measure --model <id> --tbench <board score> --cost <usd per turn>
   ```

4. **If it clears everything:** append the row to `models.csv`, add the id to
   `admitted:`, and add the model to `models:` in
   [`../dsh/cordis.patch.yml`](../dsh/cordis.patch.yml).
5. **Prove it:** `python bench/bench.py measure` must exit 0.


## Re-baselining

The gates are the envelope of the admitted rows, less their own jitter. When the
source of a gate changes the floor moves with it, and the number has to move too:
two changes of source have already re-based it, 38 -> 30,0 -> 38,0, because each
scale measures something else and carrying the old number over would have admitted
nothing or everything.

## Still open

- A candidate is measured once; admitted rows are re-measured in three rounds.
- Transport TTFB lives in the endpoint bench, not here.
- Image input and structured output beyond tool calls.
