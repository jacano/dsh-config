# dsh-config

My [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH)
setup: one file, to reproduce on another machine.

DSH is a local agent harness. Sessions and credentials stay on your machine, and
it brings no model and no key of its own: you point it at a provider with your own
key. This repo is that configuration and nothing else, and no secret lives here.

The **desktop app** is the one this is written for: it carries its own runtime, so
no Node and no terminal. The web line is the same harness on Node, reading the
same file.

## Install

| Flavour | Platform | Get it |
| --- | --- | --- |
| Desktop | Windows x64 | [deepseek-harness-0.2.0-rc.2-win-x64.exe](https://download.deepseek.com/dsh-desk/bin/win-x64/deepseek-harness-0.2.0-rc.2-win-x64.exe) |
| Desktop | macOS Apple Silicon | [deepseek-harness-0.2.0-rc.2-mac-arm64.zip](https://download.deepseek.com/dsh-desk/bin/mac-arm64/deepseek-harness-0.2.0-rc.2-mac-arm64.zip) |
| Desktop | macOS Intel | [deepseek-harness-0.2.0-rc.2-mac-x64.zip](https://download.deepseek.com/dsh-desk/bin/mac-x64/deepseek-harness-0.2.0-rc.2-mac-x64.zip) |
| Web | Node.js 22+ | `npm install -g @deepseek-ai/dsh`, then `dsh web` |

Those are the only desktop builds published for that release. The links pin a
version and go stale with the next one; each app reads its own updater feed
instead, on the `nightly` channel:

```
https://download.deepseek.com/dsh-desk/feeds/<win-x64|mac-arm64|mac-x64>/nightly.yml
```

The npm line is version-free and follows the `latest` tag.

## Setup

Install from the table, then:

**1. Set the key**, once per machine. Open a new terminal afterwards: a running
process does not see a new variable.

```bash
export COMMANDCODE_API_KEY="your-command-code-key"
```

```powershell
[Environment]::SetEnvironmentVariable('COMMANDCODE_API_KEY', 'your-command-code-key', 'User')
```

**2. Restore the file.**

```bash
mkdir -p ~/.dsh && cp dsh/cordis.patch.yml ~/.dsh/
```

```powershell
New-Item -ItemType Directory -Force "$HOME\.dsh" | Out-Null
Copy-Item "dsh\cordis.patch.yml" "$HOME\.dsh\" -Force
```

**3. Run** the desktop app — or `dsh web` if you took the web line. The model menu
shows one group, **Command Code**, with six models. `dsh --profile web
--dump-config` prints what DSH composes from the file.

## The one file

`dsh/cordis.patch.yml` → `~/.dsh/cordis.patch.yml`: the providers and their
models, the default model, the permission presets, and the rows that take DeepSeek
out of the composition. Every profile reads it, and the home layer outranks a
profile's own, so one file covers both flavours.

It is a YAML array of loader patch entries: `id` names the row, `name` the plugin
behind it, and `config` replaces that row's config whole.

Three things it depends on:

- **A `name` that does not match its row is skipped with a warning**, not applied.
  Bundles repurpose ids across releases — `llm-deepseek` mounts
  `@deepseek-ai/dsh-llm-deepseek-api-key` on the desktop and
  `@deepseek-ai/dsh-llm-deepseek` from npm — so the rows whose plugin has moved
  carry no `name` and match by id.
- **Settings forms write below this file**, so anything pinned here shadows them.
  That is why the theme and the work-details mode are not pinned: they belong to
  Settings.
- **The file is read at boot and never watched.** Restart after editing it.

Everything in this repo is written in English: the README, the file's comments,
the commit messages.

## Models

Command Code — `https://api.commandcode.ai/provider/v1`, `openai-completions`, key
`COMMANDCODE_API_KEY`:

| Model | Id on the wire |
| --- | --- |
| DeepSeek V4.1 Flash | `deepseek/deepseek-v4.1-flash` |
| DeepSeek V4.1 Flash Fast | `deepseek/deepseek-v4.1-flash-fast` |
| GLM-5.3 Flash | `z-ai/glm-5.3-flash` |
| GLM-5.3 FlashX | `z-ai/glm-5.3-flashx` |
| Muse Spark 1.3 Contributor | `meta/muse-spark-1.3-contributor` |
| MiMo V2.6 Flash | `xiaomi/mimo-v2.6-flash` |

MiMo V2.6 Flash reads the way its gateway catalog entry spells it, and refuses
`max_tokens` 262144, so it takes the house 131072. The default model is
`deepseek/deepseek-v4.1-flash`: the same DeepSeek model, served by Command Code
rather than by the official API, so it never touches DeepSeek credits.

## Notes

- **Effort levels.** Every model takes `reasoning_effort` at the same five levels
  — `low`, `medium`, `high`, `xhigh`, `max`, each sent as itself on
  `POST /chat/completions` — and answers HTTP 400 to `minimal` and `none`. They
  all think by default and nothing turns it off (`thinking: {type: disabled}` and
  `enable_thinking: false` answer 200 and are ignored), so no entry declares
  `off:`, and `low` is cheaper rather than worse. Only the entries'
  `reasoningEfforts` puts the Effort submenu in the picker; the Settings → Models
  form leaves that field alone.
- **Images.** All six models read images, so the route declares
  `defaultInput: [text, image]` once. It is a fallback, not an override — a
  text-only model added later must declare `input: [text]`. Under-claiming costs a
  clear refusal at admission; over-claiming swaps the image for the literal
  `(image omitted: model does not support images)` mid-request, with nothing
  reporting it.
- **The official DeepSeek provider is off entirely**: `disabled: true` on the
  API-key chat route, the account chat route, the search provider and the
  request-field registry. No `deepseek-official` route exists, and no
  `DEEPSEEK_API_KEY` is stored. The registry is also what keeps
  `session-log-deepseek` and `plugin-package-inventory-deepseek` dormant, so
  neither the session log nor the plugin inventory rides along on an official
  request. Delete that block for the factory routes.
- **`web_search`** stays in a session's tool list — an agent preset composes it,
  and a preset has no patch semantics — but with the search provider gone every
  call fails with `WEB_PROVIDER_UNAVAILABLE`. The host `tool-web` row, the one
  `headless` uses, loses the tool outright with `search: false`.
- **Left on purpose:** `deepseek-account`, `account-controller` and
  `ui-settings-account` are the account page, not the provider. The
  developer-tools switch that gates the preset selector and the Trajectory tab is
  `ui-settings.enabled`, whose default is already `true`.
- **Two harmless warnings** on `web` and `headless`: `entry
  "llm-deepseek-account" not found` and `entry "ui-settings-account" not found`.
  Both rows are desktop-only.
- Never commit keys: DSH writes `.credentials.yaml` into its home, and the
  `.gitignore` here refuses it.
