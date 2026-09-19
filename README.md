# dsh-config

My [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH)
setup, to reproduce it fast on another machine.

DSH is a local agent harness with a web UI. It brings no model and no key of its
own. This repo holds my settings and my patch layers. No secret is stored here.

The `dsh/` folder mirrors the DSH home directory (`~/.dsh` by default, or the
`DSH_HOME` variable).

## Contents

- `dsh/settings.yaml` — user settings: the model providers and the default
  model.
- `dsh/cordis.patch.yml` — the machine-local patch layer. DSH applies it to
  every profile and it outranks each profile's own layer. It disables
  `web_search`.
- `dsh/profiles/web/cordis.patch.yml` — per-profile layer, empty.
- `dsh/profiles/headless/cordis.patch.yml` — per-profile layer, empty.

## Before you start

- Node.js 22 or newer.
- An **OpenCode Go** subscription and API key.
- A **Command Code** account and API key.

## 1. Install DeepSeek Harness

```bash
npm install -g @deepseek-ai/dsh
dsh --version
```

A quick look with no install:

```bash
npx @deepseek-ai/dsh web
```

## 2. Set the API keys

The settings file never holds a secret. It only names the environment variables
that hold the keys, so set them once per machine.

macOS / Linux (bash or zsh):

```bash
export OPENCODE_API_KEY="your-open-code-go-key"
export COMMANDCODE_API_KEY="your-command-code-key"
```

Windows (PowerShell, stored for the user):

```powershell
[Environment]::SetEnvironmentVariable('OPENCODE_API_KEY', 'your-open-code-go-key', 'User')
[Environment]::SetEnvironmentVariable('COMMANDCODE_API_KEY', 'your-command-code-key', 'User')
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

```bash
dsh web
```

The web UI listens on `127.0.0.1` and prints a link with a token. The model menu
shows the groups **OpenCode Go**, **OpenCode Go (responses)** and **Command
Code**.

## Providers

### OpenCode Go

- Endpoint: `https://opencode.ai/zen/go/v1` (OpenAI-compatible).
- Extra rule: the gateway wants a stable session header,
  `x-opencode-session`. The route sends a fixed value.
- The model `muse-spark-1.3-contributor` only answers on the Responses API, so
  it lives in its own route (`opencode-go-responses`) with
  `api: openai-responses`.
- Key: environment variable `OPENCODE_API_KEY`.

### Command Code

- Endpoint: `https://api.commandcode.ai/provider/v1` (OpenAI-compatible).
- Muse Spark answers on the normal chat endpoint here, so all three models share
  one route.
- Key: environment variable `COMMANDCODE_API_KEY`.

### Models

| Model | OpenCode Go | Command Code |
| --- | --- | --- |
| DeepSeek V4.1 Flash | `deepseek-v4.1-flash` | `deepseek/deepseek-v4.1-flash` |
| GLM-5.3 Flash | `glm-5.3-flash` | `z-ai/glm-5.3-flash` |
| Muse Spark 1.3 Contributor | `muse-spark-1.3-contributor` | `meta/muse-spark-1.3-contributor` |

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

- The default model is `opencode-go-responses / muse-spark-1.3-contributor`
  (the `agent-default-model` section). Change the `provider` and `model` there
  to make another model the default.
- DSH settings are split by plugin. The model providers live under the
  `llm-pi-ai` section, named after the plugin `@deepseek-ai/dsh-llm-pi-ai`.
- Patch order: bundle layers, then the profile's `cordis.patch.yml`, then the
  home-level `~/.dsh/cordis.patch.yml`, then any `--patch` overlay.
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
  provider: opencode-go-responses
  model: muse-spark-1.3-contributor
llm-pi-ai:
  providers:
    opencode-go:
      displayName: OpenCode Go
      api: openai-completions
      baseURL: https://opencode.ai/zen/go/v1
      apiKeyEnv: OPENCODE_API_KEY
      headers:
        x-opencode-session: ses_dsh_8f2a1c4e7b6d4a90
      defaultContextWindow: 1048576
      defaultMaxTokens: 32768
      models:
        - id: deepseek-v4.1-flash
          name: DeepSeek V4.1 Flash (OpenCode Go)
          contextWindow: 1048576
          maxTokens: 32768
        - id: glm-5.3-flash
          name: GLM-5.3 Flash (OpenCode Go)
          contextWindow: 1000000
          maxTokens: 131072
    opencode-go-responses:
      displayName: OpenCode Go (responses)
      api: openai-responses
      baseURL: https://opencode.ai/zen/go/v1
      apiKeyEnv: OPENCODE_API_KEY
      headers:
        x-opencode-session: ses_dsh_8f2a1c4e7b6d4a90
      defaultContextWindow: 1048576
      defaultMaxTokens: 131072
      models:
        - id: muse-spark-1.3-contributor
          name: Muse Spark 1.3 Contributor (OpenCode Go)
          contextWindow: 1048576
          maxTokens: 131072
    command-code:
      displayName: Command Code
      api: openai-completions
      baseURL: https://api.commandcode.ai/provider/v1
      apiKeyEnv: COMMANDCODE_API_KEY
      defaultContextWindow: 1000000
      defaultMaxTokens: 32768
      models:
        - id: deepseek/deepseek-v4.1-flash
          name: DeepSeek V4.1 Flash (Command Code)
          contextWindow: 1000000
          maxTokens: 32768
        - id: z-ai/glm-5.3-flash
          name: GLM-5.3 Flash (Command Code)
          contextWindow: 1048576
          maxTokens: 131072
        - id: meta/muse-spark-1.3-contributor
          name: Muse Spark 1.3 Contributor (Command Code)
          contextWindow: 1048576
          maxTokens: 131072
```
