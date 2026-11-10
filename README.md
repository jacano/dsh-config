# dsh-config

Two halves, one repo: the configuration, and the benchmark that decides what goes
in it.

| Half | Holds | When you touch it |
| --- | --- | --- |
| [`dsh/`](dsh/) | The DSH configuration: one patch file, install notes, the model menu. | When a model is already chosen and has to appear. |
| [`bench/`](bench/) | The benchmark that chooses the models: policy, data, one process. | When a new model or provider needs judging. |

## Which half do I need?

| I want to… | Read |
| --- | --- |
| Install DSH on a new machine and point it at Command Code | [dsh/README.md](dsh/README.md) |
| Add, remove or rename a model in the menu | [dsh/README.md](dsh/README.md) |
| Judge a new model, or a new subscription | [bench/README.md](bench/README.md) |
| See why a model was dropped | [bench/models-policy.yml](bench/models-policy.yml) |
| Repeat the whole selection from scratch | [bench/PLAYBOOK.md](bench/PLAYBOOK.md) |

## The menu today

Which models are admitted is decided in one place,
[`bench/models-policy.yml`](bench/models-policy.yml); what the harness actually
loads is [`dsh/cordis.patch.yml`](dsh/cordis.patch.yml). This file names neither
the rows nor their numbers, because both would go stale here.

For the live picture — who is in, what it measures, and whether the menu matches
the policy — run:

```bash
python bench/evaluate.py
```

That command prints the four admitted rows with their current numbers, and exits
non-zero if anything in the repo disagrees.
