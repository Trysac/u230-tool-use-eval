import json

import pytest

from tool_use_eval import (
    Call,
    Case,
    CaseResult,
    ExpectedCall,
    FunctionSpec,
    Parameter,
    ToolEvalError,
    check_case,
    evaluate,
    load_functions,
    main,
    parse_calls,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def make_functions() -> dict[str, FunctionSpec]:
    """Create functions: get_weather(city: string req, unit: enum opt), get_time(no params), get_temp(days:int, limit:number)."""
    city_param = Parameter(type="string", required=True)
    unit_param = Parameter(type="string", enum=("celsius", "fahrenheit"))
    params = {"city": city_param, "unit": unit_param}
    weather = FunctionSpec(name="get_weather", parameters=params)

    time_spec = FunctionSpec(name="get_time", parameters={})

    days_param = Parameter(type="integer", required=True)
    limit_param = Parameter(type="number")
    temp_params = {"days": days_param, "limit": limit_param}
    temp = FunctionSpec(name="get_temp", parameters=temp_params)

    return {
        "get_weather": weather,
        "get_time": time_spec,
        "get_temp": temp,
    }


def make_weather_expected() -> ExpectedCall:
    return ExpectedCall(
        name="get_weather",
        params={
            "city": ["Paris", "paris"],
            "unit": ["celsius", ""],
        },
    )


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


class TestParseCalls:
    def test_parse_list_with_mixed_arguments(self):
        text = json.dumps(
            [
                {"name": "get_weather", "arguments": {"city": "Paris"}},
                {"name": "get_weather", "arguments": '{"city": "Rome"}'},
            ]
        )
        calls = parse_calls(text)
        assert len(calls) == 2
        assert calls[0] == Call("get_weather", {"city": "Paris"})
        assert calls[1] == Call("get_weather", {"city": "Rome"})

    def test_parse_single_object(self):
        text = json.dumps({"name": "get_weather", "arguments": {"city": "Paris"}})
        calls = parse_calls(text)
        assert calls == [Call("get_weather", {"city": "Paris"})]

    def test_parse_invalid_json_raises_unparseable(self):
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls("not json")
        assert exc_info.value.code == "unparseable"

    def test_parse_too_large_text(self):
        text = "x" * 1_000_001
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls(text)
        assert exc_info.value.code == "input_too_large"

    def test_parse_too_many_calls(self):
        calls = [{"name": "f", "arguments": {}} for _ in range(17)]
        text = json.dumps(calls)
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls(text)
        assert exc_info.value.code == "too_many_calls"

    def test_parse_too_deep_arguments(self):
        # Build nested object depth 33 (root depth 0)
        obj = {}
        for _ in range(33):
            obj = {"a": obj}
        call = {"name": "f", "arguments": obj}
        text = json.dumps(call)
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls(text)
        assert exc_info.value.code == "too_deep"

    def test_parse_arguments_string_invalid_json(self):
        call = {"name": "f", "arguments": "{bad json"}
        text = json.dumps(call)
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls(text)
        assert exc_info.value.code == "unparseable"

    def test_parse_arguments_not_object(self):
        call = {"name": "f", "arguments": [1, 2]}
        text = json.dumps(call)
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls(text)
        assert exc_info.value.code == "unparseable"


class TestLoadFunctions:
    def test_load_valid_functions(self):
        text = json.dumps(
            [
                {
                    "name": "get_weather",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                        },
                        "required": ["city"],
                    },
                },
                {"name": "get_time", "parameters": {"type": "object", "properties": {}}},
                {
                    "name": "get_temp",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days": {"type": "integer"},
                            "limit": {"type": "number"},
                        },
                        "required": ["days"],
                    },
                },
            ]
        )
        funcs = load_functions(text)
        assert set(funcs.keys()) == {"get_weather", "get_time", "get_temp"}
        weather = funcs["get_weather"]
        assert weather.parameters["city"].required is True
        assert weather.parameters["unit"].enum == ("celsius", "fahrenheit")
        assert weather.parameters["unit"].required is False
        assert funcs["get_time"].parameters == {}
        assert funcs["get_temp"].parameters["days"].type == "integer"
        assert funcs["get_temp"].parameters["limit"].type == "number"

    def test_load_invalid_json_raises_unsupported_schema(self):
        with pytest.raises(ToolEvalError) as exc_info:
            load_functions("not json")
        assert exc_info.value.code == "unsupported_schema"

    def test_load_missing_parameters_type(self):
        text = json.dumps([{"name": "f", "parameters": {"type": "array"}}])
        with pytest.raises(ToolEvalError) as exc_info:
            load_functions(text)
        assert exc_info.value.code == "unsupported_schema"

    def test_load_unsupported_type(self):
        text = json.dumps(
            [{"name": "f", "parameters": {"type": "object", "properties": {"x": {"type": "date"}}}}]
        )
        with pytest.raises(ToolEvalError) as exc_info:
            load_functions(text)
        assert exc_info.value.code == "unsupported_schema"

    def test_load_enum_value_mismatch(self):
        text = json.dumps(
            [
                {
                    "name": "f",
                    "parameters": {
                        "type": "object",
                        "properties": {"x": {"type": "integer", "enum": ["a"]}},
                    },
                }
            ]
        )
        with pytest.raises(ToolEvalError) as exc_info:
            load_functions(text)
        assert exc_info.value.code == "unsupported_schema"


