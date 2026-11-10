# bench — choosing the models

This half of the repo decides **which models go in the menu**. It holds the
policy, the measurements, the scripts that produce them, and the records.

It never edits the DSH configuration. When a model wins here, it is added to
[`../dsh/cordis.patch.yml`](../dsh/cordis.patch.yml) in a separate change.

## The funnel

```
catalog snapshot (97 priced rows)
  └─ phase 1  static     capability >= 38.0, cost <= $0.0026/turn, plan access
       └─ 9 rows worth measuring — the rest never cost a token
            └─ phase 2  measured   speed >= 88 tok/s, latency <= 4.8 s, cache works
                 └─ phase 3  fitness   prefill <= 25 ms/1k, cache >= 80%,
                                       retention >= 0.60, errors <= 1/10,
                                       tool calls valid >= 90%
                      └─ 4 rows admitted
```

Every threshold is the envelope of the admitted rows: a new model has to beat the
worst admitted one on every axis. Nothing enters without a threshold moving on
purpose, in a commit that names the number.

## Files

| File | What it is |
| --- | --- |
| [`models-policy.yml`](models-policy.yml) | The gates, the admitted rows, the excluded rows with the number that killed each. Source of truth. |
| [`catalog-2026-11-10.csv`](catalog-2026-11-10.csv) | Frozen snapshot of the 97 priced models: price, cache, capability. Phase 1 runs on this and costs nothing. |
| [`measurements-2026-11-10.csv`](measurements-2026-11-10.csv) | Phase 2, run 1. `-run2` and `-run3` are the later rounds, kept because the variance is the lesson. |
| [`fitness-2026-11-10.csv`](fitness-2026-11-10.csv) | Phase 3: prefill slope, cache in a loop, parallel retention, error budget, tool-call validity. |
| [`AGENTIC.md`](AGENTIC.md) | Why phase 3 exists, what each gate detects, and the numbers. |
| [`MODELS.md`](MODELS.md) | Per-call ranking and the history of what was dropped. |
| [`PLAYBOOK.md`](PLAYBOOK.md) | The runbook: new model, new API, re-baselining. |

## Scripts

```bash
python bench/scripts/evaluate_gates.py     # all three phases, both directions
python bench/scripts/check_models.py       # policy and dsh/cordis.patch.yml agree
python bench/scripts/measure_model.py <id>        # phase 2 for one model
python bench/scripts/provider_fitness.py <id>     # phase 3 for one model
python bench/scripts/provider_fitness.py --tools <id>...   # only tool calls
```

`evaluate_gates.py` exits 1 if an admitted row misses a gate **or has no fitness
data**, and if a measured row outside the menu clears everything. That is what
"nothing new enters" means mechanically.

`check_models.py` crosses the policy against the DSH patch file, so the menu and
the benchmark cannot drift apart.

## Adding a model

1. Static check by hand — capability and price, no tokens spent. If it fails, add
   it to `excluded:` with the number that killed it.
2. `measure_model.py <id>` — speed, warm latency, cache.
3. `provider_fitness.py <id>` — prefill, cache loop, concurrency, errors, tools.
4. If it clears everything: `admitted:` here, the `models:` list in `../dsh/`,
   and the tables in the README.
5. `evaluate_gates.py && check_models.py` — both must exit 0.

Full details in [PLAYBOOK.md](PLAYBOOK.md).

## Route versus model

This half judges whether a **model** is worth having. For comparing two gateways
serving the same model — transport, short and long calls, concurrency — use
[jacano/llm-endpoint-bench](https://github.com/jacano/llm-endpoint-bench). The
transport phase lives there, not here.

## Still open

- Phase 3 is one run per model. Speed got three runs and a median; fitness has
  not, yet.
- Transport TTFB is not measured here (it is in the endpoint bench).
- Image input, structured output beyond tools, and very long context are not
  covered.
