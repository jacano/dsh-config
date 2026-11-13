# bench — choosing the models

Three lanes. They share nothing but [`common.py`](common.py), which knows where
everything is and parses the two files more than one lane needs: the policy and
the price catalogue.

```
money/     what a subscription costs per token        free, calls no model
select/    fold 1: which models are worth calling     free, calls no model
measure/   fold 2: the battery, fold 3: real work     spends tokens
```

Nothing here edits the DSH configuration; that is a separate change in
[`../dsh/`](../dsh/).

```bash
python bench/money/refresh.py            # read the providers' pages, report the diff
python bench/money/refresh.py --write    # store what it parsed in providers.json
python bench/money/plan_cost.py          # what each plan costs per token, blend inside
python bench/select/modelsdb.py          # refresh what models.dev says about our models
python bench/select/capability.py        # refresh the AA scores
python bench/select/shortlist.py         # fold 1: what is worth calling at all
python bench/select/shortlist.py --write # and save shortlist-<today>.csv
python bench/measure/evaluate.py         # fold 2: the stored table against the gates
python bench/measure/evaluate.py --model <id> --capability 30 --cost 0.0013   # a live run
```

## The funnel

```
money   prices  every model a provider sells, in every lane, with that plan's
        │       discount or credit multiplier — and what the plan costs per token
        │       once the blend, the promo and the window are folded in
        ↓
select  fold 1  price → identity (models.dev: reason, tools) → capability (AA)
        │           └─ IN rows ─┐
        ↓                       ↓
measure fold 2  speed, latency, cache, prefill, retention, errors, tool calls
        └────── fold 3  a real bug in a real repository, three rounds, pytest decides
                                ↓
                            admitted, and only then in the config
```

Each step can only remove rows. The gates live in
[`models-policy.yml`](models-policy.yml) and every lane reads them from there, so
a threshold moves in one place.

## money/ — what a plan costs per token

`select/` asks whether a model is worth calling; this asks what the plan selling
it really charges, and it is the only table that folds the four things that decide
a subscription into one number:

```bash
python bench/money/plan_cost.py                       # today, every plan, DeepSeek V4.1 Flash
python bench/money/plan_cost.py --today 2026-10-22    # the day a promo was live
python bench/money/plan_cost.py --model deepseek-v4-pro
python bench/money/plan_cost.py --write
```

- **the money** — fee ÷ the usage it buys, times the model's multiplier;
- **the promo** — inside its window only. The number goes back up the day the
  offer closes, because a discount that never ends is a price, and this file
  refuses to treat one as the other;
