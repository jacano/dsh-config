# dsh — the DSH configuration

This half of the repo is only the configuration: what makes DeepSeek Harness
speak to Command Code, and which models appear in the menu. It carries no
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
shows two groups: **Command Code**, on the OpenAI-compatible route, and
**Command Code (anthropic-messages)** for the Claude rows.

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

The rows are the `models:` list in [`cordis.patch.yml`](cordis.patch.yml). This
file does not repeat them: a second copy of the menu drifts from the first, and
`python bench/evaluate.py` prints the list with its current numbers whenever you
want to see it.

Claude does not speak Chat Completions on this provider: every `claude-*` id in
`GET /provider/v1/models` advertises only `/messages`, so it rides a second route
— `api: anthropic-messages`, base URL the API root
(`https://api.commandcode.ai/provider`, no `/v1`, because pi-ai appends
`/v1/messages`) — with `compat.forceAdaptiveThinking: true`, because Claude 5.5
answers 400 to `thinking.type.enabled` and wants adaptive thinking plus
`output_config.effort`.

The default model is `deepseek/deepseek-v4.1-flash-fast`: the owner's pick, and the
safe one — cheapest on a cold cache, stable across measurement rounds, and on the
completions route, so an Anthropic outage leaves a working model behind. Each label
is the `name` the provider's catalog returns for that id, copied verbatim,
parentheses included.

Which rows are here and why is decided in [../bench/](../bench/). This file records
only the result, never the metrics: the numbers live in
[`models.csv`](../bench/models.csv) and the menu in
[`cordis.patch.yml`](cordis.patch.yml). `python bench/evaluate.py` prints both.

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
  needs no setting; the numbers in [models.csv](../bench/models.csv) were measured with that
  breakpoint in place.
- **Images.** Every row reads images, declared once as `defaultInput: [text, image]`.
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
