# Command Code model ranking — measured 2026-11-09

Runtime numbers on this machine, same probes for every row. Prices from
`commandcode.ai/models` (per 1M tokens).

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

## What did not separate them

Vision (all read a colour correctly), two parallel tool calls, JSON mode, valid
tool-call arguments, a 128k needle, and generated code that actually ran (5/5
test cases each). Quality differences showed up only as token spend: on the same
5 hard tasks at `effort: high`, reasoning tokens were 807 (Ultrafast), 1,403
(Fast), 1,967 (Plain), 504 (GLM), 3,693 (Muse).

## Verdict

Applied to `dsh/cordis.patch.yml` on 2026-11-09: two rows kept, four removed.

- **Keep Fast** — the default. Cheapest per agent turn, stable, caches, 5/6 +
  runnable code. Its only real gap is that it has no ZDR upstream.
- **Keep GLM-5.3 Flash** — deliberately, despite losing on speed and caching: it
  is the only non-DeepSeek model with a published score (41.8 / coding 71.5) and
  the only row with both a real score and a working ZDR upstream. A second
  opinion, not a daily driver.
- **Drop Ultrafast.** The premium lane: 0.5 s TTFT, ~780 t/s, the only row that
  accepted `off` — at $2.40/$9.60 per M, $0.0211 a turn, 8x Fast. Kept on the
  first pass, then dropped the same day: 1.2 s from Fast is fast enough, the
  config never needed the `off` level, and the price premium bought latency
  alone. `off` is now declared by no row.
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
