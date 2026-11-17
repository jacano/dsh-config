# AGENTS.md — dsh-config

One thing: the DeepSeek Harness configuration. [`dsh/cordis.patch.yml`](dsh/cordis.patch.yml)
names the providers DSH may speak to and the models in its menu; [`README.md`](README.md) is
its manual, and names the sibling repositories.

The one coupling points outward: `model-bench` checks that this menu matches its policy, and
the check reads this file. Changing a model id here is half a change — the other half is
`models-policy.yml` there, or `python bench.py measure` fails.

## Conventions

- **English**, everywhere: code, comments, commits, documentation. Reply to the person in
  their language.
- **Point at the file, do not restate it.** A second copy drifts.
- **A setting without the failure it avoids is a future bug.** Say what breaks.
- **Commits** are Conventional Commits: imperative, lowercase, no trailing period, under 72
  characters (`feat(models): …`).
- **Never commit a key.** Credentials live in `~/.dsh/.credentials.yaml`.
