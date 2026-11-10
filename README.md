# dsh-config

My [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH)
setup: one file, to reproduce on another machine.

DSH is a local agent harness. Sessions and credentials stay on your machine, and
it brings no model and no key of its own: you point it at a provider with your own
key. This repo is that configuration and nothing else, and no secret lives here.

The **desktop app** is the one this is written for.

## Install

| Flavour | Platform | Get it |
| --- | --- | --- |
| Desktop | Windows x64 | [deepseek-harness-0.2.0-rc.2-win-x64.exe](https://download.deepseek.com/dsh-desk/bin/win-x64/deepseek-harness-0.2.0-rc.2-win-x64.exe) |
| Desktop | macOS Apple Silicon | [deepseek-harness-0.2.0-rc.2-mac-arm64.zip](https://download.deepseek.com/dsh-desk/bin/mac-arm64/deepseek-harness-0.2.0-rc.2-mac-arm64.zip) |
| Desktop | macOS Intel | [deepseek-harness-0.2.0-rc.2-mac-x64.zip](https://download.deepseek.com/dsh-desk/bin/mac-x64/deepseek-harness-0.2.0-rc.2-mac-x64.zip) |
| Web | any platform | `npm install -g @deepseek-ai/dsh`, then `dsh web` |

## Setup

Install from the table, then:

**1. Set the key**, once per machine. Settings → Models → **Command Code** takes
it and stores it in `~/.dsh/.credentials.yaml`, which is resolved per request, so
nothing needs a restart.

By hand, that file is:

```yaml
version: 1
refs:
  COMMANDCODE_API_KEY: "your-command-code-key"
```

On macOS and Linux, `chmod 600` it: the store refuses a document readable beyond
its owner.

**2. Restore the file.**

```powershell
New-Item -ItemType Directory -Force "$HOME\.dsh" | Out-Null
Copy-Item "dsh\cordis.patch.yml" "$HOME\.dsh\" -Force
```

```bash
mkdir -p ~/.dsh && cp dsh/cordis.patch.yml ~/.dsh/
```

**3. Run** the desktop app — or `dsh web` if you took the web line. The model menu
shows two groups, **Command Code** and **Command Code (anthropic-messages)**, one
model each.

## The one file

`dsh/cordis.patch.yml` → `~/.dsh/cordis.patch.yml`. Every profile reads it and it
outranks the profile's own layer, so one file covers both flavours. It is a YAML
array of loader patch entries: `id` names the row, `name` the plugin, `config`
replaces that row's config whole.

- A `name` that does not match its row is skipped with a warning, not applied.
  Bundles repurpose ids — `llm-deepseek` is `dsh-llm-deepseek-api-key` on the
  desktop and `dsh-llm-deepseek` from npm — so rows whose plugin has moved carry
  no `name` and match by id.
- Settings forms write below this file, so a preference pinned here shadows the
  form; theme and work-details are left to Settings for that reason.
- **Hot-reloaded, no restart.** The layer is watched, not read once: saving a
  valid edit recomposes the running profile in place, so the desktop app and
  `dsh web` pick the change up as it is written. An edit that cannot apply —
  unparsable YAML, an entry that fails validation — is rejected and the last good
  composition keeps running. Startup-only profiles are the exception: the shipped
  `headless`, `acp` and SDK templates, and any manifest that sets
  `patchReload: startup`, take the layer only at boot.

Everything here is written in English.

## Models

Command Code — `https://api.commandcode.ai/provider/v1`, `openai-completions`, key
`COMMANDCODE_API_KEY`:

| Model | Id on the wire | Route |
| --- | --- | --- |
| DeepSeek V4.1 Flash Fast (latest) | `deepseek/deepseek-v4.1-flash-fast` | `command-code` |
| Claude Haiku 5.5 | `claude-haiku-5-5` | `command-code-anthropic` |

Claude does not speak Chat Completions on this provider: every `claude-*` id in
`GET /provider/v1/models` advertises only `/messages`, so it rides a second route
— `api: anthropic-messages`, base URL the API root
(`https://api.commandcode.ai/provider`, no `/v1`, because pi-ai appends
`/v1/messages`) — with `compat.forceAdaptiveThinking: true`, because Claude 5.5
answers 400 to `thinking.type.enabled` and wants adaptive thinking plus
`output_config.effort`.

The default model is `deepseek/deepseek-v4.1-flash-fast`: the owner's pick, and the
safe one — cheapest on a cold cache, stable across two measurement rounds, and the
only row on the completions route, so an Anthropic outage leaves a working model
behind. Haiku 5.5 wins the measured comparison and is one menu entry away. Each
label is the `name` the provider's catalog returns for that id, copied verbatim,
parentheses included.

Two rows, chosen by measurement rather than by what the catalog offers.
[MODELS.md](MODELS.md) holds the numbers; the short version:

| | Fast | Haiku 5.5 |
| --- | --- | --- |
| Role | default | the measured winner |
| Output rate | 116 tok/s | **146 tok/s** |
| TTFT, 20-60k prefix | 1.6 s | **1.4 s** |
| Caches the prefix | yes (36,736 of 36,937) | **yes (60,304 read)** |
| Intelligence | 39.5 | **43.4** |
| $ per agent turn | $0.0025 | **$0.0017** |

The `$/turn` column assumes a 90k prompt (89k of it cached where caching works)
and 1.5k of output. That assumption is what decides the ranking: Muse Spark 1.3
Contributor, at $0.10/$0.20 per M, looks 20x cheaper than Fast on sticker price
and lands 3.7x *above* it in real cost, because it caches nothing and re-pays the
whole prefix every turn.

### Model policy

[models-policy.yml](models-policy.yml) is the gate every row must clear before it
reaches the menu, and the record of what was measured and rejected:

- **≥ 100 tok/s** end to end, measured here.
- **TTFT ≤ 2.5 s** on a 20-60k prefix.
- **The prefix must cache** — a second identical request has to read cached tokens
  back.
- **≤ $0.0025 per agent turn**, the Fast ceiling. Nothing meaningfully more
  expensive than the reference row gets in, however good it looks.
- **Reachable on the plan** — no `403 MODEL_NOT_IN_PLAN`.

`python scripts/check_models.py` enforces it: the patch file and the policy must
name the same rows, nothing excluded may appear, and the default must be admitted
on the route it claims. It exits 1 with the offending row, so a model that fails a
gate cannot slip back in through a hurried edit. 22 rows are excluded and one is
kept out as redundant; every entry carries the measurement that killed it.

Dropped on 2026-11-09, with the measurement that killed each:

- **DeepSeek V4.1 Flash Ultrafast.** The premium lane — 0.5 s to first token and
  ~780 tok/s on its own Fireworks snapshot — priced at $2.40/$9.60 per M, 8x Fast's
  cost per turn. It was kept at first and dropped within hours: 1.2 s from Fast is
  fast enough, and the only thing it did that nothing else did — accept `off` —
  is worth less than $0.0211 a turn. Its `off` level went with it, so no row now
  declares one.
- **DeepSeek V4.1 Flash (plain).** Same 1017 snapshot as Fast but a worse lane:
  9-47 s to first token, a `max_tokens` ceiling that changes between identical
  requests (see below), and 2.1x Fast's cost per turn.
- **GLM-5.3 FlashX.** A paid speed tier ($0.37/$1.25) that is still slower than
  Fast, with no published score and no ZDR upstream. Beats nothing.
- **Muse Spark 1.3 Contributor.** Headline "up to 95% off" cancelled by a missing
  prompt cache — 0% cached on five straight passes over the same 90k prefix — plus
  the slowest TTFT of the six and no ZDR upstream (422 `cmd_zdr_no_providers`).

Dropped on 2026-11-10, on the same probes re-run against a 20k prefix:

- **GLM-5.3 Flash.** The second opinion stopped paying for itself: ~57 tok/s and no
  prompt cache at all, so it re-pays the whole prefix every turn ($0.0143 against
  $0.0025). Haiku 5.5 is faster, smarter (43.4 against 41.8) and cheaper.
- **MiniMax M3.1 Flash.** It does cache (35,310 of 35,311) and it is priced in the
  same band, but Haiku 5.5 beats it on every axis that matters here: 146 against
  124 tok/s, 43.4 against 42.7, $0.0017 against $0.0024 a turn.
- **Muse Spark 1.3 Contributor, again.** Re-measured and re-dropped: 164 tok/s on a
  long generation, but 0 cached tokens on the second pass over the same prefix and
  4.2-4.9 s to first token. Its sticker price is the cheapest in the catalog and
  its real cost is still 3.7x Fast.
- **Step 5 Preview and Sonnet 5.5.** Both clear the speed bar in the abstract, both
  cost 5-14x Fast a turn ($0.084 and $0.0259), so neither fits the budget this
  config is built around. Sonnet also measured 94 tok/s here, under the bar.

### What survives, and why

All of the candidates passed the same capability probes identically: vision,
JSON mode, two parallel tool calls in one message, valid tool-call arguments, a
128k-token needle, and generated Python that actually ran (5/5 cases each). The
differences that decided this were in the serving, not in what the models can do.

**Fast** is the default by choice: cheapest on a cold cache, stable across two
rounds of measurement, and the only row on the `openai-completions` route, so an
Anthropic outage leaves a working model behind.

**Haiku 5.5** is the row the numbers actually favour, and it is kept for that
reason: 146 tok/s against Fast's 116, 43.4 intelligence against 39.5, and $0.0017
a turn against $0.0025, because its cached prefix bills at $0.01/M where Fast's
bills at $0.016/M. It needed a second route to speak at all, and a `cache_control`
breakpoint to cache: without one, the same 60k prompt reads back 0 cached tokens
and costs 3.2-3.5 s to first token instead of 1.4 s.

### The lanes behind the survivors

Fast lives on the stable DeepSeek lane: the 1017 snapshot, a hard `max_tokens`
ceiling of 393,216, 2.0-2.3 s to first token on a 128k prompt. Ultrafast was a
separate Fireworks deployment (`…-1017-ultrafast`) with its own 1,048,576 ceiling
and ~780 tok/s; the plain lane was a third deployment again — native DeepSeek —
and the one that behaved worst: `max_tokens: 393217` was rejected once with "must
be between 0 and 393216" and then accepted on five straight retries, and its
`/responses` answers `resp_…` ids it cannot continue (`previous_response_id` →
400 `PreviousResponseNotFound`). Fast rejects anything above 393,216 every time.

## Notes

- **Effort.** Every entry declares the same five levels (`low`, `medium`, `high`,
  `xhigh`, `max`, sent as themselves), and the route answers 400 to `minimal` and
  `none`. The ladder is therefore declared once and aliased. The submenu comes from
  each entry's `reasoningEfforts`; Settings → Models leaves it alone. No row
  declares `off`: the one row that did take it — Ultrafast, 0 reasoning tokens with
  tools still working — was dropped, so the level is not offered at all.
- **Cache.** The prefix cache is not automatic on the Anthropic route: without a
  `cache_control` breakpoint the same 60k prompt reads back 0 cached tokens and
  costs 3.2-3.5 s to first token. pi-ai marks the last message itself, so the row
  needs no setting; the numbers in [MODELS.md](MODELS.md) were measured with that
  breakpoint in place.
- **Images.** Both rows read images, declared once as `defaultInput: [text, image]`.
  A text-only model added later must declare `input: [text]`, or its images are
  silently replaced by `(image omitted: model does not support images)`.
- **DeepSeek is off entirely**: API-key route, account route, search provider and
  request-field registry all `disabled: true`, and no `DEEPSEEK_API_KEY` stored.
  The registry is also what keeps `session-log-deepseek` and
  `plugin-package-inventory-deepseek` dormant.
- **`web_search`** is still listed and fails with `WEB_PROVIDER_UNAVAILABLE`: an
  agent preset composes it, and no patch reaches a preset.
- **Left on purpose:** `deepseek-account`, `account-controller` and
  `ui-settings-account` are the account page, not the provider. The
  developer-tools switch behind the preset selector and the Trajectory tab is
  `ui-settings.enabled`, `true` by default.
- Never commit keys: they live in `~/.dsh/.credentials.yaml`, outside this repo,
  and the `.gitignore` here refuses the file.

## Web and headless

The same file drives them and the models are the same. What differs:

- They log two warnings the desktop profile does not: `entry
  "llm-deepseek-account" not found` and `entry "ui-settings-account" not found`.
  Both rows are desktop-only, so those compositions have nothing to disable at
  those ids.
- The host `tool-web` row — the one `headless` uses — loses `web_search` outright
  with `search: false`.
- `dsh --profile web --dump-config` prints what DSH composes from the file, which
  is the way to check it by hand.
