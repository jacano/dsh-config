# dsh-config

My [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH)
setup: **one file**, to reproduce it fast on another machine.

## What DSH is

DSH is a **local** agent harness. It runs on your machine, keeps your sessions,
your workspace and your credentials there, and it brings no model and no key of
its own: you point it at a provider with your own key. Nothing to sign up to —
something to install, configure once, and then use from a browser tab or from a
window on the desktop.

This repo is that configuration and nothing else. No secret is stored here.

## Two flavours, one configuration

DSH ships the same harness with two front ends, and each one is a *profile*:

- **The web build** — `npm install -g @deepseek-ai/dsh`, then `dsh web`, which is
  an alias of `--profile web`. It serves the UI on `127.0.0.1` and prints a link
  with a token. `npx @deepseek-ai/dsh web` runs it with no install. This is the
  flavour that needs Node.js.
- **The desktop apps** — an installer per platform, from the table below, which
  works in `--profile desktop`. The app is a shell around the same web app bundle
  (the profile carries `@deepseek-ai/dsh-web-app`), so the window runs what
  `dsh web` serves, and it brings its own runtime: no Node.js needed.

**Both read the same home directory, `~/.dsh`.** The model menu, the permissions,
the theme and the default model are the same for the two, and because the whole
configuration lives in the home-level patch layer, that is a property of the
design and not a promise: no profile can drift from another.

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

## The one file

- `dsh/cordis.patch.yml` → `~/.dsh/cordis.patch.yml`. It holds every setting
  this setup has: the model providers and their models, the default model, the
  permission presets, the theme and the client toggles.

Why the home level and not the profile's own layer: DSH composes a profile from
its bundles, then `profiles/<name>/cordis.patch.yml` (that profile only), then
`~/.dsh/cordis.patch.yml` (every profile, and it wins), then any `--patch`
overlay. The web build and the desktop app are two different profiles, so the
home-level file is the only place where one edit configures both.

The file is a YAML array of loader patch entries: `id` names the entry to
configure, `name` the plugin behind it, and the value under `config` replaces
that entry's config. A block commented out is a provider that is out of the menu
and one `# ` away from coming back.

There is no `settings.yaml` in this repo, and that is deliberate. DSH used to
keep the user settings in `~/.dsh/settings.yaml`; it now writes them into the
patch layer and renames the old file to `settings.yaml.imported` on the first
write (the app documents this). A `settings.yaml` is a leftover of that
migration, not a place DSH reads, so keeping one here would only invite edits
that do nothing. If your home still holds a `settings.yaml.imported`, it is that
leftover and you can ignore it.

The profile's own `cordis.patch.yml` is unused here, and DSH treats a missing one
as "no layer". Note what this means when you edit settings **inside the app**: the
graphical forms write to the profile layer, which sits *below* this file, so a
form edit is shadowed by what this file sets. Edit this file by hand, or remove
the entry here if you would rather drive that setting from the app.

## Before you start

- Node.js 22 or newer, for the web flavour. The desktop installers need none.
- A **Command Code** account and API key: the only provider that is active here.
- An **OpenCode Go** subscription and API key, only if you want to re-enable the
  OpenCode entries, which are commented out.

## 1. Install DeepSeek Harness

Web flavour:

```bash
npm install -g @deepseek-ai/dsh
dsh --version
```

Desktop flavour: run the installer of your platform from the **Download** table
above.

## 2. Set the API keys

The configuration never holds a secret. It only names the environment variables
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

One file, into the DSH home.

macOS / Linux:

```bash
mkdir -p ~/.dsh
cp dsh/cordis.patch.yml ~/.dsh/cordis.patch.yml
```

Windows (PowerShell):

```powershell
New-Item -ItemType Directory -Force "$HOME\.dsh" | Out-Null
Copy-Item "dsh\cordis.patch.yml" "$HOME\.dsh\cordis.patch.yml" -Force
```

## 4. Run

Web flavour:

```bash
dsh web
```

Desktop flavour: start the app.

Either way the model menu shows one group, **Command Code**, with five models.
The OpenCode groups are commented out in the file, so they are not in the menu
until you remove the `# ` from their blocks.

To see what DSH composes from the file before you start a session:

```bash
dsh --profile web --dump-config | less
```

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

Two entries, one per API shape, both commented out in the file:

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

## Notes

- The default model is `deepseek-official / deepseek-flash`, the row the harness
  brings of its own. Change `provider` and `model` in the `agent-default-model`
  entry to make another model the default.
- Web search is left as the harness ships it: no entry in the file touches it.
- The compositions of the `web` and `headless` profiles log one warning,
  `patch: entry "ui-settings-account" not found`, because that plugin belongs to
  the desktop app's client bundle. The desktop profile has it, the others skip
  the entry, and nothing else is affected.
- DSH settings are split by plugin, and `id` is the key: the model providers live
  in the `llm-pi-ai` entry, named after the plugin `@deepseek-ai/dsh-llm-pi-ai`.
- `contextWindow` is metadata for the history compaction and for the display.
  The real limit lives on the server.
- Never commit keys. Keep them in environment variables. DSH also writes a
  `.credentials.yaml` file in its home; it is not part of this repo, and
  `.gitignore` here refuses it.
