# dsh-config

**Deciding which AI subscription deserves the money — with numbers instead of
impressions, and with the question still askable when the answer changes.**

Four steps, and each one is a command:

1. **What a token costs on each plan.** Not the list price: the price after the
   plan's multiplier and the ceiling it puts on that model, per million of input,
   cache read, cache write and output. `plan` prints that table.
2. **What the model can do**, from one source only — Terminal-Bench, which runs
   terminal tasks and grades whether they got done. A model it does not rank is not
   in the conversation.
3. **The frontier of the two**: which models nothing beats on both price and
   capability, and for the rest, which row beats them. `chart` draws it, and the
   picture is published.
4. **How the survivors behave**, measured against the live route: speed, latency,
   prefill, cache in and out of a loop, parallel retention, errors, tool calls, and
   one real bug in a real repository. `measure` and `agentic`.

What comes out is the model menu in `dsh/cordis.patch.yml`, and the reasons behind it
in [`bench/decisions.md`](bench/decisions.md), dated.

A subscription is a **ceiling, not a meter**: the fee is paid whether or not the plan
is used, and past its limit requests stop. So the question is never "what does a
token cost" on its own, but "for the same money, how much of which model do I get".

## The two halves

| Half | Holds | When you touch it |
| --- | --- | --- |
| [`dsh/`](dsh/) | The DSH configuration: one patch file, install notes, the model menu. | When a model is already chosen and has to appear. |
| [`bench/`](bench/) | The benchmark that chooses the models: policy, data, measurement, chart. | When a new model or provider needs judging. |

## Which half do I need?

| I want to… | Read |
| --- | --- |
| Install DSH on a new machine and point it at a provider | [dsh/README.md](dsh/README.md) |
| Add, remove or rename a model in the menu | [dsh/README.md](dsh/README.md) |
| Add a subscription and find out what it is worth | [bench/README.md](bench/README.md) |
| See why a model was dropped | [bench/models-policy.yml](bench/models-policy.yml) for the gates, [bench/models.csv](bench/models.csv) for the numbers |
| See what was decided, and with which numbers | [bench/decisions.md](bench/decisions.md) |
| Ask the four questions again | [bench/README.md](bench/README.md) |

## The picture, and the menu

The frontier is published, and regenerated whenever the data moves:
**https://jacano.github.io/dsh-config/**

Its shape and controls are borrowed from [linearbench](https://linearbench.pages.dev/),
which plots an intelligence index against an estimated cost per task; this plots
Terminal-Bench against the price a plan actually charges, with the multiplier and the
ceiling already inside the number.

The live numbers — what each model costs, what it measures, and whether the menu
matches the policy — come from one command:

```bash
python bench/bench.py measure
```

It prints the admitted rows with their current numbers, and exits non-zero if
anything in the repo disagrees. This file names no prices and no speeds: every one of
those would go stale here.

## License

MIT — see [LICENSE](LICENSE). The prices under `bench/data/plans.json` are facts about
other people's products, read from the pages named under `sources`; the measurements
in `bench/models.csv` are taken here and carry the date they were taken.

