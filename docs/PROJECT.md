# Project record

## Objective

Score function-calling outputs against expected calls: schema checks, acceptable-value sets per argument, order-insensitive parallel calls and per-failure-code summaries.

## Scope

In scope:

- Parse a JSON array of function specifications into `FunctionSpec` objects using the supported JSON Schema subset.
- Parse predicted calls from a JSON array or a single call object, with limits on input size, call count, and argument nesting depth.
- Check actual calls against expected calls and declared function schemas, returning `CaseResult` with a first-failure code and bounded detail.
- Evaluate many cases with `evaluate`, producing `Summary(total, correct, accuracy, by_code)`.
- Provide the `main` command line interface for `run <functions.json> <cases.jsonl> [--min-accuracy 0.0] [--casefold]`.

Out of scope:

- Multi-turn conversations.
- Executing predicted functions.
- Relevance detection.
- Executable evaluation.
- Provider-specific response formats beyond the call shape accepted by `parse_calls`.

## Timeline

No dated events are recorded in the provided materials.

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 1877790 / 102241 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.1208 |

## Factory run u230 (measured from API usage)

| Date (UTC) | Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| 2026-11-11 | generation | deepseek-v4-pro | yes | 1891 | 18631 | 0 | 3328 | 0.0382 |
| 2026-11-11 | fix-1 | deepseek-flash | no | 32216 | 19832 | 0 | 608000 | 0.0186 |
| 2026-11-11 | fix-2 | deepseek-flash | no | 13553 | 4607 | 0 | 43008 | 0.0049 |
| 2026-11-11 | audit | deepseek-flash | no | 35429 | 25094 | 0 | 457216 | 0.0217 |
| 2026-11-11 | fix-3 | deepseek-flash | no | 31682 | 18646 | 0 | 581632 | 0.0177 |
| 2026-11-11 | docs | deepseek-flash | no | 69579 | 15431 | 0 | 256 | 0.0197 |

Total: $0.1208. Prices: deepseek line, as measured by its adapter. Providers serve the current version of each model id, so the date tells which version answered; versions, launch stages and price sources per line are in the factory's model register (docs/MODELS.md).
