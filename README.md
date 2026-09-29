# dsh-config

My [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH)
setup, to reproduce it fast on another machine: the settings and the patch
layers of the two flavours it ships in.

## What DSH is

DSH is a **local** agent harness. It runs on your machine, keeps your sessions,
your workspace and your credentials there, and it brings no model and no key of
its own: you point it at a provider with your own key. Nothing to sign up to —
something to install, configure once, and then use from a browser tab or from a
window on the desktop.

This repo is that configuration and nothing else. No secret is stored here, and
the only things it holds are the two files DSH reads on startup plus the profile
of the desktop app.

## Two flavours, one configuration

DSH ships the same harness with two front ends:

- **The web build.** `npm install -g @deepseek-ai/dsh`, then `dsh web`. It serves
  the UI on `127.0.0.1` and prints a link with a token. `npx @deepseek-ai/dsh web`
  runs it with no install at all. This is the flavour that needs Node.js.
- **The desktop apps.** An installer per platform, from the table below. The
  desktop app is a shell around the same web app bundle: the profile of this
  machine declares `@deepseek-ai/dsh-web-app` among its bundles
  (`dsh/profiles/desktop/package.json`), so the window runs exactly what
  `dsh web` serves, and it brings its own runtime, so it needs no Node.js.

**Both read the same home directory, `~/.dsh`**: the same `settings.yaml`, the
same patch layers, the same credentials, the same sessions and workspaces. There
is nothing to configure twice — the model menu, the permissions and the theme you
set in one are what the other starts with — and this repo is that one
configuration, so restoring `dsh/` covers the two flavours at once.

One nuance about scope, because it explains the two patch files this repo holds:
a `profiles/<name>/cordis.patch.yml` applies to **that profile only** (each
profile has one, and the desktop app works in `profiles/desktop/`), while the
home-level `~/.dsh/cordis.patch.yml` and `settings.yaml` apply to **every**
profile, the web and headless ones included. Anything that must hold everywhere
goes in the home-level files; the per-profile file is where the graphical
settings forms persist what you edit inside the app.

### Download

