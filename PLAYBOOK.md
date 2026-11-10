# Playbook: judging a new model or a new subscription

The whole point of this repo is that the answer to "should I use this model?"
takes three commands, not an afternoon. This is the runbook.

## The funnel in one picture

```
catalog (97 rows today)
  └─ phase 1  static    capability >= 38.0, cost <= $0.0026/turn, plan access
       └─ 9 rows worth measuring
            └─ phase 2  measured   speed >= 88 tok/s, latency <= 4.8 s, cache works
                 └─ phase 3  fitness   prefill <= 25 ms/1k, cache >= 80%,
                                       retention >= 0.60, errors <= 1/10
                      └─ 4 rows admitted
```

Phase 1 costs no tokens: if capability or price disqualifies a model, it is never
called. Only the survivors are worth measuring.

## A new model on the same provider

1. **Get the id** from `GET /provider/v1/models` (or the model page's
   `cmd --model` line).
2. **Static check, by hand, free.** Capability from Artificial Analysis or the
   catalog; cost per turn from the price. If it fails either, write it into
   `excluded:` in [models-policy.yml](models-policy.yml) with the number that
   killed it and stop. No tokens spent.
3. **Measure phase 2 and 3.**

   ```bash
   python scripts/measure_model.py <model-id>
   python scripts/provider_fitness.py <model-id>
   ```

   Each prints the numbers and whether they clear the gates.
4. **If it clears every gate**, add it in three places: `admitted:` in the
   policy, the `models:` list in `dsh/cordis.patch.yml`, and the tables in the
   README.
5. **Prove it.**

   ```bash
   python scripts/evaluate_gates.py
   python scripts/check_models.py
   ```

   Both must exit 0. `evaluate_gates.py` also fails if an admitted row has no
   fitness data, so a row cannot enter half-measured.

## A new subscription or API

1. Add a provider block to `dsh/cordis.patch.yml`: `api`, `baseURL`,
   `apiKeyEnv`, and the models you want on it.
2. Claude-style APIs need `api: anthropic-messages` and the API root without
   `/v1`; OpenAI-style ones need `api: openai-completions` and the versioned
   path. Check which endpoints a model advertises before choosing.
3. Store the key in `~/.dsh/.credentials.yaml`; never in this repo.
4. Run the same three measurements. `measure_model.py` and
   `provider_fitness.py` take any model id, so a new gateway needs no new code,
   only the right URL and header — which live in the config, not the scripts.
5. If the gateway needs a different header or auth scheme, pass it through the
   config's `headers:` and `apiKeyEnv`, not by editing the scripts.

For route-versus-route comparisons (same model, two gateways), use
[jacano/llm-endpoint-bench](https://github.com/jacano/llm-endpoint-bench): it
measures transport, short and long calls, and concurrency, interleaved. This repo
measures model suitability; that one measures the route.

## Re-baselining

The gates are the envelope of the admitted set. When a new row enters, one of
them may have to move — and that is a decision, made in a commit that names the
number that moved and why. Re-run the full funnel monthly, or whenever a
provider changes something, and record the new round:

- `catalog-YYYY-MM-DD.csv` — a frozen snapshot of prices and scores.
- `measurements-YYYY-MM-DD-runN.csv` — phase 2, one row per model.
- `fitness-YYYY-MM-DD.csv` — phase 3, one row per model.

## What is still missing

- **Tool-call validity**: valid JSON, schema adherence, parallel calls. The
  closest thing to the real agent loop and not measured yet.
- **Transport TTFB** (`llm-endpoint-bench` has it; this repo does not).
- Three runs per model in phase 3, so fitness can be treated like speed instead
  of a single sample.
