# Command Code model ranking — 2026-11-09, revised 2026-11-10

Runtime numbers on this machine, same probes for every row. Prices from
`commandcode.ai/models` (per 1M tokens).

## 2026-11-10 round: cache, latency and cost per turn

The gates are the envelope of the admitted set: no row may be worse than the
current worst on any axis, so nothing new enters without a threshold moving on
purpose. `python scripts/evaluate_gates.py` checks both directions against
[measurements-2026-11-10-run2.csv](measurements-2026-11-10-run2.csv) and
[catalog-2026-11-10.csv](catalog-2026-11-10.csv). The table below is the raw
evidence those gates consume.

The 2026-11-09 round ranked rows by sticker price and a single cold call. That
missed the thing that decides an agent turn: whether the prefix caches. This round
sends the same ~20k prefix twice with `max_tokens: 16`, so pass two measures the
cache and the elapsed time is the time to first token; output rate comes from a
separate 1,600-token generation. Re-measured in full on 2026-11-10, 01:20.

| Model | Route | In / Out / Cache $/M | Pass-2 cache | TTFT cold/warm | Output | Intel. | $/turn |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Claude Haiku 5.5** | messages | 0.10 / 0.50 / 0.01 | **60,304 read** | 1.9 / 1.7 s | **146 t/s** | **43.4** | **$0.0017** |
| DeepSeek V4.1 Flash Fast | completions | 0.16 / 0.58 / 0.016 | 36,736 of 36,934 | **1.9 / 1.7 s** | 100-116 t/s | 39.5 | $0.0025 |
| MiniMax M3.1 Flash | completions | 0.15 / 0.60 / 0.015 | 35,072 of 35,308 | 2.2 / 1.3 s | 118 t/s | 42.7 | $0.0024 |
| GLM-5.3 Flash | completions | 0.15 / 0.50 / 0.03 | **36,992 of 37,014** | 2.0 / 0.7 s | 74 t/s | 41.8 | $0.0036 |
| Step 5 Preview | completions | 1.00 / 2.70 / 0.05 | 36,864 of 36,915 | 2.8 / 1.9 s | 167 t/s | 43.7 | $0.0095 |
| Nemotron 3.5 Super VL | completions | 0.20 / 0.50 / 0.04 | 41,984 of 41,991 | **1.5 / 0.8 s** | **382 t/s** | 26.5 | $0.0045 |
| Muse Spark 1.3 Contributor | completions | 0.10 / 0.20 / 0.002 | 35,939 (8/8 warm) | 2.6-5.3 s | 120 t/s | 48.1 | **$0.00058** |
| Claude Sonnet 5.5 | messages | 2.00 / 10.00 / 0.10 | 60,304 read | **1.40 / 1.17 s** | 100 t/s | 56.0 | $0.0259 |
| GPT-6 Luna | completions | 0.10 / 0.50 / 0.01 | 35,109 of 35,112 | 1.7 / 2.2 s | 95 t/s | 38.1 | $0.0017 |
| Muse Spark 1.2 Contributor | completions | 0.10 / 0.20 / 0.002 | 35,939 of 36,012 | 3.6 / 3.3 s | 113 t/s | 39.6 | **$0.00058** |
| Muse Ember | completions | 0.10 / 0.50 / 0.004 | 35,942 (7/8 warm) | 3.6-6.5 s | **299 t/s** | 36.0 (AA) | $0.0012 |
| Qwen 3.7 Flash | completions | 0.03 / 0.13 / 0.006 | 41,079 read | **7.79 / 4.65 s** | 64 t/s | — | ~$0.0008 |

$/turn keeps the 2026-11-09 assumption: a 90k prompt, 89k of it cached where
caching works, 1.5k of output.

Three findings reordered everything:

- **Anthropic caching is opt-in on the wire.** Without a `cache_control`
  breakpoint, Haiku's 60k prefix reads back 0 cached tokens and takes 3.2-3.5 s to
  first token; with one it reads 60,304 back and drops to 1.7 s. pi-ai adds the
  breakpoint itself, so the harness gets the good number, but a raw API caller
  does not.
- **The cache takes a few requests to warm, and a two-pass probe lies.** Muse Spark
  1.3 Contributor read 0 cached on pass 2 and 35,939 on pass 3; Ember read 0 on
  pass 2 and 35,942 on pass 4. Over eight identical requests they hit 8/8 and 7/8.
  One cold pass is not evidence of a cache-less model — the 2026-11-09 note on GLM
  made the same mistake in the same direction.
- **A warm cache helps the bill far more than the clock.** With it warm, Spark 1.3
  Contributor lands at $0.00058 a turn and Ember at $0.0012, both cheaper than Fast.
  Their start stays slow — 4.5 s median and 3.6-6.5 s — because that window is
  spent thinking, not reading the prefix. A control with unique prefixes was barely
  slower for Ember (3.8 s median), which is how little latency the cache buys.
- **The cheapest row still does not win.** Both Muse rows are 2-4x cheaper per turn
  than Fast and both start 1-4 s later than the gate allows. Cost alone never
  admits a row.

### Verdict, 2026-11-10

Applied to `dsh/cordis.patch.yml`: Haiku 5.5 in, GLM-5.3 Flash out, Fast kept —
and left as the default by choice. The gates themselves live in
[models-policy.yml](models-policy.yml) and `scripts/check_models.py` enforces them.

