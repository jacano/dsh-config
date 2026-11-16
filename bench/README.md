# bench — choosing the models

One script, three data files, four questions. The script does not decide anything
by itself: it prices, it filters, it measures, it runs a task, and it says what it
could not.

```bash
python bench/bench.py plan               # how many turns a month buys
python bench/bench.py filter             # what Terminal-Bench actually ranks
python bench/bench.py measure            # the stored table against the gates
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

## Three questions, not a pipeline

```
plan     what a subscription buys: turns per month, per model, per plan
   │     a number to look at, never a veto
filter   does Terminal-Bench rank it, and does it clear the floor
   │     free, calls no model
measure  the ones left, against the gates the policy states
   │     and against the menu, which has to agree
   ↓
admitted, and only then in the config
```

Each command answers its own question and none of them chains into the next by
itself: you run the one you need. The gates live in
[`models-policy.yml`](models-policy.yml), so a threshold moves in one place.

## plan — how far each plan goes

A subscription costs the same whether it is used or not, and its ceiling stops the
damage. So the question is not what a token costs: it is how many turns a month buys
of the model you want, and that is the whole table.

A turn is assumed to be **89.000 tokens read from cache + 1.000 fresh + 1.500
written**, which is what an agent call looks like after the prefix is warm:

```
cost = (89.000 x cache_read + 1.000 x input + 1.500 x output) / 1.000.000
```

Then the plan's multiplier applies, and the same model is not the same price twice:
one plan lists double and halves it with a 0,5x multiplier, another takes a tenth off
the list, a third charges double for a fifth of the week. The block's `factor` and
`billed_factor` are the whole of that, and no two plans have to agree.

```bash
python bench/bench.py plan                        # every model worth a plan
python bench/bench.py plan --model claude-haiku-5.5
python bench/bench.py plan --today 2026-10-22     # the day a promo was live
```

One row per model, one column per plan, and every cell answers the same question:
**what do ten dollars buy**. On a subscription that is its ceiling - a per-model
allowance, or the plan's credits when the model has none. On a metered plan there is
no ceiling, so it is simply ten dollars of usage. Two things feed a cell, both from
`data/plans.json`: that budget, and what one turn consumes (the provider's list
rate, its multiplier, and the hours it charges double for). A dash means that plan
does not sell the model.

**The turn is an assumption, and it is printed with the table.** By default it is
1k of fresh input, 89k of cache read and 1.5k of output, which flatters whichever
route discounts cache hardest. Pass your own shape and the cells change with it:

```bash
python bench/bench.py plan --mix 345000,309000,771     # fresh, cache, out
```

Two routes that look four times apart on the default mix can come out within ten per
cent of each other on an input-heavy one, because a discount is rarely the same
across the three kinds of token. When that matters, ask for the prices instead of
the turns - `plan --model <id>` prints what a million of each kind costs, with no mix
assumed at all:

```
  plan                        input   cache read     output
  command-code              0.01812      0.00036    0.07250
  open-design               0.00682      0.00014    0.02727
```

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
| `opengateway` | `opengateway.ai/pricing` | the same page: a metered tier has no ceiling to look up, only a price and a discount that may end |

The card is enough to know the fee; it is not enough to know how far the plan goes.
Adding a subscription is one block with those two URLs and its numbers already
filled in. This repo makes no network call: the numbers are read from the pages
above when someone asks, not on a schedule.

## filter — the board

**One scale, and nothing else about the model.** Terminal-Bench 4.1 (`tb`) is the
only thing `filter` knows about a model: it runs terminal tasks and grades whether
they got done, and it ranks model **and agent** — "38,5 with Claude Code" is a
different claim from "38,5 alone", which is why the agent is stored with the
number. `tbench_min` is the floor, and a model the board does not rank is out with
that reason on its row: a purchase rule, not a judgement about the model.

Everything else a model *could* be described by (does it reason, does it call
tools, how much context) was removed on 2026-11-15: it gated nothing, and a number
that gates nothing ends up being quoted as if it did.

Two spellings of one model are one row - plans write `deepseek-v4.1-flash` where the
catalogue writes `deepseek-v4-1-flash` - but two lanes of it are two rows, because a
fast lane and an eco lane are a different purchase. The console is the bill, not the
page: one plan billed a model at 2x while its own table printed 4x, so
`billed_factor` carries what was charged, `factor` keeps what the provider advertises, and
neither overwrites the other.

## measure — the gates, and the menu

**Measured.** Speed is the median of three 1.600-token generations; latency is the
median of three warm passes after two priming requests; cache must read back on
those passes. Two probes go further into what a person feels on a long context -
the first token with 60k of prefix, and the whole turn at that size - so a route
that reads slowly cannot hide behind a fast short prompt.

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
python bench/bench.py measure --model <id> --tbench 38.5 --cost 0.0013  # recorded, not gated
python bench/bench.py measure --provider opendesign --model deepseek-v4.1-flash
```

## agentic — a real task

Synthetic numbers say nothing about whether a model can read a repository, find the
bug and fix it. This runs a small module with one failing test through DSH headless,
rebuilding the workspace every round, and lets pytest decide. Three of three or it
did not pass. A fixed repository makes the next round trivial and the numbers
meaningless; that mistake was made once.

The module is deliberately small - three functions, one of them wrong - so the run
measures the loop (read the failure, change the code, run the tests again) and not
the model's ability to hold a large codebase. It is the cheapest question that still
uses the real harness.

## Where every number comes from

| Question | Source | Where |
| --- | --- | --- |
| What does the plan charge, and what does it give? | the provider's pricing card and its credits page, both named under `sources` | `data/plans.json` |
| What does a token cost on that provider? | the provider's own catalogue or price list | `data/plans.json` |
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
   `python bench/bench.py filter`: if the board does not rank it, that is the whole
   story — nothing is recorded, because the gate will say it again tomorrow.
3. **Live, only for rows `filter` keeps:**

   ```bash
   python bench/bench.py measure --model <id> --tbench <board score> --cost <usd per turn>
   ```

   `--cost` is the plan's price for that turn as `plan` reports it. It is written
   into the row and printed next to the numbers; it does not decide anything.

4. **If it clears everything:** paste the row `measure` printed into `models.csv`,
   add the id to `admitted:`, and add the model to `models:` in
   [`../dsh/cordis.patch.yml`](../dsh/cordis.patch.yml). `measure` prints the row in
   the table's own column order for exactly that.
5. **Prove it:** `python bench/bench.py measure` must exit 0.


## Re-baselining

The gates are the envelope of the admitted rows, less their own jitter. When the
source of a gate changes the floor moves with it, and the number has to move too:
two changes of source have already re-based it, 38 -> 30,0 -> 38,0, because each
scale measures something else and carrying the old number over would have admitted
nothing or everything.

## Still open

- A measurement is one run; the numbers inside it that move (retention) are already
  medians of three, and a row that matters is measured again when it is doubted.
- Image input and structured output beyond tool calls.
