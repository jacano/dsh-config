# Decisions

Dated on purpose: each entry is what was decided with the numbers of that day, not a
rule that follows from the code. The live numbers are in `data/plans.json`,
`data/tbench.json` and `models.csv`; `plan`, `chart` and `measure` print them.

## 2026-11-16 · OpenDesign Go is the subscription to pay for

$10 buys a single pool of $220 of Coding Plan credits a month, capped at $55 per
seven days and $18 per five hours. What that works out to per million tokens, after
the multiplier and the ceiling, with its measured route beside it:

| Model | input | cache read | cache write | output | measured |
| --- | --- | --- | --- | --- | --- |
| DeepSeek V4.1 Flash | 0,00682 | 0,00014 | 0,00682 | 0,02727 | 103 t/s · 2,26 s |
| Claude Haiku 5.5 | 0,00909 | 0,00091 | 0,01136 | 0,04545 | 145 t/s · 1,32 s |
| DeepSeek V4.1 Flash Eco | 0,00368 | 0,00007 | 0,00368 | 0,01473 | 59 t/s - out |

Both admitted rows clear every gate. The eco is cheaper and out at 59 t/s, which is
not a slow reading: three runs, and the provider says so itself ("throughput-first
tier, may respond more slowly, recommended for batch"). Haiku carries a 4x multiplier
and is the most expensive token in the plan - still admissible, and the cache write
is 1,25x its input, as Anthropic prices it.

## 2026-11-16 · Command Code's value is the ceiling, not the volume

GOAT is $10 for a per-model credit (100 on DeepSeek V4.1 Flash, 60 on the Fast lane,
20 on Haiku and on new models, 10 on premium), through $20/5 h and $50/7 d windows.
On the two models both plans sell, it loses on price as well:

| Model | OpenDesign | Command Code |
| --- | --- | --- |
| DeepSeek V4.1 Flash, input | 0,00682 | 0,01812 |
| Claude Haiku 5.5, input | 0,00909 | 0,05000 |

What it has and OpenDesign's Go does not is a quality ceiling. Go tops out at
Haiku, Terminal-Bench 40,0, because it sells no Top Model Credits at all. GOAT sells
Opus 5.5 and Fable 5.2 at 65,8.

So: OpenDesign for the volume, and Command Code only if a hard problem needs a model
OpenDesign does not have. This one is unverified rather than rejected: the
subscription lapsed on 2026-11-16 with twenty of its models ranked and none of them
measured.

## 2026-11-16 · a subscription is a ceiling

A plan is spent whether or not it is used, and its ceiling stops the damage: past it,
Command Code falls back to pay-as-you-go credits and then pauses, OpenDesign waits for
the window to reset. Nothing can overdraw the $10. The fee divided by what the plan
lets a model spend is its rate, and that rate times the provider's multiplier is the
price the table prints - which is why the price is not a gate: it is a number to look
at.

## 2026-11-16 · the 220 was the pool, not a sum of per-model caps

The console's "models and their credit types" page lists a monthly usage figure per
model - 15 for Haiku, 120 for DeepSeek, 220 for the eco - and reading them as caps
was wrong. The credits page says Go is one pool of 220 and that those figures are
what a slice of credits buys on each model, its multiplier included. The mistake
priced Haiku fourteen times too high for an hour, which is why the reading is
recorded here and not just in the commit.

## 2026-11-16 · three questions and an agentic run, no pipeline

`plan` says what a token costs, `chart` draws price against Terminal-Bench, `measure`
puts what is left against the gates, and `agentic` runs one real task. Each answers
its own question and none of them chains into the next: there is no stage that
decides for the following one. The numbers are read by hand from the pages named
under `sources`, when someone asks.

## 2026-11-17 · prices, not turns

The table quoted turns per month, and a turn is a shape of traffic: 1k of fresh
input, 89k of cache read, 1,5k of output. That shape decided the ranking - the two
eco lanes sat four times apart on it and within ten per cent on the mix an invoice
implied - which means the table was quoting an assumption, not a price. It quotes
dollars per million now, of each kind of token, and says nothing about how the model
is used.

## 2026-11-17 · the analysis is a command, and a provider arrives by data

The reasoning that picked five models out of twenty-three was done by hand once, and a
conclusion nobody can re-run is a conclusion that rots. It is `chart` now: price across,
Terminal-Bench up, the floor as a red line, and the frontier drawn through whatever
nothing beats - `--mix` when the cost axis should be a request of a given shape rather
than a million tokens.

That closes the loop a new subscription goes through - **give the numbers, price them,
draw them, measure what survives** - and the order matters: the first two cost nothing
and the last is the only one that spends a token. A provider that stops before it is
unmeasured, not rejected, and the chart shows it as a point with nothing behind it.

