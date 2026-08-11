from __future__ import annotations

import json
from pathlib import Path

import pytest

from coworld.ruleset import (
    FEATURE_NAMES,
    RulesetLimits,
    RulesetValidationError,
    compile_ruleset,
    parse_ruleset,
    validate_ruleset,
)


FIXTURES = Path(__file__).parent / "fixtures" / "rulesets"


@pytest.mark.parametrize("filename", ["null.json", "greedy.json", "traits-only.json", "macro-feedback.json"])
def test_golden_rulesets_validate_and_compile(filename: str) -> None:
    result = parse_ruleset((FIXTURES / filename).read_bytes())
    assert result.valid, [str(error) for error in result.errors]
    compiled = compile_ruleset(result)
    assert compiled.node_count == result.node_count


@pytest.mark.parametrize("value", [None, {}, {"version": 1}])
def test_null_ruleset_forms(value: object) -> None:
    result = validate_ruleset(value)
    assert result.valid
    assert compile_ruleset(result).is_null


def test_behavior_requires_version_one() -> None:
    missing = validate_ruleset({"traits": {"trade": 1}})
    unsupported = validate_ruleset({"version": 2, "traits": {"trade": 1}})
    boolean = validate_ruleset({"version": True, "traits": {"trade": 1}})
    floating = validate_ruleset({"version": 1.0, "traits": {"trade": 1}})
    assert "$.version: version is required" in str(missing.errors[0])
    assert "only SugarLang version 1" in str(unsupported.errors[0])
    assert "only SugarLang version 1" in str(boolean.errors[0])
    assert "only SugarLang version 1" in str(floating.errors[0])


def test_unknown_fields_and_traits_have_actionable_paths() -> None:
    result = validate_ruleset(
        {
            "version": 1,
            "mystery": 1,
            "traits": {"kindness": 1, "trade": "yes"},
        }
    )
    messages = [str(error) for error in result.errors]
    assert "$.mystery: unknown ruleset field" in messages
    assert "$.traits.kindness: unknown trait" in messages
    assert "$.traits.trade: trait value must be a finite number" in messages


def test_movement_structure_errors_are_collected() -> None:
    result = validate_ruleset(
        {
            "version": 1,
            "movement": [
                {"if": ["wat", 1], "extra": 2},
                {"if": ["get", "world.unknown"], "score": []},
            ],
        }
    )
    messages = [str(error) for error in result.errors]
    assert '$.movement[0].extra: unknown movement-rule field' in messages
    assert '$.movement[0].score: movement rule requires a score expression' in messages
    assert '$.movement[0].if[0]: unknown operator "wat"' in messages
    assert '$.movement[1].score: operator array cannot be empty' in messages
    assert '$.movement[1].if[1]: unknown feature "world.unknown"' in messages
    assert '$.movement[-1]: final movement rule must omit "if"' in messages


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        (["+", 1], 'operator "+" expects at least 2 arguments'),
        (["-", 1], 'operator "-" expects at least 2 arguments'),
        (["/", 1], 'operator "/" expects at least 2 arguments'),
        (["abs", 1, 2], 'operator "abs" expects exactly 1 argument'),
        (["pow", 1], 'operator "pow" expects exactly 2 arguments'),
        (["if", 1, 2], 'operator "if" expects exactly 3 arguments'),
        (["get", "agent.sugar", 2], 'operator "get" expects exactly 1 argument'),
    ],
)
def test_operator_arities(expression: object, message: str) -> None:
    result = validate_ruleset({"version": 1, "movement": [{"score": expression}]})
    assert any(message in str(error) for error in result.errors)


@pytest.mark.parametrize("feature", FEATURE_NAMES)
def test_every_feature_is_accepted(feature: str) -> None:
    result = validate_ruleset({"version": 1, "movement": [{"score": ["get", feature]}]})
    assert result.valid


def test_node_budget_accepts_boundary_and_rejects_one_over() -> None:
    at_limit = ["+"] + [1] * 255
    over_limit = ["+"] + [1] * 256
    accepted = validate_ruleset({"version": 1, "movement": [{"score": at_limit}]})
    rejected = validate_ruleset({"version": 1, "movement": [{"score": over_limit}]})
    assert accepted.valid
    assert accepted.node_count == 256
    assert rejected.node_count == 257
    assert "expression node budget exceeded: 257 > 256" in str(rejected.errors[-1])


def test_get_counts_as_one_expression_node() -> None:
    result = validate_ruleset({"version": 1, "movement": [{"score": ["get", "cell.welfare"]}]})
    assert result.valid
    assert result.node_count == 1


def test_depth_budget_accepts_boundary_and_rejects_one_over() -> None:
    expression: object = 1
    for _ in range(15):
        expression = ["abs", expression]
    accepted = validate_ruleset({"version": 1, "movement": [{"score": expression}]})
    expression = ["abs", expression]
    rejected = validate_ruleset({"version": 1, "movement": [{"score": expression}]})
    assert accepted.valid
    assert any("maximum expression depth 16 exceeded at depth 17" in str(error) for error in rejected.errors)


def test_raw_byte_budget_counts_utf8_and_whitespace() -> None:
    payload = json.dumps({"version": 1, "movement": [{"score": 1}]}) + "   "
    exact = len(payload.encode("utf-8"))
    assert parse_ruleset(payload, RulesetLimits(max_bytes=exact)).valid
    result = parse_ruleset(payload, RulesetLimits(max_bytes=exact - 1))
    assert not result.valid
    assert f"ruleset is {exact} bytes; maximum is {exact - 1} bytes" in str(result.errors[0])


@pytest.mark.parametrize(
    "payload",
    [b"\xff", "{", '{"version": NaN}', '{"version": Infinity}'],
)
def test_parser_rejects_invalid_json(payload: str | bytes) -> None:
    result = parse_ruleset(payload)
    assert not result.valid
    assert result.errors[0].path == "$"


@pytest.mark.parametrize(
    "literal",
    [True, False, "1", None, float("nan"), float("inf"), pytest.param(10**4_000, id="oversized-integer")],
)
def test_invalid_literals_are_rejected(literal: object) -> None:
    result = validate_ruleset({"version": 1, "movement": [{"score": literal}]})
    assert not result.valid


def test_compile_raises_with_all_validation_errors() -> None:
    result = validate_ruleset({"version": 3, "movement": []})
    with pytest.raises(RulesetValidationError) as error:
        compile_ruleset(result)
    assert len(error.value.errors) == 2
