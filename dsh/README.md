# dsh — the DSH configuration

This half of the repo is only the configuration: what makes DeepSeek Harness
speak to Command Code, and which four models appear in the menu. It carries no
benchmark, no measurements and no history — that is [`../bench/`](../bench/).

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
| MiniMax M3.1 Flash | `minimax/minimax-m3.1-flash` | `command-code` |
| GPT-6 Luna | `gpt-6-luna` | `command-code` |
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

Four rows, one mechanism in three phases: static, measured, provider fitness.
[MODELS.md](../bench/MODELS.md) holds the numbers; the short version:

| | Fast | MiniMax M3.1 | Haiku 5.5 | Luna |
| --- | --- | --- | --- | --- |
| Role | default | spare | the measured winner | the long-context one |
| Output rate | 113 tok/s | 107 tok/s | **146 tok/s** | 89 tok/s |
| TTFT, warm | 1.6 s | 1.9 s | **1.4 s** | 1.3 s |
| Prefill | 19.1 ms/1k | 23.1 ms/1k | 22.7 ms/1k | **1.6 ms/1k** |
| Caches the prefix | yes | yes | yes | yes |
| Intelligence | 39.5 | 42.7 | **43.4** | 38.1 |
| $ per agent turn | $0.0025 | $0.0024 | **$0.0017** | $0.0017 |

The `$/turn` column assumes a 90k prompt (89k of it cached where caching works)
and 1.5k of output. Luna is the interesting one: at 89 tok/s it is the slowest
row here, but its 1.6 ms/1k prefill makes it the cheapest way to read a long
context in the whole set, which in an agent loop matters more than the write
speed. The Muse rows that looked cheaper on sticker price were dropped for the
opposite reason — see [AGENTIC.md](../bench/AGENTIC.md).

### Choosing the models

Which rows are here, and why, is decided by a benchmark that lives in
[../bench/](../bench/). This file only records the result: four models, with
[`models-policy.yml`](../bench/models-policy.yml) as the source of truth for
what is admitted.

The short version: a model has to clear capability and price from the catalog
(free), then speed, latency and cache on the wire, then provider fitness — how
fast it reads a long prefix, whether it caches in a loop, whether it holds under
four parallel calls, and whether its tool calls are valid. Models that look cheap
and fail the last phase are out however good the sticker is; the full table is in
[AGENTIC.md](../bench/AGENTIC.md).

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
  needs no setting; the numbers in [MODELS.md](../bench/MODELS.md) were measured with that
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