class TestCheckCase:
    def setup_method(self):
        self.functions = make_functions()

    def test_ok_optional_omitted(self):
        actual = [Call("get_weather", {"city": "paris"})]
        expected = [make_weather_expected()]
        result = check_case(actual, expected, self.functions)
        assert result == CaseResult(ok=True, code=None, detail="")

    def test_value_mismatch_unit_fahrenheit(self):
        actual = [Call("get_weather", {"city": "Paris", "unit": "fahrenheit"})]
        expected = [make_weather_expected()]
        result = check_case(actual, expected, self.functions)
        assert result.ok is False
        assert result.code == "value_mismatch"

    def test_missing_required(self):
        actual = [Call("get_weather", {"unit": "celsius"})]
        expected = [make_weather_expected()]
        result = check_case(actual, expected, self.functions)
        assert result.code == "missing_required"

    def test_unexpected_param(self):
        actual = [Call("get_weather", {"city": "Paris", "country": "FR"})]
        expected = [make_weather_expected()]
        result = check_case(actual, expected, self.functions)
        assert result.code == "unexpected_param"

    def test_type_mismatch_enum(self):
        actual = [Call("get_weather", {"city": "Paris", "unit": "kelvin"})]
        expected = [make_weather_expected()]
        result = check_case(actual, expected, self.functions)
        assert result.code == "type_mismatch"

    def test_unknown_function(self):
        actual = [Call("get_wether", {"city": "Paris"})]
        expected = [make_weather_expected()]
        result = check_case(actual, expected, self.functions)
        assert result.code == "unknown_function"

    def test_wrong_count(self):
        actual = [Call("get_weather", {"city": "Paris"})]
        expected = [make_weather_expected(), make_weather_expected()]
        result = check_case(actual, expected, self.functions)
        assert result.code == "wrong_count"

    def test_wrong_function(self):
        actual = [Call("get_time", {})]
        expected = [make_weather_expected()]
        result = check_case(actual, expected, self.functions)
        assert result.code == "wrong_function"

    def test_value_mismatch_order_insensitive_match(self):
        actual = [Call("get_weather", {"city": "Rome"}), Call("get_weather", {"city": "Paris"})]
        expected = [
            ExpectedCall("get_weather", {"city": ["Paris"], "unit": [""]}),
            ExpectedCall("get_weather", {"city": ["Rome"], "unit": [""]}),
        ]
        result = check_case(actual, expected, self.functions)
        assert result.ok is True

    def test_two_actual_same_expected_value_mismatch(self):
        actual = [Call("get_weather", {"city": "Paris"}), Call("get_weather", {"city": "Paris"})]
        expected = [
            ExpectedCall("get_weather", {"city": ["Paris"], "unit": [""]}),
            ExpectedCall("get_weather", {"city": ["Rome"], "unit": [""]}),
        ]
        result = check_case(actual, expected, self.functions)
        assert result.code == "value_mismatch"

    def test_int_bool_mismatch(self):
        funcs = make_functions()
        actual = [Call("get_temp", {"days": True})]
        expected = [ExpectedCall("get_temp", {"days": [3]})]
        result = check_case(actual, expected, funcs)
        assert result.code == "type_mismatch"

    def test_int_matches_int(self):
        funcs = make_functions()
        actual = [Call("get_temp", {"days": 3})]
        expected = [ExpectedCall("get_temp", {"days": [3]})]
        result = check_case(actual, expected, funcs)
        assert result.ok is True

    def test_number_accepts_int(self):
        funcs = make_functions()
        actual = [Call("get_temp", {"days": 1, "limit": 3})]
        expected = [ExpectedCall("get_temp", {"days": [1], "limit": [3.0]})]
        result = check_case(actual, expected, funcs)
        assert result.ok is True

    def test_float_for_int_mismatch(self):
        funcs = make_functions()
        actual = [Call("get_temp", {"days": 2.5})]
        expected = [ExpectedCall("get_temp", {"days": [2]})]
        result = check_case(actual, expected, funcs)
        assert result.code == "type_mismatch"

    def test_casefold_string_matching(self):
        actual = [Call("get_weather", {"city": " PARIS "})]
        expected = [ExpectedCall("get_weather", {"city": ["paris"], "unit": [""]})]
        result = check_case(actual, expected, self.functions, string_mode="casefold")
        assert result.ok is True

    def test_exact_string_matching(self):
        actual = [Call("get_weather", {"city": " PARIS "})]
        expected = [ExpectedCall("get_weather", {"city": ["paris"], "unit": [""]})]
        result = check_case(actual, expected, self.functions, string_mode="exact")
        assert result.code == "value_mismatch"


