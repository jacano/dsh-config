# bench — choosing the models

One script, two data files, three questions. The script does not decide anything
by itself: it prices, it filters, it measures, and it says what it could not.

```bash
python bench/bench.py refresh            # re-read the providers and both catalogues
python bench/bench.py refresh --write    # store what it parsed in data/
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
| `models.csv` | the measured rows, medians of three rounds |

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

## plan — what a plan costs per token

`select` asks whether a model is worth calling; this asks what the plan selling it
really charges. It is the only table that folds the four things that decide a
subscription into one number:

- **the money** — fee ÷ the usage it buys, times the model's multiplier;
- **the promo** — inside its window only. The number goes back up the day the
  offer closes, because a discount that never ends is a price, and this script
  refuses to treat one as the other;
- **the week** — five weekdays of seven peak hours are 20,8 % of the week at the
  peak price, and the catalogue says so itself ("Off-peak shown (17h/day) · peak
  $0.30 / $1.20"). A plan that publishes a flat price gets no blend; one that
  sells the peak lane as its own row is blended, not counted twice;
- **the window** — weekly and five-hour caps limit the *rate*, not the total.
  When one bites, the plan buys less than its credits and the price climbs.

`tokens/¥` is what one yuan buys at the plan's blended marginal price — the only
axis a $10 plan and a ¥500 plan can be put on together.

```bash
python bench/bench.py plan --today 2026-10-22    # the day a promo was live
python bench/bench.py plan --model deepseek-v4-pro
python bench/bench.py plan --write               # snapshots/, never versioned
```

## select — fold 1

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
- keep a list of models it has judged. There is no `excluded:` any more: a row that
  the gate rejects is rejected again on the next run, and writing it down was a
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

Two rows in the shortlist are the same model on different routes, and the filter
does not merge them: it prices both and lets the number speak. That is how
OpenDesign's Haiku turned out cheaper than Command Code's after the console showed
the plan billing ×2 where the page prints ×4 — `billed_factor` carries the bill,
`factor` keeps what the page says, and a refresh can no longer overwrite the
observation with the brochure.

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
  `4 × solo`.
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
   credits, and its models with either a `catalog` slug or its own `list_turn_usd`
   plus a `factor`. Run `python bench/bench.py refresh` to see whether the pages
   agree with you, and `python bench/bench.py plan` to see what it costs per token.
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

For comparing two gateways serving the same model — transport, short and long
calls, concurrency — use [jacano/llm-endpoint-bench](https://github.com/jacano/llm-endpoint-bench).

## Re-baselining

The gates are the envelope of the admitted rows. When the source of a gate
changes, the floor moves with it: it went 38 -> 30,0 when the catalogue's claim was
replaced by AA's index, and 30,0 -> 38,0 when AA was replaced by Terminal-Bench.
Each move is a different scale, and pretending otherwise would have admitted
nothing.

## Still open

- A candidate is measured once; admitted rows are re-measured in three rounds.
- Transport TTFB lives in the endpoint bench, not here.
- Image input and structured output beyond tool calls.