- **Fast stays the default.** It is the owner's pick and the safe one: cheapest on
  a cold cache, stable across two rounds, and the only row on the
  `openai-completions` route, so an Anthropic outage leaves a working model behind.
- **Haiku 5.5 is admitted as the measured winner**, not as the default. It wins
  speed (146 vs 100-116 t/s), latency (1.7 vs 1.7 s warm), intelligence (43.4 vs
  39.5) and cost per turn ($0.0017 vs $0.0025), and it is one menu entry away.
- **Drop GLM-5.3 Flash.** It caches, and well, but 74 t/s misses the speed gate and
  $0.0036 a turn is 1.4x the ceiling for a row that is less capable than Haiku. Its
  ZDR upstream was its only argument, and this config does not buy on ZDR.
- **MiniMax M3.1 Flash is admitted**, by owner choice: it clears every gate (118
  t/s, 35,072 cached, $0.0024) and Haiku beats it on all three axes, but a spare row
  on the completions route costs nothing.
- **Ember and Spark 1.3 Contributor are admitted with a slower start.** They trade
  the start for price: 4.7 s and 4.5 s to first token, but $0.0012 and $0.00058 a
  turn with 46.3 and 48.1 capability. Ember generates at 299 t/s, so its start is
  amortized past ~830 tokens of answer; Spark is the cheapest and smartest row in
  the catalog. They clear the measured gates (speed, latency, cache) and the static ones,
  which is exactly what keeps Spark 1.2 (39.6) and GLM (41.8) out.
- **GPT-6 Luna is admitted, and the capability gate moved to 38.0 to fit it.** 38.1 clears it outright: no waiver, no exception. It starts in 1.32 s and caches on every pass.
- **Do not re-add Spark 1.2 Contributor, Step 5 or Sonnet.** Spark 1.2 misses the
  static capability floor; Step 5 is 3.8x the ceiling and Sonnet 10x. All are
  listed with their numbers in [models-policy.yml](models-policy.yml), so a later
  round can re-test rather than re-argue.

---

## 2026-11-09 round (historical)

The first pass ranked by sticker price and a cold call. Kept for the record
because its numbers explain why the rows below were dropped.

| Model | In / Out / Cache $/M | Caches? | ZDR | TTFT | Output | Task score | $/turn | $/40 turns |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DeepSeek V4.1 Flash Fast | 0.16 / 0.58 / 0.016 | yes | **no** | 1.2 s | ~150 t/s | 5/6 + code runs | $0.0025 | $0.10 |
| DeepSeek V4.1 Flash | 0.15 / 0.60 / 0.047 | yes | yes | **9-47 s** | ~50-250 t/s | 5/6 | $0.0052 | $0.21 |
| GLM-5.3 FlashX | 0.37 / 1.25 / 0.075 | yes | **no** | 1.1-1.6 s | ~125 t/s | 5/6 + code runs | $0.0089 | $0.36 |
| Muse Spark 1.3 Contributor | 0.10 / 0.20 / 0.002 | **no** | **no** | 4.9-16 s | ~74-110 t/s | 5/6 + code runs | $0.0093 | $0.37 |
| GLM-5.3 Flash | 0.15 / 0.50 / 0.03 | **no** | yes | 1.2-3.3 s | ~57 t/s | 5/6 + code runs | $0.0143 | $0.57 |
| DeepSeek V4.1 Ultrafast | 2.40 / 9.60 / 0.048 | yes | yes | **0.5-0.6 s** | **~780 t/s** | 5/6 + code runs | $0.0211 | $0.84 |

$/turn assumes an agent turn with a 90k prompt (89k cached where caching works)
and 1.5k output. The ranking flips completely without that assumption: on sticker
price per token, Muse Spark Contributor looks 20x cheaper than Ultrafast, but it
caches nothing, so every turn re-pays the whole prefix.

### What did not separate them

Vision (all read a colour correctly), two parallel tool calls, JSON mode, valid
tool-call arguments, a 128k needle, and generated code that actually ran (5/5
test cases each). Quality differences showed up only as token spend: on the same
5 hard tasks at `effort: high`, reasoning tokens were 807 (Ultrafast), 1,403
(Fast), 1,967 (Plain), 504 (GLM), 3,693 (Muse).

### Drops

- **Drop Ultrafast.** The premium lane: 0.5 s TTFT, ~780 t/s, the only row that
  accepted `off` — at $2.40/$9.60 per M, $0.0211 a turn, 8x Fast. Kept on the
  first pass, then dropped the same day. `off` is now declared by no row.
- **Drop plain Flash.** Same 1017 snapshot as Fast but measurably worse: 9-47 s
  TTFT, a `max_tokens` ceiling that changes per request, and 2.1x the cost per turn.
- **Drop GLM-5.3 FlashX.** A paid speed tier ($0.37/$1.25) still slower than
  Fast, with no published score and no ZDR upstream. Beats nothing.
- **Drop Muse Spark Contributor.** Its headline 95% discount is cancelled by a
  missing prompt cache (0% cached on five straight passes over the same 90k
  prefix), plus the slowest TTFT of the six and no ZDR upstream
  (422 `cmd_zdr_no_providers`).

## Caveat on short answers

Both survivors think by default, and reasoning is billed against
`max_tokens`. At `max_tokens: 200` the Fast lane spent 197 of them thinking and
returned `"Ok 👍"` with `finish_reason: length`; the same prompt at 1500 returned
137 reasoning tokens and a complete answer. Give the row room — this config's
`maxTokens: 32768` is ample — because a small cap truncates the answer, not the
thinking.