class TestEvaluate:
    def test_evaluate_summary(self):
        functions = make_functions()
        expected_weather = make_weather_expected()
        cases = [
            Case(
                id="1",
                actual_text=json.dumps([{"name": "get_weather", "arguments": {"city": "Paris"}}]),
                expected=[expected_weather],
            ),
            Case(
                id="2",
                actual_text=json.dumps([{"name": "get_weather", "arguments": {"city": "paris"}}]),
                expected=[expected_weather],
            ),
            Case(
                id="3",
                actual_text=json.dumps(
                    [{"name": "get_weather", "arguments": {"city": "Paris", "unit": "fahrenheit"}}]
                ),
                expected=[expected_weather],
            ),
            Case(
                id="4",
                actual_text=json.dumps(
                    [
                        {"name": "get_weather", "arguments": {"city": "Paris"}},
                        {"name": "get_weather", "arguments": {"city": "Paris"}},
                    ]
                ),
                expected=[expected_weather],
            ),
        ]
        summary = evaluate(cases, functions)
        assert summary.total == 4
        assert summary.correct == 2
        assert summary.accuracy == 0.5
        assert summary.by_code == {"value_mismatch": 1, "wrong_count": 1}

    def test_evaluate_zero_cases(self):
        functions = make_functions()
        summary = evaluate([], functions)
        assert summary.total == 0
        assert summary.correct == 0
        assert summary.accuracy == 0.0
        assert summary.by_code == {}

    def test_evaluate_parse_error_maps_code(self):
        functions = make_functions()
        cases = [Case(id="bad", actual_text="not json", expected=[])]
        summary = evaluate(cases, functions)
        assert summary.total == 1
        assert summary.correct == 0
        assert summary.by_code == {"unparseable": 1}

    def test_evaluate_maps_size_call_and_depth_guards(self):
        functions = make_functions()
        cases = [
            Case(id="large", actual_text="x" * 1_000_001, expected=[]),
            Case(
                id="many",
                actual_text=json.dumps([{"name": "f", "arguments": {}} for _ in range(17)]),
                expected=[],
            ),
            Case(id="deep", actual_text="[" * 5000, expected=[]),
        ]
        summary = evaluate(cases, functions)
        assert summary.total == 3
        assert summary.correct == 0
        assert summary.accuracy == 0.0
        assert summary.by_code == {
            "input_too_large": 1,
            "too_many_calls": 1,
            "too_deep": 1,
        }


