# DSH config

My [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH)
setup, to reproduce it fast on another machine.

DSH is a local agent harness with a web UI. It brings no model and no key of its
own. This repo holds my settings file and the steps to add my two model
providers: **OpenCode Go** and **Command Code**. No secret is stored here.

## Files

- `settings.yaml` — my DSH user settings, ready to copy to `~/.dsh/settings.yaml`.
- `README.md` — this guide.

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

## 3. Install the settings

Copy `settings.yaml` to the DSH home folder (default `~/.dsh`, change it with
the `DSH_HOME` variable). Create the folder if it does not exist.

macOS / Linux:

```bash
mkdir -p ~/.dsh
cp settings.yaml ~/.dsh/settings.yaml
```

Windows (PowerShell):

```powershell
New-Item -ItemType Directory -Force "$HOME\.dsh" | Out-Null
Copy-Item settings.yaml "$HOME\.dsh\settings.yaml" -Force
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
- Model `muse-spark-1.3-contributor` only answers on the Responses API, so it
  lives in its own route (`opencode-go-responses`) with `api: openai-responses`.
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

## Notes

- The default model is `opencode-go / deepseek-v4.1-flash` (the
  `agent-default-model` section). Change the `provider` and `model` there to
  make another model the default.
- `contextWindow` is metadata for the history compaction and for the display.
  The real limit lives on the server.
- DSH settings are split by plugin. The model providers live under the
  `llm-pi-ai` section, named after the plugin `@deepseek-ai/dsh-llm-pi-ai`.
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
  provider: opencode-go
  model: deepseek-v4.1-flash
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
