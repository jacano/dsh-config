# dsh-config

My [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH)
setup, to reproduce it fast on another machine.

DSH is a local agent harness with a web UI. It brings no model and no key of its
own. This repo holds my settings, my profile patches, and one custom agent
preset that turns off `web_search`. No secret is stored here.

The `dsh/` folder mirrors the DSH home directory (`~/.dsh` by default, or the
`DSH_HOME` variable).

## Contents

- `dsh/settings.yaml` — user settings: the model providers and the default
  model.
- `dsh/profiles/web/cordis.patch.yml` — web profile patch layer (host plane).
- `dsh/profiles/headless/cordis.patch.yml` — headless profile patch layer. It
  disables `web_search`.
- `dsh/.agent-presets/standard-nosearch/` — a custom agent preset, a copy of
  the built-in Standard with `web_search` disabled. It is the default for the
  web UI.

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

There are two planes, and each one has its own switch.

### Web sessions (the web UI)

The web app disables the host `tool-web` row and composes the model-facing web
tools **per agent preset**. So the profile patch alone does not change a web
session. The switch is an agent preset.

I keep a custom preset, `standard-nosearch`: a copy of the built-in **Standard**
preset with the `tool-web` config set to `search: false, fetch: true`:

```yaml
- id: tool-web
  name: '@deepseek-ai/dsh-tool-web'
  config:
    search: false
    fetch: true
```

It is the default through this setting in `settings.yaml`:

```yaml
agent-presets:
  default: standard-nosearch
```

To make your own: copy the built-in Standard preset directory to
`~/.dsh/.agent-presets/<your-id>/`, edit the `tool-web` config, and set
`agent-presets.default` to `<your-id>`. Use a **new id**: a built-in preset
wins a duplicate id, so a copy under the same name is ignored.

### Host and headless plane

The `headless` profile mounts the host `tool-web` row, so the profile patch is
the switch there. `dsh/profiles/headless/cordis.patch.yml`:

```yaml
- id: tool-web
  config:
    search: false
    fetch: true
```

In the web profile the host row is disabled by `dsh-web-app`, so the same entry
in `dsh/profiles/web/cordis.patch.yml` covers only the host plane. The preset
does the work for web sessions.

## Notes

- The default model is `opencode-go-responses / muse-spark-1.3-contributor`
  (the `agent-default-model` section). Change the `provider` and `model` there
  to make another model the default.
- DSH settings are split by plugin. The model providers live under the
  `llm-pi-ai` section, named after the plugin `@deepseek-ai/dsh-llm-pi-ai`.
  The default preset lives under the `agent-presets` section.
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
agent-presets:
  default: standard-nosearch
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