class TestCLI:
    def test_cli_success(self, tmp_path, capsys):
        functions_file = tmp_path / "functions.json"
        functions_file.write_text(
            json.dumps(
                [
                    {
                        "name": "get_weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    }
                ]
            )
        )
        cases_file = tmp_path / "cases.jsonl"
        cases = [
            {
                "id": "1",
                "actual": json.dumps([{"name": "get_weather", "arguments": {"city": "Paris"}}]),
                "expected": [{"name": "get_weather", "params": {"city": ["Paris"]}}],
            },
            {
                "id": "2",
                "actual": json.dumps([{"name": "get_weather", "arguments": {"city": "Rome"}}]),
                "expected": [{"name": "get_weather", "params": {"city": ["Rome"]}}],
            },
        ]
        cases_file.write_text("\n".join(json.dumps(c) for c in cases))

        ret = main(["run", str(functions_file), str(cases_file), "--min-accuracy", "0.5"])
        captured = capsys.readouterr()
        assert ret == 0
        assert "accuracy=1.000 correct=2 total=2" in captured.out
        assert captured.out.replace("accuracy=1.000 correct=2 total=2\n", "") == ""

    def test_cli_below_min_accuracy(self, tmp_path, capsys):
        functions_file = tmp_path / "functions.json"
        functions_file.write_text(
            json.dumps(
                [
                    {
                        "name": "get_weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    }
                ]
            )
        )
        cases_file = tmp_path / "cases.jsonl"
        cases = [
            {
                "id": "1",
                "actual": json.dumps([{"name": "get_weather", "arguments": {"city": "Paris"}}]),
                "expected": [{"name": "get_weather", "params": {"city": ["Paris"]}}],
            },
            {
                "id": "2",
                "actual": json.dumps([{"name": "get_weather", "arguments": {"city": "Rome"}}]),
                "expected": [{"name": "get_weather", "params": {"city": ["Paris"]}}],
            },
        ]
        cases_file.write_text("\n".join(json.dumps(c) for c in cases))

        ret = main(["run", str(functions_file), str(cases_file), "--min-accuracy", "0.75"])
        captured = capsys.readouterr()
        assert ret == 1
        out_lines = captured.out.strip().split("\n")
        assert out_lines[0] == "accuracy=0.500 correct=1 total=2"
        assert out_lines[1:] == ["value_mismatch 1"]

    def test_cli_four_cases_summary_and_exit_codes(self, tmp_path, capsys):
        functions_file = tmp_path / "functions.json"
        functions_file.write_text(
            json.dumps(
                [
                    {
                        "name": "get_weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    }
                ]
            )
        )
        cases_file = tmp_path / "cases.jsonl"
        expected_paris = [{"name": "get_weather", "params": {"city": ["Paris"]}}]
        cases = [
            {
                "id": "1",
                "actual": json.dumps([{"name": "get_weather", "arguments": {"city": "Paris"}}]),
                "expected": expected_paris,
            },
            {
                "id": "2",
                "actual": json.dumps([{"name": "get_weather", "arguments": {"city": "Rome"}}]),
                "expected": [{"name": "get_weather", "params": {"city": ["Rome"]}}],
            },
            {
                "id": "3",
                "actual": json.dumps([{"name": "get_weather", "arguments": {"city": "Rome"}}]),
                "expected": expected_paris,
            },
            {
                "id": "4",
                "actual": json.dumps([{"name": "get_weather", "arguments": {"city": "Paris"}}]),
                "expected": expected_paris + expected_paris,
            },
        ]
        cases_file.write_text("\n".join(json.dumps(c) for c in cases))

        ret = main(["run", str(functions_file), str(cases_file), "--min-accuracy", "0.75"])
        captured = capsys.readouterr()
        assert ret == 1
        assert "accuracy=0.500 correct=2 total=4" in captured.out
        assert "value_mismatch 1" in captured.out
        assert "wrong_count 1" in captured.out

        ret = main(["run", str(functions_file), str(cases_file), "--min-accuracy", "0.5"])
        capsys.readouterr()
        assert ret == 0

    def test_cli_casefold(self, tmp_path, capsys):
        functions_file = tmp_path / "functions.json"
        functions_file.write_text(
            json.dumps(
                [
                    {
                        "name": "get_weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    }
                ]
            )
        )
        cases_file = tmp_path / "cases.jsonl"
        case = {
            "id": "1",
            "actual": json.dumps([{"name": "get_weather", "arguments": {"city": " PARIS "}}]),
            "expected": [{"name": "get_weather", "params": {"city": ["paris"]}}],
        }
        cases_file.write_text(json.dumps(case))

        ret = main(["run", str(functions_file), str(cases_file), "--casefold"])
        captured = capsys.readouterr()
        assert ret == 0
        assert "accuracy=1.000 correct=1 total=1" in captured.out

    def test_cli_usage_error(self, capsys):
        ret = main(["bad"])
        assert ret == 2
        captured = capsys.readouterr()
        assert "Usage:" in captured.err

    def test_cli_io_error(self, capsys):
        ret = main(["run", "/nonexistent/functions.json", "/nonexistent/cases.jsonl"])
        assert ret == 2
        captured = capsys.readouterr()
        assert "Error loading functions" in captured.err


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_parse_empty_text_raises_unparseable(self):
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls("")
        assert exc_info.value.code == "unparseable"

    def test_check_case_nan_number_rejected(self):
        funcs = make_functions()
        actual = [Call("get_temp", {"days": 1, "limit": float("nan")})]
        expected = [ExpectedCall("get_temp", {"days": [1], "limit": [1.0]})]
        result = check_case(actual, expected, funcs)
        assert result.code == "type_mismatch"

    def test_check_case_infinity_number_rejected(self):
        funcs = make_functions()
        actual = [Call("get_temp", {"days": 1, "limit": float("inf")})]
        expected = [ExpectedCall("get_temp", {"days": [1], "limit": [1.0]})]
        result = check_case(actual, expected, funcs)
        assert result.code == "type_mismatch"

    def test_nested_object_argument_recursive_compare(self):
        # Add a function with object parameter
        inner_param = Parameter(type="string")
        obj_param = Parameter(type="object", properties={"key": inner_param})
        func = FunctionSpec(name="complex", parameters={"data": obj_param})
        funcs = {"complex": func}
        actual = [Call("complex", {"data": {"key": "value"}})]
        expected = [ExpectedCall("complex", {"data": [{"key": "value"}]})]
        result = check_case(actual, expected, funcs)
        assert result.ok is True

    def test_nested_object_mismatch(self):
        inner_param = Parameter(type="string")
        obj_param = Parameter(type="object", properties={"key": inner_param})
        func = FunctionSpec(name="complex", parameters={"data": obj_param})
        funcs = {"complex": func}
        actual = [Call("complex", {"data": {"key": "other"}})]
        expected = [ExpectedCall("complex", {"data": [{"key": "value"}]})]
        result = check_case(actual, expected, funcs)
        assert result.code == "value_mismatch"

    def test_array_parameter(self):
        item_param = Parameter(type="integer")
        array_param = Parameter(type="array", items=item_param)
        func = FunctionSpec(name="sum", parameters={"nums": array_param})
        funcs = {"sum": func}
        actual = [Call("sum", {"nums": [1, 2, 3]})]
        expected = [ExpectedCall("sum", {"nums": [[1, 2, 3], [4, 5, 6]]})]
        result = check_case(actual, expected, funcs)
        assert result.ok is True

    def test_array_mismatch(self):
        item_param = Parameter(type="integer")
        array_param = Parameter(type="array", items=item_param)
        func = FunctionSpec(name="sum", parameters={"nums": array_param})
        funcs = {"sum": func}
        actual = [Call("sum", {"nums": [1, 2, 4]})]
        expected = [ExpectedCall("sum", {"nums": [[1, 2, 3]]})]
        result = check_case(actual, expected, funcs)
        assert result.code == "value_mismatch"

    def test_optional_param_empty_string_allows_omission(self):
        funcs = make_functions()
        actual = [Call("get_weather", {"city": "Paris"})]
        expected = [ExpectedCall("get_weather", {"city": ["Paris"], "unit": [""]})]
        result = check_case(actual, expected, funcs)
        assert result.ok is True

    def test_optional_param_empty_string_but_actual_missing_ok(self):
        # Already covered in test_ok_optional_omitted
        pass


class TestAdditionalBranches:
    def test_error_string_includes_code(self):
        assert str(ToolEvalError("unparseable", "bad input")) == "unparseable: bad input"

    def test_load_functions_array_and_scalar_enums(self):
        text = json.dumps(
            [
                {
                    "name": "f",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "flag": {"type": "boolean", "enum": [True]},
                            "ratio": {"type": "number", "enum": [1.5]},
                        },
                        "required": ["tags"],
                    },
                }
            ]
        )
        funcs = load_functions(text)
        params = funcs["f"].parameters
        assert params["tags"].required is True
        assert params["tags"].items is not None
        assert params["tags"].items.type == "string"
        assert params["flag"].enum == (True,)
        assert params["ratio"].enum == (1.5,)

    @pytest.mark.parametrize(
        "payload",
        [
            {"type": "object", "properties": {"x": {"type": "string", "enum": []}}},
            {"type": "object", "properties": {"x": {"type": "array"}}},
            {"type": "object", "properties": {"x": {"type": "object"}}},
            {"type": "object", "properties": {}, "required": "x"},
        ],
    )
    def test_load_functions_rejects_bad_property_schemas(self, payload):
        with pytest.raises(ToolEvalError) as exc_info:
            load_functions(json.dumps([{"name": "f", "parameters": payload}]))
        assert exc_info.value.code == "unsupported_schema"

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            [1],
            [{"parameters": {"type": "object", "properties": {}}}],
            [{"name": "f"}],
        ],
    )
    def test_load_functions_rejects_bad_function_entries(self, payload):
        with pytest.raises(ToolEvalError) as exc_info:
            load_functions(json.dumps(payload))
        assert exc_info.value.code == "unsupported_schema"

    def test_parse_top_level_scalar(self):
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls("123")
        assert exc_info.value.code == "unparseable"

    def test_parse_array_entry_not_object(self):
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls("[1]")
        assert exc_info.value.code == "unparseable"

    def test_parse_call_missing_name(self):
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls(json.dumps([{"arguments": {}}]))
        assert exc_info.value.code == "unparseable"

    def test_parse_nested_list_too_deep(self):
        nested: list[object] = []
        for _ in range(33):
            nested = [nested]
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls(json.dumps({"name": "f", "arguments": {"x": nested}}))
        assert exc_info.value.code == "too_deep"

    def test_nested_boolean_and_list_and_object_comparisons(self):
        funcs = {
            "f": FunctionSpec(
                name="f",
                parameters={
                    "flag": Parameter(type="boolean"),
                    "nums": Parameter(type="array", items=Parameter(type="integer")),
                    "data": Parameter(
                        type="object",
                        properties={
                            "a": Parameter(type="integer"),
                            "b": Parameter(type="integer"),
                        },
                    ),
                },
            )
        }
        actual = [Call("f", {"flag": True, "nums": [1], "data": {"a": 1}})]
        expected = [ExpectedCall("f", {"flag": [True], "nums": [[1, 2]], "data": [{"b": 1}]})]
        result = check_case(actual, expected, funcs)
        assert result.code == "value_mismatch"

    def test_object_and_array_schema_failures(self):
        funcs = {
            "f": FunctionSpec(
                name="f",
                parameters={
                    "data": Parameter(
                        type="object",
                        properties={"a": Parameter(type="string")},
                        required_props=frozenset({"a"}),
                    ),
                    "nums": Parameter(type="array"),
                },
            )
        }
        assert (
            check_case([Call("f", {"data": "x"})], [ExpectedCall("f", {})], funcs).code
            == "type_mismatch"
        )
        assert (
            check_case([Call("f", {"data": {}})], [ExpectedCall("f", {})], funcs).code
            == "type_mismatch"
        )
        assert (
            check_case([Call("f", {"data": {"a": 1}})], [ExpectedCall("f", {})], funcs).code
            == "type_mismatch"
        )
        assert (
            check_case([Call("f", {"nums": "x"})], [ExpectedCall("f", {})], funcs).code
            == "type_mismatch"
        )

    def test_cli_invalid_min_accuracy_value(self, capsys):
        ret = main(["run", "functions.json", "cases.jsonl", "--min-accuracy", "abc"])
        assert ret == 2
        assert "Invalid min-accuracy" in capsys.readouterr().err

    def test_cli_min_accuracy_out_of_range(self, capsys):
        ret = main(["run", "functions.json", "cases.jsonl", "--min-accuracy", "1.5"])
        assert ret == 2
        assert "between 0 and 1" in capsys.readouterr().err

    def test_cli_unknown_option(self, capsys):
        ret = main(["run", "functions.json", "cases.jsonl", "--unknown"])
        assert ret == 2
        assert "Usage:" in capsys.readouterr().err


