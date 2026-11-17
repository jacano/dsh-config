# dsh-config

My [DeepSeek Harness](https://github.com/deepseek-ai) configuration: one file, naming the
providers it may speak to and the models in its menu.

| Repository | Holds |
| --- | --- |
| **dsh-config** (here) | The configuration: providers and the model menu. |
| [model-bench](https://github.com/jacano/model-bench) | The benchmark that chose the menu, and the page it publishes. |
| [agent-skills](https://github.com/jacano/agent-skills) | Procedures an agent follows, with the code they need. |

## Install

| Flavour | Platform | Get it |
| --- | --- | --- |
| Desktop | Windows x64 | [deepseek-harness-0.2.0-rc.2-win-x64.exe](https://download.deepseek.com/dsh-desk/bin/win-x64/deepseek-harness-0.2.0-rc.2-win-x64.exe) |
| Desktop | macOS Apple Silicon | [deepseek-harness-0.2.0-rc.2-mac-arm64.zip](https://download.deepseek.com/dsh-desk/bin/mac-arm64/deepseek-harness-0.2.0-rc.2-mac-arm64.zip) |
| Desktop | macOS Intel | [deepseek-harness-0.2.0-rc.2-mac-x64.zip](https://download.deepseek.com/dsh-desk/bin/mac-x64/deepseek-harness-0.2.0-rc.2-mac-x64.zip) |
| Web | any | `npm install -g @deepseek-ai/dsh`, then `dsh web` |

Release-candidate builds: a later one can change the configuration format.

## Use

1. **Keys** go in `~/.dsh/.credentials.yaml`, under the reference each provider block names
   in `apiKeyEnv`. Settings → Models writes that file. On macOS and Linux, `chmod 600` it.
2. **The file:** `cp dsh/cordis.patch.yml ~/.dsh/` (or the PowerShell equivalent).
3. **Start** the app, or `dsh web`. The menu shows one group per provider block.

## The file

`dsh/cordis.patch.yml` → `~/.dsh/cordis.patch.yml`. A YAML array of loader patch entries:
`id` names the row, `name` the plugin, `config` replaces that row's config whole. Every
profile reads it, and it outranks the profile's own layer.

Six rules worth knowing before editing it:

- **Hot-reloaded.** Saving a valid edit recomposes the running profile; an invalid one is
  rejected and the last good composition keeps running. `headless`, `acp` and the SDK
  templates read it at boot only.
- **`name` must match its row.** A mismatch is skipped with a warning. Bundles reuse ids —
  `llm-deepseek` is `dsh-llm-deepseek-api-key` on the desktop and `dsh-llm-deepseek` from
  npm — so rows whose plugin moved carry no `name` and match by id.
- **This file outranks Settings.** A preference pinned here shadows the form below it.
- **Images** are declared once, `defaultInput: [text, image]`. A text-only model added later
  needs `input: [text]`, or its images arrive as `(image omitted…)`.
- **`api:`** is one of `openai-completions`, `openai-responses` or `anthropic-messages`, and
  it is the block's business, not the model's. A `claude-*` id that earns a 400 on the
  OpenAI shape wants `anthropic-messages`.
- **Never commit a key.** `.gitignore` refuses the file.

What each row costs and measured, and why the menu holds what it holds, is in
[model-bench](https://github.com/jacano/model-bench). Nothing here repeats those numbers: a
price copied into a configuration file goes stale, and this file cannot know when.

## License

MIT — see [LICENSE](LICENSE).
