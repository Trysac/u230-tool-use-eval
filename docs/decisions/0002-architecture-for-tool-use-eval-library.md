# Architecture for tool-use-eval library

Status: accepted (generated, pending human review)

## Context

Need a dependency-free library to evaluate function-calling predictions against schemas and acceptable values, with typed failure codes and order-insensitive matching.

## Decision

Implement a single Python module with dataclasses for Call, ExpectedCall, FunctionSpec, Parameter, CaseResult, Summary, and a ToolEvalError. Use a JSON Schema subset parser for function specifications, depth-limited JSON parsing for calls, and augmenting-path bipartite matching for order-insensitive value comparison. CLI is handled with manual argument parsing to control exit codes.

## Consequences

The library is self-contained, uses only standard library, and provides strict typing. Tests cover all acceptance criteria and edge cases. The augmenting-path algorithm ensures correct assignment even when calls are out of order. Depth and size limits protect against malicious input.