| Flavour | Build | File |
| --- | --- | --- |
| Web | any platform with Node.js 22+ | `npm install -g @deepseek-ai/dsh` (or `npx @deepseek-ai/dsh web`) |
| Desktop | Windows x64 | [deepseek-harness-0.1.7-rc.1.20260924.1-win-x64.exe](https://download.deepseek.com/dsh-desk/bin/win-x64/deepseek-harness-0.1.7-rc.1.20260924.1-win-x64.exe) |
| Desktop | macOS Apple Silicon | [deepseek-harness-0.1.7-rc.1.20260924.1-mac-arm64.dmg](https://download.deepseek.com/dsh-desk/bin/mac-arm64/deepseek-harness-0.1.7-rc.1.20260924.1-mac-arm64.dmg) |

Those are the two desktop builds published for the current release
(`0.1.7-rc.1.20260924.1`): there is no Intel-mac, Windows-on-ARM or Linux package
under `download.deepseek.com/dsh-desk/bin/`. The web flavour is not downloaded at
all; it comes from npm.

## Contents

- `dsh/settings.yaml` — user settings: the model providers and the default
  model. Every profile reads it, so it is the file that makes the web build and
  the desktop app show the same menu.
- `dsh/cordis.patch.yml` — the home-level patch layer. DSH applies it to every
  profile and it outranks each profile's own layer. It disables `web_search`.
- `dsh/profiles/desktop/` — the desktop profile as this machine has it:
  `cordis.patch.yml` (what the app's settings forms write: permissions, theme,
  default model, providers), plus the profile's `cordis.yml`, `package.json` and
  `pnpm-workspace.yaml`, which DSH composes the profile from.

Patch order, from the weakest to the strongest: the bundles of the profile, then
the profile's `cordis.patch.yml`, then the home-level `~/.dsh/cordis.patch.yml`,
then any `--patch` overlay.

## Before you start

- Node.js 22 or newer, for the web flavour. The desktop installers need none.
- A **Command Code** account and API key. That is the only provider that is
  active in this setup.
- An **OpenCode Go** subscription and API key, only if you want to re-enable the
  OpenCode entries, which are commented out in both files.

## 1. Install DeepSeek Harness

Web flavour:

```bash
npm install -g @deepseek-ai/dsh
dsh --version
```

Desktop flavour: run the installer of your platform from the **Download** table
above.

## 2. Set the API keys

The settings file never holds a secret. It only names the environment variables
that hold the keys, so set them once per machine.

macOS / Linux (bash or zsh):

```bash
export COMMANDCODE_API_KEY="your-command-code-key"
export OPENCODE_API_KEY="your-open-code-go-key"   # only for the commented entries
```

Windows (PowerShell, stored for the user):

```powershell
[Environment]::SetEnvironmentVariable('COMMANDCODE_API_KEY', 'your-command-code-key', 'User')
[Environment]::SetEnvironmentVariable('OPENCODE_API_KEY', 'your-open-code-go-key', 'User')
```

Open a new terminal after this step. A running process does not see a new
environment variable.

## 3. Restore the config

Copy the contents of `dsh/` into the DSH home. Create the folder if it does not
exist.

macOS / Linux:

```bash
mkdir -p ~/.dsh
cp -R dsh/. ~/.dsh/
```

Windows (PowerShell):

```powershell
New-Item -ItemType Directory -Force "$HOME\.dsh" | Out-Null
Copy-Item -Recurse -Force "dsh\*" "$HOME\.dsh\"
```

## 4. Run

Web flavour:

```bash
dsh web
```

Desktop flavour: start the app. The web UI listens on `127.0.0.1` and prints a
link with a token, and the desktop window loads the same UI.

Either way the model menu shows one group, **Command Code**, with five models.
The OpenCode groups are commented out in the configuration, so they are not in
the menu until you remove the `# ` from their blocks.

## Providers

Every provider name and every model name carries the wire it speaks in
parentheses: `openai-completions` for `POST /chat/completions` and
`openai-responses` for `POST /responses`. That is the whole difference between
the two entries of OpenCode Go: one service, two API shapes.

### Command Code — active

- Endpoint: `https://api.commandcode.ai/provider/v1` (`openai-completions`).
- Key: environment variable `COMMANDCODE_API_KEY`.
- Five models, all on the chat endpoint: DeepSeek V4.1 Flash, DeepSeek V4.1
  Flash Fast, GLM-5.3 Flash, Muse Spark 1.3 Contributor and Space Bunny Alpha.
- Muse Spark answers on the Responses API here as well, but this route registers
  it on the chat endpoint, so one provider covers all five.
- Space Bunny Alpha is a stealth model: free while its test window lasts, and
  its id can disappear when it ends.

### OpenCode Go — commented out

Two entries, one per API shape, and both are comments in `settings.yaml` and in
`dsh/profiles/desktop/cordis.patch.yml`:

- `opencode-go` — `https://opencode.ai/zen/go/v1`, `api: openai-completions`:
  DeepSeek V4.1 Flash, GLM-5.3 Flash, Space Bunny Free.
- `opencode-go-responses` — the same base URL, `api: openai-responses`:
  Muse Spark 1.3 Contributor, which only answers on that shape.
- Extra rule: the gateway wants a stable session header,
  `x-opencode-session`; the route sends a fixed value.
- Key: environment variable `OPENCODE_API_KEY`.
- Space Bunny Free is a stealth model too: free for a limited time, and its
  provider keeps a zero-retention policy.

### Models

| Model | Command Code (active) | OpenCode Go (commented out) |
| --- | --- | --- |
| DeepSeek V4.1 Flash | `deepseek/deepseek-v4.1-flash` | `deepseek-v4.1-flash` |
| DeepSeek V4.1 Flash Fast | `deepseek/deepseek-v4.1-flash-fast` | — |
| GLM-5.3 Flash | `z-ai/glm-5.3-flash` | `glm-5.3-flash` |
| Muse Spark 1.3 Contributor | `meta/muse-spark-1.3-contributor` | `muse-spark-1.3-contributor` |
| Space Bunny Alpha / Free | `stealth/space-bunny-alpha` | `space-bunny-free` |

## Disable web_search

One file covers every profile: `~/.dsh/cordis.patch.yml` (the home-level patch
layer). DSH applies it to every profile, and it outranks each profile's own
`cordis.patch.yml`, so there is nothing to change under `profiles/`.

```yaml
- id: tool-web
  config:
    search: false
    fetch: true
- id: web-search-deepseek
  disabled: true
```

- `tool-web` removes the tool where the host row is active, which is the
  `headless` profile.
- `web-search-deepseek` disables the search provider. This is what covers the
  web UI: its sessions compose the model-facing `tool-web` per agent preset, and
  a `tool-web` override cannot reach a preset. No search request leaves the
  machine. `web_search` stays in the model's tool list and returns a structured
  error when called:

```
Error: configured web provider "deepseek-official" is not registered
```

`web_fetch` is not affected.

There is no supported way to patch an agent preset, so removing `web_search`
from a web session would require copying the whole preset. The provider patch
avoids that copy.

## Notes

- The default model is `deepseek-official / deepseek-flash` (the
  `agent-default-model` section), which is the model row the harness brings of
  its own. Change the `provider` and `model` there to make another model the
  default.
- DSH writes the settings you edit in the graphical forms into the patch layer of
  the active profile, which is why `dsh/profiles/desktop/cordis.patch.yml` holds
  the same provider block as `dsh/settings.yaml`. Edit one place and copy it to
  the other, or edit `settings.yaml` only, which every profile reads.
- DSH settings are split by plugin. The model providers live under the
  `llm-pi-ai` section, named after the plugin `@deepseek-ai/dsh-llm-pi-ai`.
- `contextWindow` is metadata for the history compaction and for the display.
  The real limit lives on the server.
- Never commit keys. Keep them in environment variables. DSH also writes a
  `.credentials.yaml` file in its home; it is not part of this repo.

## settings.yaml

```yaml
ui-onboarding:
  welcomeNoticeVersion: 2026-08-13.1
permission:
  defaultPreset: danger-full-access
ui-theme:
  preference: dark
agent-default-model:
  provider: deepseek-official
  model: deepseek-flash
llm-pi-ai:
  providers:
    command-code:
      displayName: Command Code (openai-completions)
      api: openai-completions
      baseURL: https://api.commandcode.ai/provider/v1
      apiKeyEnv: COMMANDCODE_API_KEY
      defaultContextWindow: 1000000
      defaultMaxTokens: 32768
      models:
        - id: deepseek/deepseek-v4.1-flash
          name: DeepSeek V4.1 Flash (Command Code, openai-completions)
          contextWindow: 1000000
          maxTokens: 32768
        - id: deepseek/deepseek-v4.1-flash-fast
          name: DeepSeek V4.1 Flash Fast (Command Code, openai-completions)
          contextWindow: 1000000
          maxTokens: 32768
        - id: z-ai/glm-5.3-flash
          name: GLM-5.3 Flash (Command Code, openai-completions)
          contextWindow: 1048576
          maxTokens: 131072
        - id: meta/muse-spark-1.3-contributor
          name: Muse Spark 1.3 Contributor (Command Code, openai-completions)
          contextWindow: 1048576
          maxTokens: 131072
        - id: stealth/space-bunny-alpha
          name: Space Bunny Alpha (Command Code, openai-completions)
          contextWindow: 1000000
          maxTokens: 131072
    # opencode-go and opencode-go-responses are commented out; see dsh/settings.yaml
    # for the full blocks, which are ready to be uncommented.
```
