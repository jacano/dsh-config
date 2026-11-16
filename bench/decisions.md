# Decisions

Dated on purpose: each entry is what was decided with the numbers of that day, not a
rule that follows from the code. The live numbers are in `data/plans.json`,
`data/tbench.json` and `models.csv`; `plan`, `filter` and `measure` print them.

The first two entries count **turns of 1k fresh input, 89k of cache read and 1.5k of
output**. `plan` prints prices per million tokens now, with no shape assumed; the
turn was the unit of the day and the counts below are that turn's arithmetic.

## 2026-11-16 · OpenDesign Go is the subscription to pay for

$10 buys a single pool of $220 of Coding Plan credits a month, capped at $55 per
seven days and $18 per five hours. Measured on the routes it matters for:

| Model | Turns a month | Measured |
| --- | --- | --- |
| DeepSeek V4.1 Flash | 167.046 | 103 t/s · 2,26 s · prefill 18,2 · retention 0,75 |
| Claude Haiku 5.5 | 63.218 | 145 t/s · 1,32 s · prefill 17,4 · retention 1,28 |

Both clear every gate. The DeepSeek Eco is cheaper again - 309.345 turns, 0,27x
multiplier - and it is out at 59 t/s, which is not a slow reading, it is three
readings: the lane is slow on purpose and the provider says so itself ("may respond
more slowly at times, recommended for batch processing").

Haiku is billed at 4x the Coding Plan credits. It still wins on volume against
Command Code's 11.494 turns, but it is the most expensive turn in the plan and it is
not the default.

## 2026-11-16 · Command Code's value is the ceiling, not the volume

GOAT is $10 for a per-model credit (100 on DeepSeek V4.1 Flash, 60 on the Fast lane,
20 on Haiku and on new models, 10 on premium), through $20/5 h and $50/7 d windows.
On the two models both plans sell, it loses on turns: 62.839 against 167.046 on
DeepSeek, 11.494 against 63.218 on Haiku.

What it has and OpenDesign's Go does not is a quality ceiling. Go tops out at
Haiku, Terminal-Bench 40,0, because it sells no Top Model Credits at all. GOAT sells
Opus 5.5 and Fable 5.2 at 65,8 for about 1.200-1.900 turns a month - 40 to 60 a day.

So: OpenDesign for the volume, and Command Code only if a hard problem needs a model
OpenDesign does not have. Not for volume, where it loses on both shared models. This
one is unverified rather than rejected: the subscription lapsed on 2026-11-16 with
twenty of its models ranked and none of them measured.

## 2026-11-16 · a subscription is a ceiling, so the question is turns

A plan is spent whether or not it is used, and its ceiling stops the damage: past it,
Command Code falls back to pay-as-you-go credits and then pauses, OpenDesign waits for
the window to reset. Nothing can overdraw the $10, so the price of a token is not
what decides - how many turns a month the ceiling buys is. That is the whole of
`plan`, and it is why the price is no longer a gate: a number to look at, not a veto.

## 2026-11-16 · the 220 was the pool, not a sum of per-model caps

The console's "models and their credit types" page lists a monthly usage figure per
model - 15 for Haiku, 120 for DeepSeek, 220 for the eco - and reading them as caps
was wrong. The credits page says Go is one pool of 220 and that those figures are
what a slice of credits buys on each model, its multiplier included. The mistake
priced Haiku fourteen times too high for an hour, which is why the reading is
recorded here and not just in the commit.

## 2026-11-16 · three questions and an agentic run, no pipeline

`plan` says what a subscription buys, `filter` says what Terminal-Bench ranks,
`measure` puts what is left against the gates, and `agentic` runs one real task.
Each answers its own question and none of them chains into the next: there is no
stage that decides for the following one. The numbers are read by hand from the
pages named under `sources`, when someone asks.
