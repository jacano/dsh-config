# bench — choosing the models

One script, four data files, four questions. The script does not decide anything by
itself: it prices, it draws, it measures, it runs a task, and it says what it could
not.

The shape of the exercise - a subscription's real price per token against a
capability score, and a frontier through whatever nothing beats - is borrowed from
[linearbench](https://linearbench.pages.dev/). What changed is the axis on the left:
they plot an intelligence index against an estimated cost per task, and this plots
Terminal-Bench against what the plan actually charges, with the multiplier and the
ceiling already inside the number.

```bash
python bench/bench.py plan               # what a million tokens costs
python bench/bench.py chart              # the Pareto picture of the same table
python bench/bench.py chart --html docs/index.html       # the page the site serves
python bench/bench.py measure            # the stored table against the gates
python bench/bench.py agentic --provider opendesign --model deepseek-v4.1-flash
```

| | |
| --- | --- |
| `data/plans.json` | the plans, what they publish, and the catalogue they price from |
| `data/tbench.json` | the board: what each model does on Terminal-Bench |
| `models-policy.yml` | the gates, and what is admitted |
| `models.csv` | the measured rows: one line per route, with the eight numbers the gates read. No price - that is `plan`'s table |
| `page.html` | the page `chart --html` fills in, served by Pages from `docs/` |

Nothing here edits the DSH configuration; that is a separate change in
[`../dsh/`](../dsh/).

## Four questions, not a pipeline

```
plan     what a million tokens of each kind costs, per model, per plan
   │     the multiplier, the ceiling and the peak hour are already inside
chart    those rows as a picture: price across, the board up, the frontier drawn
   │     through whatever nothing beats              free, a png and a page
measure  the ones left, against the gates the policy states
   │     speed, latency, prefill, cache, retention, errors, tool calls
agentic  one real bug in one real repository, three rounds, pytest decides
   ↓
admitted, and only then in the config
```

Each command answers its own question and none of them chains into the next by
itself: you run the one you need. The gates live in
[`models-policy.yml`](models-policy.yml), so a threshold moves in one place.

## plan — what a million tokens costs

A price per token, with nothing assumed about how you use it. The multiplier, the
plan's ceiling and the hours it charges double for are already inside the number, so
what is left is the shape of your own traffic - and that is yours to know.

```bash
python bench/bench.py plan                        # every model worth a plan
python bench/bench.py plan --model claude-haiku-5.5
python bench/bench.py plan --today 2026-10-22     # the day a promo was live
```

```
  model                            tb plan                input  cache read  cache write     output
  deepseek-v4.1-flash-eco        38.5 open-design       0.00368     0.00007      0.00368    0.01473
  deepseek/deepseek-v4.1-flash-e 38.5 opengateway       0.00670     0.00060      0.00670    0.12000
  deepseek-v4.1-flash            38.5 open-design       0.00682     0.00014      0.00682    0.02727
  claude-haiku-5.5               40.0 open-design       0.00909     0.00091      0.01136    0.04545
  deepseek-v4-1-flash            38.5 command-code      0.01812     0.00036            -    0.07250
```

A dash in the write column is not a zero: it is a provider that prices writing as it
prices reading, or does not say. Anthropic's convention is 1,25x input, which Haiku
shows - and a turn that writes a prefix pays it once, so a workload that changes its
prompt often carries a cost the read column does not show.

A subscription turns fee and ceiling into a rate: `fee / what it lets you spend`,
times the provider's multiplier. A metered plan has no ceiling to divide by, so its
price is simply the price. That is the whole of it - there is no turn, no blend of
your own traffic, and no number standing in for one you have not measured.

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

## chart — the board, drawn

**One scale, and nothing else about the model.** Terminal-Bench 4.1 (`tb`) is the
only thing the chart knows about a model: it runs terminal tasks and grades whether
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
python bench/bench.py measure --model <id> --tbench 38.5
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

## Onboarding a provider

The work is in the data, and the four commands read it. In order:

1. **Give the numbers.** For each plan: the fee, what it buys (one pool or a ceiling
   per model), the windows it resets on, the multiplier per model, any discount with
   its dates, and the rate per million for input, cache read, cache write and output.
   The two pages they come from go in the block under `sources`.
2. **Write the block** in `data/plans.json`: one entry under `providers`, its models
   with `input`, `cache`, `cache_write`, `output` and a `factor`. Where the console
   charges something other than what the page advertises, `billed_factor` carries the
   bill and `factor` keeps the brochure - the same split `open-design` uses for Haiku.
3. **Price it:** `python bench/bench.py plan`. Every rate already has the multiplier,
   the ceiling and the peak hour inside it, so what it prints is what a million tokens
   costs - check those against the provider's own arithmetic.
4. **Draw it:** `python bench/bench.py chart`. Price across, Terminal-Bench up, the
   board's floor as a red line and the frontier drawn through whatever nothing beats.
   The picture answers "is anything here worth buying" before a token is spent, and
   `--mix fresh,cache,out` prices a request of your own shape instead of a million.
5. **Measure what survived:** `measure --model <id> --tbench <score>` for the rows
   worth the call. It prints a line in `models.csv`'s own shape; paste it, add the id
   to `admitted:`, add the model to the menu, and `measure` must then exit 0.

A provider that never reaches step 5 is unmeasured, not rejected - the chart shows it
as a point with no gate behind it, and that is the difference between "not worth it"
and "nobody tried".

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
