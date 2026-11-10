# Command Code model ranking — 2026-11-09, revised 2026-11-10

Runtime numbers on this machine, same probes for every row. Prices from
`commandcode.ai/models` (per 1M tokens).

## 2026-11-10 round: cache, latency and cost per turn

The 2026-11-09 round ranked rows by sticker price and a single cold call. That
missed the thing that decides an agent turn: whether the prefix caches. This round
sends the same ~20k prefix twice with `max_tokens: 16`, so pass two measures the
cache and the elapsed time is the time to first token; output rate comes from a
separate 1,600-token generation.

| Model | Route | In / Out / Cache $/M | Pass-2 cache | TTFT | Output | Intel. | $/turn |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Claude Haiku 5.5** | messages | 0.10 / 0.50 / 0.01 | **60,304 read** | **1.4 s** | **146 t/s** | **43.4** | **$0.0017** |
| DeepSeek V4.1 Flash Fast | completions | 0.16 / 0.58 / 0.016 | 36,736 of 36,937 | 1.6 s | 116 t/s | 39.5 | $0.0025 |
| MiniMax M3.1 Flash | completions | 0.15 / 0.60 / 0.015 | 35,310 of 35,311 | 1.9 s | 124 t/s | 42.7 | $0.0024 |
| Muse Spark 1.3 Contributor | completions | 0.10 / 0.20 / 0.002 | **0** | 4.2-4.9 s | 164 t/s | 48.1 | $0.0093 |
| GLM-5.3 Flash | completions | 0.15 / 0.50 / 0.03 | **0** | 1.2-3.3 s | ~57 t/s | 41.8 | $0.0143 |
| Claude Sonnet 5.5 | messages | 2.00 / 10.00 / 0.10 | — | — | 94 t/s | 56.0 | $0.0259 |

$/turn keeps the 2026-11-09 assumption: a 90k prompt, 89k of it cached where
caching works, 1.5k of output.

Two findings reordered everything:

- **Anthropic caching is opt-in on the wire.** Without a `cache_control`
  breakpoint, Haiku's 60k prefix reads back 0 cached tokens and takes 3.2-3.5 s to
  first token; with one it reads 60,304 back and drops to 1.44 s. pi-ai adds the
  breakpoint itself, so the harness gets the good number, but a raw API caller
  does not.
- **A cheap sticker means nothing without a cache.** Muse Spark 1.3 Contributor is
  the cheapest row in the catalog ($0.10/$0.20, $0.002 cache) and the second
  fastest on a long generation (164 t/s), yet it caches nothing and re-pays the
  whole prefix every turn: $0.0093 a turn, 3.7x Fast and 5.5x Haiku. Its TTFT is
  also the worst of the group at 4.2-4.9 s.

### Verdict, 2026-11-10

Applied to `dsh/cordis.patch.yml`: Haiku 5.5 in, GLM-5.3 Flash out, Fast kept as
the fallback.

- **Keep Haiku 5.5 as the default.** It wins speed (146 vs 116 t/s), latency
  (1.4 vs 1.6 s), intelligence (43.4 vs 39.5) and cost per turn ($0.0017 vs
  $0.0025) against the row it replaces. It is the only row that does all four.
- **Keep Fast as the fallback.** Cheapest on a cold cache, stable across two
  rounds, and the only row on the `openai-completions` route, so an Anthropic
  outage leaves a working model behind.
- **Drop GLM-5.3 Flash.** ~57 t/s and no cache: it costs 8x Haiku a turn and is
  slower and less capable. Its ZDR upstream was its only argument, and this config
  does not buy on ZDR.
- **Do not re-add Spark Contributor, MiniMax, Step 5 or Sonnet.** The first has no
  cache and a 4-5 s TTFT; the second is beaten by Haiku on every axis; the last
  two cost 5-14x Fast a turn.

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