class TestRobustness:
    def test_parse_recursion_limit_raises_too_deep(self):
        with pytest.raises(ToolEvalError) as exc_info:
            parse_calls("[" * 5000)
        assert exc_info.value.code == "too_deep"

    def test_huge_integer_argument_type_mismatch(self):
        funcs = make_functions()
        actual = [Call("get_weather", {"city": 10**400})]
        expected = [make_weather_expected()]
        result = check_case(actual, expected, funcs)
        assert result.code == "type_mismatch"

    def test_huge_integer_number_param_does_not_overflow(self):
        funcs = make_functions()
        actual = [Call("get_temp", {"days": 1, "limit": 10**400})]
        expected = [ExpectedCall("get_temp", {"days": [1], "limit": [3.0]})]
        result = check_case(actual, expected, funcs)
        assert result.code == "value_mismatch"

    def test_load_functions_huge_integer_enum(self):
        text = json.dumps(
            [
                {
                    "name": "f",
                    "parameters": {
                        "type": "object",
                        "properties": {"x": {"type": "number", "enum": [10**400]}},
                    },
                }
            ]
        )
        funcs = load_functions(text)
        assert funcs["f"].parameters["x"].enum == (10**400,)

    def test_unknown_function_detail_is_bounded(self):
        long_name = "f" * 1_000
        result = check_case(
            [Call(long_name, {})],
            [ExpectedCall(long_name, {})],
            {},
        )
        assert result.code == "unknown_function"
        assert len(result.detail) <= 200

    def test_unexpected_param_detail_is_bounded(self):
        funcs = make_functions()
        long_param = "p" * 1_000
        actual = [Call("get_weather", {"city": "Paris", long_param: 1})]
        expected = [make_weather_expected()]
        result = check_case(actual, expected, funcs)
        assert result.code == "unexpected_param"
        assert len(result.detail) <= 200
