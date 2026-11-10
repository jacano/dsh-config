# dsh-config

Two halves, one repo:

| Half | What it holds | When you touch it |
| --- | --- | --- |
| [`dsh/`](dsh/) | The DSH configuration: one patch file, install notes, the model menu. | When a model is already chosen and has to appear. |
| [`bench/`](bench/) | The benchmark that chooses the models: policy, data, scripts, records. | When a new model or provider needs judging. |

## Which half do I need?

| I want to… | Read |
| --- | --- |
| Install DSH on a new machine and point it at Command Code | [dsh/README.md](dsh/README.md) |
| Add, remove or rename a model in the menu | [dsh/README.md](dsh/README.md) |
| Judge a new model, or a new subscription | [bench/README.md](bench/README.md) |
| See why a model was dropped | [bench/AGENTIC.md](bench/AGENTIC.md) |
| Repeat the whole selection from scratch | [bench/PLAYBOOK.md](bench/PLAYBOOK.md) |

## The menu today

Four rows, all clearing three phases — capability and price from the catalog,
speed and latency on the wire, and provider fitness on the route:

| Model | Role | tok/s | Prefill | $/turn |
| --- | --- | ---: | ---: | ---: |
| DeepSeek V4.1 Flash Fast | default | 113 | 19.1 ms/1k | $0.0025 |
| Claude Haiku 5.5 | fastest, cheapest | 146 | 22.7 ms/1k | $0.0017 |
| MiniMax M3.1 Flash | spare on the same route | 107 | 23.1 ms/1k | $0.0024 |
| GPT-6 Luna | long-context reader | 89 | **1.6 ms/1k** | $0.0017 |

The numbers and the gates behind them are in [bench/](bench/); the file that
makes them real is [`dsh/cordis.patch.yml`](dsh/cordis.patch.yml).

