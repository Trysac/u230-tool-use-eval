"""Score function-calling outputs against expected calls.

This library parses predicted tool calls, validates them against a function
schema, and compares them to expected calls with per-argument acceptable value
sets. It provides a summary of per-failure-code counts for evaluation.

The public API consists of:

- :class:`Call` - a single predicted call.
- :class:`ExpectedCall` - a single expected call with acceptable values.
- :class:`CaseResult` - the result of checking one case.
- :class:`Summary` - aggregate results over multiple cases.
- :func:`load_functions` - parse a JSON array of function specifications.
- :func:`parse_calls` - parse a JSON representation of predicted calls.
- :func:`check_case` - compare actual calls against expected calls.
- :func:`evaluate` - evaluate many cases.
- :func:`main` - command line interface.

Errors are reported via :class:`ToolEvalError` with a stable machine-readable
``code`` attribute.
"""

from __future__ import annotations

import json
import logging
import math
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Public types and constants
ToolEvalCode = Literal[
    "unparseable",
    "input_too_large",
    "too_many_calls",
    "too_deep",
    "unsupported_schema",
    "invalid_case",
    "wrong_count",
    "unknown_function",
    "missing_required",
    "unexpected_param",
    "type_mismatch",
    "wrong_function",
    "value_mismatch",
]


class ToolEvalError(Exception):
    """Raised for all tool-use evaluation errors.

    Attributes:
        code: A stable machine-readable error code.
    """

    def __init__(self, code: ToolEvalCode, message: str = "") -> None:
        super().__init__(message)
        self.code = code

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__()}".strip()


@dataclass(frozen=True)
class Call:
    """A single predicted function call."""

    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class Parameter:
    """Internal representation of a function parameter schema."""

    type: str
    required: bool = False
    enum: tuple[object, ...] | None = None
    items: Parameter | None = None
    properties: Mapping[str, Parameter] | None = None
    required_props: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FunctionSpec:
    """A parsed function specification."""

    name: str
    parameters: Mapping[str, Parameter]


@dataclass(frozen=True)
class ExpectedCall:
    """An expected function call with per-parameter acceptable values."""

    name: str
    params: Mapping[str, Sequence[object]]


@dataclass(frozen=True)
class Case:
    """One evaluation case: actual predicted text and expected calls."""

    id: str
    actual_text: str
    expected: Sequence[ExpectedCall]


@dataclass(frozen=True)
class CaseResult:
    """Result of checking a single case."""

    ok: bool
    code: str | None
    detail: str


@dataclass(frozen=True)
class Summary:
    """Aggregate evaluation summary."""

    total: int
    correct: int
    accuracy: float
    by_code: dict[str, int]


# --- JSON schema subset parsing -------------------------------------------------

_SCALAR_TYPES = {"string", "integer", "number", "boolean"}


def _parse_parameter(schema: object, depth: int = 0) -> Parameter:
    """Parse a single parameter schema object into a :class:`Parameter`.

    Raises:
        ToolEvalError: if the schema is unsupported.
    """
    if depth > 32:
        raise ToolEvalError("unsupported_schema", "schema nesting too deep")
    if not isinstance(schema, dict):
        raise ToolEvalError("unsupported_schema", "parameter must be an object")

    type_ = schema.get("type")
    if type_ not in _SCALAR_TYPES and type_ != "array" and type_ != "object":
        raise ToolEvalError("unsupported_schema", f"unsupported type {type_!r}")

    enum: tuple[object, ...] | None = None
    if "enum" in schema:
        enum_values = schema["enum"]
        if not isinstance(enum_values, list) or not enum_values:
            raise ToolEvalError("unsupported_schema", "enum must be a non-empty list")
        enum = tuple(enum_values)

    if type_ == "array":
        items_schema = schema.get("items")
        if not isinstance(items_schema, dict):
            raise ToolEvalError("unsupported_schema", "array must have items object")
        items_param = _parse_parameter(items_schema, depth + 1)
        return Parameter(type=type_, enum=enum, items=items_param)

    if type_ == "object":
        properties_schema = schema.get("properties")
        if not isinstance(properties_schema, dict):
            raise ToolEvalError("unsupported_schema", "object must have properties object")
        required_list = schema.get("required", [])
        if not isinstance(required_list, list) or not all(
            isinstance(name, str) for name in required_list
        ):
            raise ToolEvalError("unsupported_schema", "required must be a list of strings")
        properties: dict[str, Parameter] = {}
        for prop_name, prop_schema in properties_schema.items():
            if not isinstance(prop_name, str):
                raise ToolEvalError("unsupported_schema", "property names must be strings")
            prop_param = _parse_parameter(prop_schema, depth + 1)
            if prop_name in required_list:
                prop_param = replace(prop_param, required=True)
            properties[prop_name] = prop_param
        return Parameter(
            type=type_,
            enum=enum,
            properties=properties,
            required_props=frozenset(required_list),
        )

    # Scalar
    if enum is not None:
        # Validate enum values match type
        for val in enum:
            if not _value_matches_type(val, type_):
                raise ToolEvalError("unsupported_schema", "enum value does not match type")
    return Parameter(type=type_, enum=enum)


