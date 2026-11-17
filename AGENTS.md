# AGENTS.md — dsh-config

Working notes for an agent that lands in this repository. Read this first.

## What this repo is

Two halves, and they are separate jobs:

| Half | Holds | Touch it when |
| --- | --- | --- |
| [`dsh/`](dsh/) | The DSH configuration: providers, models, install notes. | A model is already chosen and has to appear. |
| [`bench/`](bench/) | The benchmark that chooses the models: policy, data, measurement, chart. | A model or a subscription needs judging. |

[`skills/`](skills/) holds agent-facing procedures that need code to be useful.

The checks are `python bench/bench.py measure` (prints the admitted rows and exits
non-zero when the repo disagrees with itself) and `python bench/bench.py chart` for the
published picture.

## When the person asks you to use *their* Chrome

That is [`skills/chrome-cdp/SKILL.md`](skills/chrome-cdp/SKILL.md). Read it before you
type anything; the failure mode is silent and costs them a click. The short version:

```bash
node skills/chrome-cdp/cdp.mjs start     # attach once, idempotent
node skills/chrome-cdp/cdp.mjs eval --url example.com "document.title"
```

- Their Chrome is the one with their session. That is the point: it reads the pages that
  need a login, and sites do not challenge it the way they challenge a fresh browser.
- **Chrome grants remote debugging to one external client per armed session.** One
  long-lived daemon owns the socket. Never open, work and close; never retry in a loop.
- `refused` means no DevTools server on those ports (Chrome closed, or the box
  unchecked). `hung` means the grant is spent: they uncheck **and re-check** *Allow
  remote debugging for this browser instance* in `chrome://inspect/#remote-debugging`,
  once, and you start the daemon again. Do not present that as their mistake.
- Do not kill Chrome, do not launch a second Chrome on their profile, do not close the
  daemon "to tidy up". Open tabs in the background and close the ones you created.
- Reading is fine on your own. Clicking something that spends money, sends a message or
  deletes data is theirs to approve.

## Conventions

- **English.** Code, comments, commits and documentation here are written in English.
  Reply to the person in whatever language they are using.
- **Explain the why.** A number without its date and its method, or a workaround without
  the failure it avoids, is a future bug. The existing notes are the model for the tone:
  state what was measured, when, and what was not.
- **Do not restate a list that lives in a file.** Point at the file. A second copy drifts.
- **Commits** are Conventional Commits, imperative, lowercase, no trailing period, under
  72 characters: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `revert:`, optionally
  scoped — `feat(chart): …`.
- **Never commit a key.** Credentials live in `~/.dsh/.credentials.yaml`, outside this
  repo, and `.gitignore` refuses the file.
