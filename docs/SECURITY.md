# Security notes

## Threat model

### Defended

- Predicted-call text passed to `parse_calls` is limited to 1,000,000 characters, 16 calls, and argument nesting depth 32 by default. Over-deep JSON is detected iteratively (`_check_depth` and `_text_nesting_depth`) so the check itself does not rely on Python recursion.
- Function schemas passed to `load_functions` are restricted to a JSON Schema subset. Unsupported types or shapes raise `ToolEvalError('unsupported_schema')`; schema parameter nesting is capped at 32. No `eval`, `exec`, or executable deserialization is used.
- Numeric comparisons reject `NaN` and infinities, and booleans are never treated as integers or numbers. String comparison uses `casefold()` and `strip()` only when `string_mode='casefold'` is requested.
- `CaseResult.detail` is truncated to 200 characters and does not echo argument values; it may include call indices, function names, and parameter names.
- The library imports only the Python standard library and makes no network calls. It configures `logging.getLogger(__name__)` with a `NullHandler`.
- `main` opens the two input files with `encoding='utf-8'`, returns `2` for usage or IO errors, and does not invoke a shell.

### Not defended

- The package does not execute predicted functions, so it provides no sandbox, capability control, or runtime isolation for function execution.
- `load_functions` has no character-size limit or count limit on the input text or on the number of functions it parses. A caller that feeds unbounded data can consume memory and CPU.
- `evaluate` has no limit on the number of cases. It applies `parse_calls` defaults per case but does not bound the total workload.
- The CLI reads whatever paths it is given; it does not restrict filesystem access, validate paths, or protect against malicious files beyond normal JSON parsing.
- Failure detail can contain untrusted function or parameter names from the input, bounded to 200 characters. It is not escaped for terminal output.
- No authentication, authorization, or secret handling is implemented in the package. No vulnerability-reporting address or publishing configuration is defined in the provided code.

## Publishing

The provided package code contains no publishing mechanism. Release configuration, if any, is outside `src/tool_use_eval/__init__.py`.
