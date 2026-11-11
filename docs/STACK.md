# Stack

## Used

| Tool | Why |
|---|---|
| Python >= 3.10 | The code uses PEP 604 union syntax and `zip(..., strict=False)`. |
| Python standard library | Imports are `json`, `logging`, `math`, `sys`, `collections.Counter`, `collections.abc`, `dataclasses`, and `typing`. |

No third-party runtime dependencies are imported or declared by the package code.

## Discarded

| Tool | Why not |
|---|---|
| Third-party runtime dependencies | None are imported by `src/tool_use_eval/__init__.py`. |
