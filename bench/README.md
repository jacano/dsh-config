# bench — choosing the models

One process, one table. This half decides which models belong in the menu; it
never edits the DSH configuration.

```bash
python bench/evaluate.py                  # the stored table against the gates
python bench/evaluate.py --static         # phase 1 only, over the catalog, free
python bench/evaluate.py --model <id> --capability 42 --cost 0.0024   # live run
```

## The funnel

```
catalog snapshot  ── phase 1  static    capability and price, free
                        └─ survivors  ── phase 2  measured  speed, latency, cache
                             └─ measured ── phase 3  fitness   prefill, cache loop,
                                                              parallelism, errors, tools
                                  └─ admitted
```

The limits are in [`models-policy.yml`](models-policy.yml), not repeated here: they
have moved every time a row entered or left, and a document that quotes them goes
stale the next day. `python bench/evaluate.py` prints them with the live table.

`--model` runs the phases in that order and stops at the first failure, so a model
that cannot pass phase 1 is never called. Every threshold is the envelope of the
admitted rows: a new model has to beat the worst admitted one on every axis, and
nothing enters without a threshold moving on purpose.

`--check` (no argument) also crosses the policy against `dsh/cordis.patch.yml`, so
the menu and the benchmark cannot drift apart.

## Files

| File | What it is |
| --- | --- |
| [`evaluate.py`](evaluate.py) | The whole process: phases, gates, live measurement, config sync. |
| [`models-policy.yml`](models-policy.yml) | Decisions only: the gates, which ids are admitted, and which are excluded with the number that killed them. No per-model metrics — those live in `models.csv`, so this file cannot go stale. |
| [`models.csv`](models.csv) | The only place per-model metrics live: speed, latency, cache, prefill, loop cache, retention, errors, tools. `evaluate.py` prints them from here. |
| [`catalog-2026-11-10.csv`](catalog-2026-11-10.csv) | Frozen snapshot of the priced catalog. Phase 1 runs on this and costs nothing. |
| [`AGENTIC.md`](AGENTIC.md) | Why phase 3 exists and what each gate detects. |
| [`PLAYBOOK.md`](PLAYBOOK.md) | The runbook: new model, new API, re-baselining. |

## One fact, one place

| Fact | Lives in |
| --- | --- |
| Price, catalog capability | `catalog-2026-11-10.csv` |
| Speed, latency, cache, prefill, retention, errors, tools | `models.csv` |
| Gates and the admitted/excluded decision | `models-policy.yml` |
| What the menu actually serves | `dsh/cordis.patch.yml` |

The policy deliberately carries no per-model numbers: an admitted row is an id and
a role. `evaluate.py` joins the decision with the measurements, so the table it
prints is always the latest one. It also fails if an admitted id has no row in
`models.csv`, which is how a stale decision gets caught.

## Adding a model

1. **Static, free.** Get capability (Artificial Analysis or the catalog) and the
   price per turn. If either fails, add the row to `excluded:` in the policy with
   the number that killed it — no tokens spent.
2. **Live run.**

   ```bash
   python bench/evaluate.py --model <id> --capability <score> --cost <usd-per-turn>
   ```

   It prints each phase and a CSV line ready for `models.csv`.
3. **If it clears everything:** add the line to `models.csv`, add the model to
   `admitted:` in the policy, and add it to `dsh/cordis.patch.yml`.
4. **Prove it:** `python bench/evaluate.py` must exit 0.

Details in [PLAYBOOK.md](PLAYBOOK.md).

## Route versus model

This half judges whether a **model** is worth having. For comparing two gateways
serving the same model — transport, short and long calls, concurrency — use
[jacano/llm-endpoint-bench](https://github.com/jacano/llm-endpoint-bench).

## Still open

- Phase 3 is one run per model; speed uses a median of three, fitness does not.
- Transport TTFB lives in the endpoint bench, not here.
- Images and structured output beyond tool calls are not covered.
