# dsh — the DSH configuration

This half of the repo is only the configuration: which providers DeepSeek Harness
may speak to, and which models appear in the menu. It carries no
benchmark, no measurements and no history — that is [`../bench/`](../bench/).

## Install

| Flavour | Platform | Get it |
| --- | --- | --- |
| Desktop | Windows x64 | [deepseek-harness-0.2.0-rc.2-win-x64.exe](https://download.deepseek.com/dsh-desk/bin/win-x64/deepseek-harness-0.2.0-rc.2-win-x64.exe) |
| Desktop | macOS Apple Silicon | [deepseek-harness-0.2.0-rc.2-mac-arm64.zip](https://download.deepseek.com/dsh-desk/bin/mac-arm64/deepseek-harness-0.2.0-rc.2-mac-arm64.zip) |
| Desktop | macOS Intel | [deepseek-harness-0.2.0-rc.2-mac-x64.zip](https://download.deepseek.com/dsh-desk/bin/mac-x64/deepseek-harness-0.2.0-rc.2-mac-x64.zip) |
| Web | any platform | `npm install -g @deepseek-ai/dsh`, then `dsh web` |

These are release-candidate builds. A later build can change the configuration
format, so re-read this file when the app moves on.

## Setup

Install from the table, then:

**1. Set the key**, once per machine. Settings → Models takes it under the group
that needs it and stores it in `~/.dsh/.credentials.yaml`, resolved per request, so
nothing needs a restart. The reference each group uses is its block's `apiKeyEnv`.

By hand, that file is:

```yaml
version: 1
refs:
  <THE_REF_THAT_BLOCK_NAMES>: "your-key"
```

The name on the left is whatever that provider's block puts in `apiKeyEnv`; the
groups are the providers, so the reference follows the block, not the other way.

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

**3. Run** the desktop app — or `dsh web` if you took the web line. The menu shows
one group per provider block in the config, and nothing else. What is in it, what it
costs and what it measured is printed by

```bash
python bench/bench.py measure
```

which also exits non-zero when the menu and the policy disagree. This file does not
repeat that list, or its prices, or its speeds: every one of those goes stale the
moment a subscription lapses, and this page cannot know that.

The group name says which models are behind it; the protocol lives in each node's
`api:` field, where it belongs.

## The one file

`dsh/cordis.patch.yml` → `~/.dsh/cordis.patch.yml`. Every profile reads it and it
outranks the profile's own layer, so one file covers both flavours.

It is a YAML array of loader patch entries: `id` names the row, `name` the plugin,
`config` replaces that row's config whole. The active part carries one line per model
and no comment on purpose — it is configuration, and everything that needs explaining
is in this README. Paused providers are the one exception: they sit commented at the
end of the file, verbatim, so restoring one is uncommenting it.

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

A route is one block under `providers:` in [`cordis.patch.yml`](cordis.patch.yml):
an `api`, a `baseURL`, the `apiKeyEnv` that resolves through the credential store,
and a `models:` list. The file is the list; this one does not repeat it, because a
second copy drifts from the first and `python bench/bench.py measure` prints the
current one with its numbers whenever you want to see it.

Two protocols cover everything here. `openai-completions` is the default shape.
`anthropic-messages` is for a gateway that only accepts the Anthropic one, and it
names the API root rather than a versioned path because pi-ai appends
`/v1/messages` itself. A `claude-*` id that earns a 400 on the OpenAI shape wants
that second route: the block's `api` is where to look, not the model.

A block may sit in the menu and not in the benchmark: that is an exception, kept
because it is the only route of its kind and named as one where it was added.
`measure` governs only the rows it has measured, so an exception neither passes nor
fails a gate - it is simply not judged.

Which route is the default is `agent-default-model`'s `config`. It should name the
subscription that is being paid for this month, which is a fact the file cannot
know: read the line, not the prose around it.

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
- **Retries.** Both `openai-completions` blocks carry a `retryPolicy` whose
  `retryableCodes` adds `MALFORMED_RESPONSE` to the five defaults. The hosted
  gateways intermittently give the first two parallel tool calls the same
  `tool_calls[].index`, so their argument strings arrive concatenated
  (`{"…"}{"…"}`); pi-ai reports that as `MALFORMED_RESPONSE` before any tool runs,
  and the default policy does not retry it, so the turn dies instead of asking
  again. The defect is server-side — the duplicate index is already in the opening
  SSE deltas, reproduced from a plain `urllib` client with no DSH in the path — and
  is tracked in [nexu-io/open-design#9369](https://github.com/nexu-io/open-design/issues/9369).
  More parallel calls in one turn make it likelier, which is why the retry is worth
  three attempts; drop the policy once the gateway is fixed.
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