- **the week** — five weekdays of seven peak hours are 20,8 % of the week at the
  peak price, and the catalogue says so itself ("Off-peak shown (17h/day) · peak
  $0.30 / $1.20"). A plan that publishes a flat price gets no blend; one that
  sells the peak lane as its own row is blended, not counted twice;
- **the window** — weekly and five-hour caps limit the *rate*, not the total.
  When one bites, the plan buys less than its credits and the price climbs.

`tokens/¥` is what one yuan buys at the plan's blended marginal price — the only
axis a $10 plan and a ¥500 plan can be put on together.

## select/ — fold 1 in detail

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

## measure/ — fold 2, and what a failure means

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

**Fold 3** is [`agentic.py`](measure/agentic.py): synthetic numbers say nothing
about whether a model can read a repository, find the bug and fix it. It runs a
1.600-line module with two failing tests through DSH headless, rebuilding the
workspace every round, and lets pytest decide. Three of three or it did not pass.

## Where every number comes from

| Question | Source | File |
| --- | --- | --- |
| What does the plan cost, and what does it give? | `commandcode.ai/pricing`, `open-design.ai` | `money/providers.json` |
| What does a token cost on that provider? | Command Code: its own catalogue. OpenDesign: its own price catalogue | `money/catalog-2026-11-10.csv`, `money/open-design-prices.csv` |
| Does it reason? Does it call tools? Context? | models.dev, a third party | `select/models.dev.json` |
| How good is it? | Artificial Analysis | `select/capability.json` |
| How does it behave on the wire? | measured here | `measure/models.csv` |

The provider is never asked to grade itself. Prices do come from the provider,
because nobody else can know them — but the *capability* and the *shape* of a
model come from catalogues that are not selling anything.

**models.dev never prices anything.** The `cost` block it carries is copied into
the shortlist as `crosscheck_turn_usd`, so a reader can put the shop's figure next
to a third party's; models.dev quotes the peak lane (0,30 / 1,20 / 0,007), so that
column runs about twice the catalogue's off-peak one and is the price of nothing.
No gate reads it, and `python bench/select/test_cost_sources.py` keeps it that
way: it multiplies those prices by a thousand, zeroes them and deletes them, then
requires every priced column and every verdict to stay put — and, so the test
cannot pass by looking at nothing, that turning a *signal* off does move verdicts.

## Files

**Shared**

| File | What it is |
| --- | --- |
| `common.py` | Where everything is, and the two readers both lanes use: the policy and the catalogue. A lane does not reach into another lane's folder except through here. |
| `models-policy.yml` | Decisions: the gates, what is admitted, what is excluded and why. |

**`money/` — the plans**

| File | What it is |
| --- | --- |
| `refresh.py` | Reads the providers' own pages and reports what changed: fee, credits, windows, multipliers, promos. |
| `providers.json` | The plans: fee, credits, windows, and each model's multiplier or own price. One block per provider, no code. A promo is stored as a window — model, `from`, `until`, the multiplier it drops to — because an offer without an end date is a price by the time anybody reads it. |
| `catalog-2026-11-10.csv` | Command Code's priced catalogue, frozen. |
| `open-design-prices.csv` | OpenDesign's price catalogue, as its console shows it. |
| `opencode-go-prices.csv` | OpenCode Go's catalogue. |
| `plan_cost.py` | What a plan really costs per million tokens: fee, multiplier, promo and peak week folded in. Free. |
| `plan-cost-<date>.csv` | A dated snapshot of that comparison. |

**`select/` — fold 1**

| File | What it is |
| --- | --- |
| `shortlist.py` | Fold 1: price, identity, capability, then the policy. Free. |
| `shortlist-<date>.csv` | A dated snapshot of fold 1, one row per provider × model. |
| `modelsdb.py` | Reads models.dev: reasoning, tool calling, context. `--probe <id>` asks a model whether it reasons. |
| `capability.py` | Reads Artificial Analysis for the intelligence score. |
| `models.dev.json` | The models.dev snapshot, with its date. Identity only: no gate takes a price from here. |
| `capability.json` | The AA snapshot, with its date. |
| `test_cost_sources.py` | Proof that models.dev cannot move a price, and that its signals can still move a verdict. |

**`measure/` — fold 2 and fold 3**

| File | What it is |
| --- | --- |
| `evaluate.py` | Fold 2: the gates, the live measurement, the config sync. |
| `models.csv` | The measured rows, medians of three rounds. The `rounds` column says so. |
| `agentic.py` | Fold 3: a real task through DSH headless, judged by pytest. |

## Adding a model or a provider

1. **A new provider** is a block in `money/providers.json`: plan, fee, credits, and
   its models with either a `catalog` slug or its own `list_turn_usd` plus a
   `factor`. Run `python bench/money/refresh.py` to see whether the pages agree
   with you, and `python bench/money/plan_cost.py` to see what it costs per token.
2. **A new model on an existing provider** is one entry in that list. Run
   `python bench/select/shortlist.py`: if the row says `out`, the reason is printed
   — record it in `excluded:` only if a gate could not have known it.
3. **Live, only for rows fold 1 marks `run`:**

   ```bash
   python bench/measure/evaluate.py --model <id> --capability <AA score> --cost <usd per turn>
   ```

4. **If it clears everything:** append the row to `measure/models.csv`, add the id
   to `admitted:`, and add the model to `models:` in
   [`../dsh/cordis.patch.yml`](../dsh/cordis.patch.yml).
5. **Prove it:** `python bench/measure/evaluate.py` must exit 0.

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
