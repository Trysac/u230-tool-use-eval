# tool-use-eval

[![PyPI version](https://img.shields.io/pypi/v/trysac-tool-use-eval)](https://pypi.org/project/trysac-tool-use-eval/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-tool-use-eval)](LICENSE)
[![CI](https://github.com/Trysac/u230-tool-use-eval/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u230-tool-use-eval/actions/workflows/ci.yml)

Score function-calling outputs against expected calls: schema checks, acceptable-value sets per argument, order-insensitive parallel calls and per-failure-code summaries

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-tool-use-eval
# or
uv add trysac-tool-use-eval
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import tool_use_eval

# normalize() trims surrounding whitespace and lower-cases the text.
print(tool_use_eval.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    tool_use_eval.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
