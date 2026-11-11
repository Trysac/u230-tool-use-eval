# tool-use-eval

[![PyPI version](https://img.shields.io/pypi/v/trysac-tool-use-eval)](https://pypi.org/project/trysac-tool-use-eval/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-tool-use-eval)](LICENSE)
[![CI](https://github.com/Trysac/u230-tool-use-eval/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u230-tool-use-eval/actions/workflows/ci.yml)

Score function-calling outputs against expected calls: schema checks, acceptable-value sets per argument, order-insensitive parallel calls and per-failure-code summaries.

## Problem

Teams that change a prompt or a model need to know whether it still calls the right functions with the right arguments. Exact string comparison of the emitted JSON fails on harmless differences (argument order, an omitted optional parameter, `'paris'` versus `'Paris'`), while eyeballing predictions does not scale. This library scores each predicted set of calls against a function schema and a list of acceptable values per argument, and reports a typed failure code for each case. It does not execute functions.

## Install

```sh
pip install trysac-tool-use-eval
```

Import name is `tool_use_eval`. Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
from tool_use_eval import Case, ExpectedCall, check_case, evaluate, load_functions, parse_calls

functions = load_functions(
    '[{"name":"get_weather","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}]'
)
actual = '[{"name":"get_weather","arguments":{"city":"paris"}}]'
calls = parse_calls(actual)
expected = [ExpectedCall("get_weather", {"city": ["Paris", "paris"]})]
assert check_case(calls, expected, functions).ok
assert evaluate([Case("c1", actual, expected)], functions).accuracy == 1.0
```

`parse_calls` accepts a JSON array of call objects or a single call object; `arguments` may be an object or a JSON-encoded object string. `ExpectedCall.params` maps each parameter to a list of acceptable values; the empty string `''` in that list allows the parameter to be omitted.

### Command line

```python
from tool_use_eval import main

exit_code = main(["run", "functions.json", "cases.jsonl", "--min-accuracy", "0.75"])
```

`functions.json` is the JSON array of function specs. Each line of `cases.jsonl` is `{"id": ..., "actual": "<JSON text>", "expected": [{"name": ..., "params": {...}}]}`. The CLI prints `accuracy=<3 decimals> correct=<n> total=<n>` followed by one `<code> <count>` line per failure code, sorted by code. It exits `0` when accuracy is at least `--min-accuracy`, `1` when below it, and `2` on usage or IO errors. `--casefold` compares strings after `casefold()` and `strip()`.

### Errors

`load_functions` raises `tool_use_eval.ToolEvalError` with code `'unsupported_schema'` for invalid JSON or unsupported schema shapes. `parse_calls` raises `ToolEvalError` with `'input_too_large'`, `'unparseable'`, `'too_many_calls'`, or `'too_deep'`. The `ToolEvalCode` type also declares `'invalid_case'`, but no function in this module raises it.

Per-case failures are returned in `CaseResult.code`: `'wrong_count'`, `'unknown_function'`, `'missing_required'`, `'unexpected_param'`, `'type_mismatch'`, `'wrong_function'`, and `'value_mismatch'`. Checks run in that order and the first failure wins.

### Public API

- `load_functions(text) -> dict[str, FunctionSpec]` parses a JSON array of objects with `name` and a JSON Schema subset in `parameters`.
- `parse_calls(text, *, max_chars=1_000_000, max_calls=16, max_depth=32) -> list[Call]`.
- `check_case(actual, expected, functions, *, string_mode='exact') -> CaseResult`; `string_mode` is `'exact'` or `'casefold'`.
- `evaluate(cases, functions, *, string_mode='exact') -> Summary`; `Summary` has `total`, `correct`, `accuracy`, and `by_code`. Each case's `actual_text` is parsed with `parse_calls`; parse failures are recorded in `by_code`.
- `main(argv=None) -> int` implements the CLI.
- Data types: `Call`, `ExpectedCall`, `Case(id, actual_text, expected)`, `CaseResult(ok, code, detail)`, `Summary`, `FunctionSpec`, `Parameter`, and `ToolEvalError`.

Limits: `parse_calls` enforces `max_chars`, `max_calls`, and argument nesting depth; `load_functions` supports object parameters with properties/required, scalar properties (`string`, `integer`, `number`, `boolean`), arrays with `items`, objects with `properties`, and non-empty `enum` lists; unsupported schema shapes raise `'unsupported_schema'`. `CaseResult.detail` is at most 200 characters and does not echo argument values. `evaluate` returns `accuracy=0.0` for zero cases.

## Why not the Berkeley Function Calling Leaderboard code

This library keeps the argument-level comparison idea as a small, dependency-free package with typed failure codes that can run in any Python test suite. It does not include the leaderboard's datasets, provider-specific response adapters, execution environment, or reporting stack.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
