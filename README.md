# dsh-config

My [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH)
setup: **one file**, to reproduce it on another machine.

## What DSH is

A local agent harness. It runs on your machine, keeps your sessions and your
credentials there, and brings no model and no key of its own: you point it at a
provider with your own key. This repo is that configuration and nothing else, and
no secret lives here.

## Two flavours, one configuration

DSH ships the same harness with two front ends, one profile each:

- **Web** — `npm install -g @deepseek-ai/dsh`, then `dsh web` (an alias of
  `--profile web`). Serves the UI on `127.0.0.1`. Needs Node.js 22 or newer.
- **Desktop** — the installers below, profile `desktop`. A shell around the same
  web app bundle, with its own runtime: no Node.js.

Both read the same `~/.dsh`, and the whole configuration lives in the home-level
patch layer, which every profile reads and which outranks a profile's own layer.
So one file configures the two, by construction and not by discipline.

| Flavour | Build | Get it |
| --- | --- | --- |
| Web | any platform with Node.js 22+ | `npm install -g @deepseek-ai/dsh` |
| Desktop | Windows x64 | [deepseek-harness-0.1.7-rc.1.20260924.1-win-x64.exe](https://download.deepseek.com/dsh-desk/bin/win-x64/deepseek-harness-0.1.7-rc.1.20260924.1-win-x64.exe) |
| Desktop | macOS Apple Silicon | [deepseek-harness-0.1.7-rc.1.20260924.1-mac-arm64.dmg](https://download.deepseek.com/dsh-desk/bin/mac-arm64/deepseek-harness-0.1.7-rc.1.20260924.1-mac-arm64.dmg) |

Those two desktop builds are the only ones published for that release.

## The one file

`dsh/cordis.patch.yml` → `~/.dsh/cordis.patch.yml`. It holds everything: the
providers and their models, the default model, the permission presets, the theme
and the client toggles.

It is a YAML array of loader patch entries: `id` names the entry, `name` the
plugin behind it, and `config` replaces that entry's config. A block commented
out is a provider that is out of the model menu, one `# ` away from coming back.

Two things worth knowing about the layering:

- DSH gives every profile a layer of its own and reads a home-level one after it,
  which wins. The configuration lives in that home-level file, which is why one
  file covers both flavours and why no profile can drift from another.
- The harness writes the settings you edit in its own forms into the profile
  layer, which sits below this file, so a form edit is shadowed. Edit this file,
  or drop the entry here if you would rather drive that setting from the app.

## Setup

**1. Install** — the npm line or the installer of the table above.

**2. Set the key**, once per machine:

```bash
export COMMANDCODE_API_KEY="your-command-code-key"
```

```powershell
[Environment]::SetEnvironmentVariable('COMMANDCODE_API_KEY', 'your-command-code-key', 'User')
```

Add `OPENCODE_API_KEY` as well only if you uncomment the OpenCode blocks. Open a
new terminal afterwards: a running process does not see a new variable.

**3. Restore the file:**

```bash
mkdir -p ~/.dsh && cp dsh/cordis.patch.yml ~/.dsh/
```

```powershell
New-Item -ItemType Directory -Force "$HOME\.dsh" | Out-Null
Copy-Item "dsh\cordis.patch.yml" "$HOME\.dsh\" -Force
```

**4. Run** `dsh web`, or start the desktop app. The model menu shows one group,
**Command Code**, with five models. `dsh --profile web --dump-config` prints what
DSH composes from the file, which is the way to check it by hand.

## Providers and models

Every name in the menu carries the wire it speaks, `openai-completions` for
`POST /chat/completions` or `openai-responses` for `POST /responses`.

**Command Code, active** — `https://api.commandcode.ai/provider/v1`,
`openai-completions`, key `COMMANDCODE_API_KEY`:

| Model | Id on the wire |
| --- | --- |
| DeepSeek V4.1 Flash | `deepseek/deepseek-v4.1-flash` |
| DeepSeek V4.1 Flash Fast | `deepseek/deepseek-v4.1-flash-fast` |
| GLM-5.3 Flash | `z-ai/glm-5.3-flash` |
| Muse Spark 1.3 Contributor | `meta/muse-spark-1.3-contributor` |
| Space Bunny Alpha | `stealth/space-bunny-alpha` |

Space Bunny Alpha and the OpenCode Free models are stealth releases: free while
their test window lasts, and their ids can disappear when it ends.

**OpenCode Go, commented out** — two entries of one service on
`https://opencode.ai/zen/go/v1`, key `OPENCODE_API_KEY`: `opencode-go`
(`openai-completions`) and `opencode-go-responses` (`openai-responses`), the
second one because Muse Spark only answers on that shape. Its blocks in the file
name the models.

## Notes

- The default model is `deepseek-official / deepseek-flash`, the row the harness
  brings of its own. Change the `agent-default-model` entry for another one.
- The `web` and `headless` compositions log one warning,
  `entry "ui-settings-account" not found`: that plugin belongs to the desktop
  client bundle. Harmless.
- Never commit keys. DSH writes a `.credentials.yaml` in its home, and the
  `.gitignore` here refuses it.
