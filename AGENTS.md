# AGENTS.md — dsh-config

Working notes for an agent that lands in this repository. Read this first.

## What this repo is

One thing: the DeepSeek Harness configuration. `dsh/cordis.patch.yml` is the file every
profile reads — the providers DSH may speak to and the models in the menu — and
[`dsh/README.md`](dsh/README.md) is its manual. There is no benchmark, no measurement and
no chart here.

| Repository | Holds |
| --- | --- |
| **dsh-config** (here) | The configuration that comes out: providers, the model menu, install notes. |
| [`model-bench`](https://github.com/jacano/model-bench) | The benchmark that chooses it: prices, Terminal-Bench, the gates, the frontier, the published page. |
| [`agent-skills`](https://github.com/jacano/agent-skills) | Procedures an agent follows, with the code they need. |

## The one coupling, and it points outward

The menu here is expected to match `models-policy.yml` in `model-bench`. That repository
checks it, and the check reads this file from a sibling clone:

```bash
# in a model-bench clone, beside a clone of this repository
python bench.py measure
```

It exits non-zero when the menu and the policy disagree. So: **changing a model id here
is half a change** — the other half is the policy and the measured row in `model-bench`,
or `measure` fails there. Do not add a copy of those numbers to this repository; a price
copied into a config file goes stale, and this repository cannot know when.

## Conventions

- **English.** Code, comments, commits and documentation here are written in English.
  Reply to the person in whatever language they are using.
- **Explain the why.** A setting without the failure it avoids is a future bug. The notes
  in [`dsh/README.md`](dsh/README.md) are the model for the tone: state what was measured,
  when, and what was not.
- **Do not restate a list that lives in a file.** Point at the file. A second copy drifts.
- **`cordis.patch.yml` is hot-reloaded.** Saving a valid edit recomposes the running
  profile; an unparsable one is rejected and the last good composition keeps running.
  Startup-only templates (`headless`, `acp`, SDK, anything with `patchReload: startup`)
  take the layer only at boot.
- **Commits** are Conventional Commits, imperative, lowercase, no trailing period, under
  72 characters: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `revert:`, optionally
  scoped — `feat(models): …`.
- **Never commit a key.** Credentials live in `~/.dsh/.credentials.yaml`, outside this
  repo, and `.gitignore` refuses the file.
