# Architecture

## Purpose

`trysac-tool-use-eval` is a single-module, standard-library-only Python package (import name `tool_use_eval`) that scores predicted function calls against declared function schemas and expected calls with per-argument acceptable values. It also provides a small command line interface in `main`.

## Shape

```text
caller code --> tool_use_eval.__init__
                    |
                    +-- load_functions, parse_calls, check_case, evaluate, main
```

- Public API: the names in `__all__` of `src/tool_use_eval/__init__.py`: `Call`, `Case`, `CaseResult`, `ExpectedCall`, `FunctionSpec`, `Parameter`, `Summary`, `ToolEvalError`, `check_case`, `evaluate`, `load_functions`, `main`, and `parse_calls`.
- Errors: parsing and schema failures raise `ToolEvalError` with a stable `code`; per-case failures are returned in `CaseResult.code`; `main` returns an integer exit code.
- Side effects: `load_functions`, `parse_calls`, `check_case`, and `evaluate` do not perform I/O. `main` reads two files and writes to stdout/stderr.
- Matching: `check_case` applies ordered checks and returns the first failure; value matching uses an augmenting-path bipartite assignment, so call order does not matter.

## Quality contract

No test suite or quality-gate script is included in the provided code. The module uses `logging.getLogger(__name__)` with `NullHandler` and has no runtime dependencies outside the Python standard library.

## Decisions

No ADR files are included in the provided materials. The specification records these out-of-scope items: multi-turn conversations, executing functions, relevance detection, executable evaluation, and provider-specific response formats beyond the shape accepted by `parse_calls`.