def _value_matches_type(value: object, type_: str) -> bool:
    if type_ == "string":
        return isinstance(value, str)
    if type_ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_ == "number":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and math.isfinite(value)
    if type_ == "boolean":
        return isinstance(value, bool)
    return False


def load_functions(text: str) -> dict[str, FunctionSpec]:
    """Parse a JSON array of function specifications.

    Args:
        text: JSON string containing an array of objects with ``name`` (str)
              and ``parameters`` (JSON Schema subset object).

    Returns:
        dict mapping function name to :class:`FunctionSpec`.

    Raises:
        ToolEvalError: if the JSON is invalid or the schema is unsupported
                       (``code`` = ``'unsupported_schema'``).
    """
    try:
        data = json.loads(text)
    except RecursionError as exc:
        raise ToolEvalError("unsupported_schema", "JSON nesting too deep") from exc
    except json.JSONDecodeError as exc:
        raise ToolEvalError("unsupported_schema", f"invalid JSON: {exc.msg}") from exc

    if not isinstance(data, list):
        raise ToolEvalError("unsupported_schema", "top-level must be an array")

    functions: dict[str, FunctionSpec] = {}
    for entry in data:
        if not isinstance(entry, dict):
            raise ToolEvalError("unsupported_schema", "each function must be an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ToolEvalError("unsupported_schema", "function must have a non-empty string name")
        parameters_schema = entry.get("parameters")
        if not isinstance(parameters_schema, dict):
            raise ToolEvalError("unsupported_schema", "function must have parameters object")
        # The parameters object must have type 'object' (explicit or implicit)
        params_type = parameters_schema.get("type", "object")
        if params_type != "object":
            raise ToolEvalError("unsupported_schema", "parameters type must be 'object'")
        try:
            param = _parse_parameter(parameters_schema)
        except ToolEvalError:
            raise
        if param.type != "object":
            raise ToolEvalError("unsupported_schema", "parameters must be object")
        functions[name] = FunctionSpec(name=name, parameters=param.properties or {})
    return functions


# --- Depth-limited JSON traversal for arguments ---------------------------------


def _check_depth(obj: object, current_depth: int, max_depth: int) -> None:
    """Iteratively check that the nesting depth of ``obj`` does not exceed ``max_depth``.

    Uses an explicit stack so it can never itself hit the interpreter recursion
    limit.

    Raises:
        ToolEvalError: if depth exceeds ``max_depth`` with code ``'too_deep'``.
    """
    stack: list[tuple[object, int]] = [(obj, current_depth)]
    while stack:
        value, depth = stack.pop()
        if depth > max_depth:
            raise ToolEvalError("too_deep", f"nesting depth exceeds {max_depth}")
        if isinstance(value, dict):
            for item in value.values():
                stack.append((item, depth + 1))
        elif isinstance(value, list):
            for item in value:
                stack.append((item, depth + 1))


def _text_nesting_depth(text: str) -> int:
    """Iteratively compute the deepest ``[]``/``{}`` nesting in raw JSON text.

    String literals and their escapes are ignored, so brackets inside strings do
    not count. Used only when the decoder itself refuses a text, to tell an
    over-deep document (``'too_deep'``) from ordinary invalid JSON.
    """
    depth = 0
    deepest = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > deepest:
                deepest = depth
        elif char in "]}" and depth > 0:
            depth -= 1
    return deepest


def parse_calls(
    text: str,
    *,
    max_chars: int = 1_000_000,
    max_calls: int = 16,
    max_depth: int = 32,
) -> list[Call]:
    """Parse a JSON representation of predicted calls.

    The JSON can be either a single call object or an array of call objects.
    Each call object has ``name`` (str) and ``arguments`` which is either an
    object or a JSON-encoded object string.

    Args:
        text: The JSON text to parse.
        max_chars: Maximum number of characters allowed in ``text``.
        max_calls: Maximum number of calls allowed.
        max_depth: Maximum nesting depth allowed in arguments.

    Returns:
        list of :class:`Call` objects.

    Raises:
        ToolEvalError: with appropriate code (``'input_too_large'``,
            ``'unparseable'``, ``'too_many_calls'``, ``'too_deep'``).
    """
    if len(text) > max_chars:
        raise ToolEvalError("input_too_large", f"text exceeds {max_chars} characters")

    try:
        raw = json.loads(text)
    except RecursionError as exc:
        raise ToolEvalError("too_deep", "JSON nesting too deep") from exc
    except json.JSONDecodeError as exc:
        # A decoder can report an extremely nested document as a syntax error
        # once it exhausts its own recursion budget, so check the raw text
        # before calling it merely unparseable.
        if _text_nesting_depth(text) > max_depth + 2:
            raise ToolEvalError("too_deep", f"nesting depth exceeds {max_depth}") from exc
        raise ToolEvalError("unparseable", f"invalid JSON: {exc.msg}") from exc

    # Normalize to list
    if isinstance(raw, dict):
        raw_calls = [raw]
    elif isinstance(raw, list):
        raw_calls = raw
    else:
        raise ToolEvalError("unparseable", "top-level must be an object or array")

    if len(raw_calls) > max_calls:
        raise ToolEvalError("too_many_calls", f"more than {max_calls} calls")

    calls: list[Call] = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            raise ToolEvalError("unparseable", "each call must be an object")
        name = raw_call.get("name")
        if not isinstance(name, str) or not name:
            raise ToolEvalError("unparseable", "call must have a non-empty string name")
        args = raw_call.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except RecursionError as exc:
                raise ToolEvalError("too_deep", "arguments JSON nesting too deep") from exc
            except json.JSONDecodeError as exc:
                if _text_nesting_depth(args) > max_depth + 2:
                    raise ToolEvalError("too_deep", f"nesting depth exceeds {max_depth}") from exc
                raise ToolEvalError(
                    "unparseable", f"arguments string is invalid JSON: {exc.msg}"
                ) from exc
        if not isinstance(args, dict):
            raise ToolEvalError(
                "unparseable", "arguments must be an object or JSON-encoded object string"
            )
        _check_depth(args, 0, max_depth)
        calls.append(Call(name=name, arguments=args))
    return calls


# --- Value comparison ------------------------------------------------------------


def _deep_equal(actual: object, expected: object, string_mode: str) -> bool:
    """Recursively compare two values with string mode rules."""
    if string_mode == "casefold" and isinstance(actual, str) and isinstance(expected, str):
        return actual.casefold().strip() == expected.casefold().strip()
    if isinstance(actual, bool) or isinstance(expected, bool):
        # booleans are not numbers
        return actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        # both numbers: reject non-finite floats, then compare numerically.
        # ints are always finite (and never converted to float, which could overflow).
        if isinstance(actual, float) and not math.isfinite(actual):
            return False
        if isinstance(expected, float) and not math.isfinite(expected):
            return False
        return actual == expected
    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            return False
        return all(_deep_equal(a, e, string_mode) for a, e in zip(actual, expected, strict=False))
    if isinstance(actual, dict) and isinstance(expected, dict):
        if set(actual.keys()) != set(expected.keys()):
            return False
        return all(_deep_equal(actual[k], expected[k], string_mode) for k in actual)
    # Fallback
    return actual == expected


def _value_matches_acceptable(
    actual: object, acceptable_values: Sequence[object], string_mode: str
) -> bool:
    """Check if actual value matches any of the acceptable values."""
    return any(_deep_equal(actual, expected, string_mode) for expected in acceptable_values)


# --- Case checking ---------------------------------------------------------------

_MAX_DETAIL_CHARS = 200


def _detail(text: str) -> str:
    """Bound a :class:`CaseResult` detail to the documented 200 characters."""
    return text[:_MAX_DETAIL_CHARS]


def _check_parameter_type(
    param: Parameter,
    value: object,
    string_mode: str,
) -> bool:
    """Check that value conforms to the parameter schema."""
    if param.enum is not None:
        return any(_deep_equal(value, enum_val, string_mode) for enum_val in param.enum)
    if param.type == "string":
        return isinstance(value, str)
    if param.type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if param.type == "number":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and math.isfinite(value)
    if param.type == "boolean":
        return isinstance(value, bool)
    if param.type == "array":
        if not isinstance(value, list):
            return False
        if param.items is None:
            return False
        return all(_check_parameter_type(param.items, item, string_mode) for item in value)
    if param.type == "object":
        if not isinstance(value, dict):
            return False
        if param.properties is None:
            return False
        for key, prop in param.properties.items():
            if key in value:
                if not _check_parameter_type(prop, value[key], string_mode):
                    return False
            elif key in param.required_props:
                return False
        return True
    return False


def check_case(
    actual: Sequence[Call],
    expected: Sequence[ExpectedCall],
    functions: Mapping[str, FunctionSpec],
    *,
    string_mode: Literal["exact", "casefold"] = "exact",
) -> CaseResult:
    """Check a set of actual calls against expected calls and function schemas.

    Implements the ordered checks described in the specification.

    Args:
        actual: Sequence of :class:`Call` (already parsed).
        expected: Sequence of :class:`ExpectedCall`.
        functions: Mapping of function name to :class:`FunctionSpec`.
        string_mode: ``'exact'`` or ``'casefold'``.

    Returns:
        :class:`CaseResult` with ``ok`` bool, ``code`` (None if ok), and
        ``detail`` string (empty if ok).
    """
    # Wrong count
    if len(actual) != len(expected):
        return CaseResult(
            ok=False,
            code="wrong_count",
            detail=_detail(f"expected {len(expected)} calls, got {len(actual)}"),
        )

    # Unknown function names take precedence over per-call argument problems.
    for i, call in enumerate(actual):
        if call.name not in functions:
            return CaseResult(
                ok=False,
                code="unknown_function",
                detail=_detail(f"call {i}: unknown function"),
            )

    # Missing required parameters.
    for i, call in enumerate(actual):
        func_spec = functions[call.name]
        for param_name, param in func_spec.parameters.items():
            if param.required and param_name not in call.arguments:
                return CaseResult(
                    ok=False,
                    code="missing_required",
                    detail=_detail(f"call {i}: missing required parameter '{param_name}'"),
                )

    # Parameters that the function does not declare.
    for i, call in enumerate(actual):
        func_spec = functions[call.name]
        for param_name in call.arguments:
            if param_name not in func_spec.parameters:
                return CaseResult(
                    ok=False,
                    code="unexpected_param",
                    detail=_detail(f"call {i}: unexpected parameter '{param_name}'"),
                )

    # Parameter types and enum values.
    for i, call in enumerate(actual):
        func_spec = functions[call.name]
        for param_name, value in call.arguments.items():
            param = func_spec.parameters[param_name]
            if not _check_parameter_type(param, value, string_mode):
                return CaseResult(
                    ok=False,
                    code="type_mismatch",
                    detail=_detail(f"call {i}: parameter '{param_name}' has invalid type or value"),
                )

    # Wrong function (multiset of names)
    actual_names = Counter(call.name for call in actual)
    expected_names = Counter(exp.name for exp in expected)
    if actual_names != expected_names:
        return CaseResult(
            ok=False,
            code="wrong_function",
            detail=_detail("function name multiset differs"),
        )

    # Value matching via bipartite augmenting path
    n = len(actual)
    adj: list[list[int]] = [[] for _ in range(n)]
    for i, act in enumerate(actual):
        for j, exp in enumerate(expected):
            if act.name != exp.name:
                continue
            # Check value constraints
            if _call_matches_expected(act, exp, string_mode):
                adj[i].append(j)

    match_to_actual = [-1] * n  # for each expected, which actual is assigned

    def dfs(u: int, seen: list[bool]) -> bool:
        for v in adj[u]:
            if seen[v]:
                continue
            seen[v] = True
            if match_to_actual[v] == -1 or dfs(match_to_actual[v], seen):
                match_to_actual[v] = u
                return True
        return False

    for u in range(n):
        seen = [False] * n
        if not dfs(u, seen):
            # No perfect matching
            return CaseResult(
                ok=False,
                code="value_mismatch",
                detail=_detail(f"call {u} cannot be matched to any expected call"),
            )

    return CaseResult(ok=True, code=None, detail="")


def _call_matches_expected(
    actual_call: Call, expected_call: ExpectedCall, string_mode: str
) -> bool:
    """Check if an actual call matches the constraints of an expected call."""
    if actual_call.name != expected_call.name:
        return False
    # Check each expected parameter
    for param_name, acceptable_values in expected_call.params.items():
        # If '' is in acceptable values, the parameter may be omitted
        if "" in acceptable_values and param_name not in actual_call.arguments:
            continue
        if param_name not in actual_call.arguments:
            return False
        actual_val = actual_call.arguments[param_name]
        if not _value_matches_acceptable(actual_val, acceptable_values, string_mode):
            return False
    # Check that actual does not contain parameters not expected
    # (unexpected_param already handled, but extra safety)
    return all(param_name in expected_call.params for param_name in actual_call.arguments)


# --- Evaluation -------------------------------------------------------------------


def evaluate(
    cases: Iterable[Case],
    functions: Mapping[str, FunctionSpec],
    *,
    string_mode: Literal["exact", "casefold"] = "exact",
) -> Summary:
    """Evaluate multiple cases and produce a summary.

    Each case's ``actual_text`` is parsed with :func:`parse_calls`. If parsing
    fails, the resulting code is recorded. Otherwise, :func:`check_case` is
    used. All failure codes are accumulated in ``by_code``.

    Args:
        cases: Iterable of :class:`Case`.
        functions: Function specifications.
        string_mode: String comparison mode.

    Returns:
        :class:`Summary` with total, correct, accuracy, by_code.
    """
    total = 0
    correct = 0
    by_code: dict[str, int] = {}

    for case in cases:
        total += 1
        try:
            actual_calls = parse_calls(case.actual_text)
        except ToolEvalError as exc:
            error_code = exc.code
            by_code[error_code] = by_code.get(error_code, 0) + 1
            continue
        result = check_case(actual_calls, case.expected, functions, string_mode=string_mode)
        if result.ok:
            correct += 1
        else:
            result_code = result.code
            if result_code is not None:
                by_code[result_code] = by_code.get(result_code, 0) + 1

    accuracy = correct / total if total > 0 else 0.0
    return Summary(total=total, correct=correct, accuracy=accuracy, by_code=by_code)


# --- CLI --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface.

    Usage: ``run <functions.json> <cases.jsonl> [--min-accuracy 0.0] [--casefold]``

    Returns:
        0 if accuracy >= min_accuracy, 1 if below, 2 on usage or IO errors.
    """
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) < 3 or argv[0] != "run":
        _print_usage()
        return 2
    functions_file = argv[1]
    cases_file = argv[2]
    min_accuracy = 0.0
    casefold = False
    i = 3
    while i < len(argv):
        if argv[i] == "--min-accuracy":
            if i + 1 >= len(argv):
                _print_usage()
                return 2
            try:
                min_accuracy = float(argv[i + 1])
            except ValueError:
                print("Invalid min-accuracy value", file=sys.stderr)
                return 2
            if not (0.0 <= min_accuracy <= 1.0):
                print("min-accuracy must be between 0 and 1", file=sys.stderr)
                return 2
            i += 2
        elif argv[i] == "--casefold":
            casefold = True
            i += 1
        else:
            _print_usage()
            return 2

    # Load functions
    try:
        with open(functions_file, encoding="utf-8") as f:
            functions_text = f.read()
        functions = load_functions(functions_text)
    except (OSError, ToolEvalError) as exc:
        print(f"Error loading functions: {exc}", file=sys.stderr)
        return 2

    # Load cases
    cases: list[Case] = []
    try:
        with open(cases_file, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(f"Error parsing case on line {line_num}: {exc}", file=sys.stderr)
                    return 2
                if not isinstance(obj, dict):
                    print(f"Case on line {line_num} must be an object", file=sys.stderr)
                    return 2
                case_id = obj.get("id")
                if not isinstance(case_id, str):
                    print(f"Case on line {line_num} missing string 'id'", file=sys.stderr)
                    return 2
                actual_text = obj.get("actual")
                if not isinstance(actual_text, str):
                    print(f"Case on line {line_num} missing string 'actual'", file=sys.stderr)
                    return 2
                expected_raw = obj.get("expected")
                if not isinstance(expected_raw, list):
                    print(f"Case on line {line_num} missing list 'expected'", file=sys.stderr)
                    return 2
                expected_calls: list[ExpectedCall] = []
                for exp_idx, exp_obj in enumerate(expected_raw):
                    if not isinstance(exp_obj, dict):
                        print(
                            f"Case on line {line_num}, expected call {exp_idx} must be an object",
                            file=sys.stderr,
                        )
                        return 2
                    exp_name = exp_obj.get("name")
                    if not isinstance(exp_name, str) or not exp_name:
                        print(
                            f"Case on line {line_num}, expected call {exp_idx} "
                            "missing string 'name'",
                            file=sys.stderr,
                        )
                        return 2
                    exp_params_raw = exp_obj.get("params")
                    if not isinstance(exp_params_raw, dict):
                        print(
                            f"Case on line {line_num}, expected call {exp_idx} "
                            "missing object 'params'",
                            file=sys.stderr,
                        )
                        return 2
                    exp_params: dict[str, Sequence[object]] = {}
                    for param_name, acceptable_values in exp_params_raw.items():
                        if not isinstance(param_name, str):
                            print(
                                f"Case on line {line_num}, expected call {exp_idx} "
                                "param name must be string",
                                file=sys.stderr,
                            )
                            return 2
                        if not isinstance(acceptable_values, list):
                            print(
                                f"Case on line {line_num}, expected call {exp_idx} "
                                f"param {param_name} must have a list",
                                file=sys.stderr,
                            )
                            return 2
                        exp_params[param_name] = acceptable_values
                    expected_calls.append(ExpectedCall(name=exp_name, params=exp_params))
                cases.append(Case(id=case_id, actual_text=actual_text, expected=expected_calls))
    except OSError as exc:
        print(f"Error reading cases file: {exc}", file=sys.stderr)
        return 2

    string_mode: Literal["exact", "casefold"] = "casefold" if casefold else "exact"
    summary = evaluate(cases, functions, string_mode=string_mode)

    print(f"accuracy={summary.accuracy:.3f} correct={summary.correct} total={summary.total}")
    for code in sorted(summary.by_code):
        print(f"{code} {summary.by_code[code]}")

    exit_code = 0 if summary.accuracy >= min_accuracy else 1
    return exit_code


def _print_usage() -> None:
    print(
        "Usage: run <functions.json> <cases.jsonl> [--min-accuracy 0.0] [--casefold]",
        file=sys.stderr,
    )


__all__ = [
    "Call",
    "Case",
    "CaseResult",
    "ExpectedCall",
    "FunctionSpec",
    "Parameter",
    "Summary",
    "ToolEvalError",
    "check_case",
    "evaluate",
    "load_functions",
    "main",
    "parse_calls",
]
