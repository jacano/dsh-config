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
shows one group, **Command Code**, with five models.

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
- Read at boot, never watched: restart after editing.

Everything here is written in English.

## Models

Command Code — `https://api.commandcode.ai/provider/v1`, `openai-completions`, key
`COMMANDCODE_API_KEY`:

| Model | Id on the wire |
| --- | --- |
| DeepSeek V4.1 Flash Fast (latest, thinking optional) | `deepseek/deepseek-v4.1-flash-fast` |
| DeepSeek V4.1 Flash (thinking always on) | `deepseek/deepseek-v4.1-flash` |
| GLM-5.3 Flash | `z-ai/glm-5.3-flash` |
| GLM-5.3 FlashX | `z-ai/glm-5.3-flashx` |
| Muse Spark 1.3 Contributor | `meta/muse-spark-1.3-contributor` |

The default model is `deepseek/deepseek-v4.1-flash-fast`, the row whose catalog
display name carries `(latest)`. The two V4.1 names describe what a probe measured
on 2026-10-17, not a build number: Command Code serves the pair from different
upstreams, and only the Fast row accepts a request with thinking switched off. Ask
either row what it is and both answer `unknown`, so neither name claims a snapshot.

## Notes

- **Effort.** Both V4.1 rows answer 200 to `off`, `low`, `medium`, `high`, `xhigh`
  and `max`, and 400 to `none` and `minimal` (measured 2026-10-17); the two GLM
  rows and Muse Spark take the five levels without `off`. Only the Fast row acts on
  `off` — 0 reasoning tokens against ~80-175 for the plain row, which thinks
  regardless of `off`, `thinking: {type: disabled}` or `enable_thinking: false`.
  That switch is not reachable from the picker: DSH spells `off` by *omitting* the
  reasoning option, which is what the provider already does by default, so no entry
  declares `off:` and the ladder stays at five levels. The submenu comes from each
  entry's `reasoningEfforts`; Settings → Models leaves it alone.
- **Output cap.** The wire accepted `max_tokens` up to 393216 on both V4.1 rows
  (same probe), so the 32768 in the entries is a choice, not a provider limit.
- **Images.** All five read images, declared once as `defaultInput: [text, image]`.
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
