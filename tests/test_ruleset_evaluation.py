from __future__ import annotations

import math
import random

import pytest

from coworld.ruleset import (
    FEATURE_NAMES,
    FeatureContext,
    compile_ruleset,
    evaluate_reference,
    validate_ruleset,
)


def _compile_expression(expression: object):
    result = validate_ruleset({"version": 1, "movement": [{"score": expression}]})
    assert result.valid, [str(error) for error in result.errors]
    compiled = compile_ruleset(result)
    assert compiled.movement is not None
    return compiled.movement[0].score.evaluate


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (["+", 1, 2, 3], 6),
        (["-", 10, 3, 2], 5),
        (["*", 2, 3, 4], 24),
        (["/", 100, 2, 5], 10),
        (["/", 100, 0, 5], 0),
        (["min", 3, -2, 4], -2),
        (["max", 3, -2, 4], 4),
        (["abs", -3], 3),
        (["neg", 3], -3),
        (["pow", -2, 3], 0),
        (["pow", 2, 20], 256),
        (["pow", 2, -20], 1 / 256),
        (["pow", 0, -1], 0),
        (["<", 1, 2], 1),
        (["<=", 2, 2], 1),
        ([">", 2, 1], 1),
        ([">=", 1, 2], 0),
        (["==", 2, 2], 1),
        (["!=", 2, 2], 0),
        (["and", 1, -1, 2], 1),
        (["and", 1, 0, 2], 0),
        (["or", 0, 0, 2], 1),
        (["not", 0], 1),
        (["if", ["<", 1, 2], 7, 9], 7),
    ],
)
def test_operator_semantics(expression: object, expected: float) -> None:
    context = FeatureContext()
    assert _compile_expression(expression)(context) == pytest.approx(expected)
    assert evaluate_reference(expression, {}) == pytest.approx(expected)


def test_non_finite_inputs_and_results_become_zero() -> None:
    context = FeatureContext()
    context.set_feature("agent.sugar", math.inf)
    get_sugar = _compile_expression(["get", "agent.sugar"])
    overflow = _compile_expression(["*", 1e308, 1e308])
    assert get_sugar(context) == 0
    assert overflow(context) == 0
    assert evaluate_reference(["*", 1e308, 1e308], {}) == 0


def test_boolean_operators_and_if_short_circuit() -> None:
    class ExplodingContext(FeatureContext):
        def value(self, index: int) -> float:
            raise AssertionError("short-circuited feature was evaluated")

    context = ExplodingContext()
    assert _compile_expression(["and", 0, ["get", "agent.sugar"]])(context) == 0
    assert _compile_expression(["or", 1, ["get", "agent.sugar"]])(context) == 1
    assert _compile_expression(["if", 1, 7, ["get", "agent.sugar"]])(context) == 7


def test_feature_context_reuses_backing_storage() -> None:
    context = FeatureContext()
    storage_id = id(context._values)
    context.set_agent_features(
        sugar=1,
        spice=2,
        wealth=3,
        sugar_metabolism=4,
        spice_metabolism=5,
        vision=6,
        movement=7,
        age=8,
        ttl=9,
        mrs=10,
    )
    context.set_cell_features(
        sugar=11,
        spice=12,
        pollution=13,
        distance=14,
        occupied=1,
        prey_wealth=15,
        welfare=16,
    )
    context.set_world_features(timestep=17, population=18, gini=0.4, mean_wealth=20)
    assert id(context._values) == storage_id
    for index, feature in enumerate(FEATURE_NAMES):
        expected = context.value(index)
        assert _compile_expression(["get", feature])(context) == expected


def test_decision_list_is_evaluated_per_candidate_top_down() -> None:
    ruleset = {
        "version": 1,
        "movement": [
            {"if": [">", ["get", "cell.pollution"], 5], "score": ["neg", ["get", "cell.pollution"]]},
            {"score": ["get", "cell.welfare"]},
        ],
    }
    compiled = compile_ruleset(ruleset)
    context = FeatureContext()
    context.set_cell_features(sugar=0, spice=0, pollution=8, distance=1, occupied=0, prey_wealth=0, welfare=10)
    assert compiled.score_cell(context) == -8
    context.set_cell_features(sugar=0, spice=0, pollution=2, distance=1, occupied=0, prey_wealth=0, welfare=10)
    assert compiled.score_cell(context) == 10


def test_traits_only_ruleset_does_not_compile_a_movement_program() -> None:
    compiled = compile_ruleset({"version": 1, "traits": {"trade": 0.75}})
    assert compiled.traits.trade == 0.75
    assert compiled.movement is None
    with pytest.raises(RuntimeError, match="stock ranking"):
        compiled.score_cell(FeatureContext())


def test_compiler_matches_reference_evaluator_on_generated_trees() -> None:
    generator = random.Random(903)
    for _ in range(300):
        expression = _random_expression(generator, depth=0)
        features = {name: generator.uniform(-20, 20) for name in FEATURE_NAMES}
        context = FeatureContext()
        context.update(features)
        evaluator = _compile_expression(expression)
        assert evaluator(context) == pytest.approx(evaluate_reference(expression, features), nan_ok=False)


def _random_expression(generator: random.Random, depth: int) -> object:
    if depth >= 3 or generator.random() < 0.3:
        if generator.random() < 0.5:
            return generator.uniform(-5, 5)
        return ["get", generator.choice(FEATURE_NAMES)]

    operator = generator.choice(
        ["+", "-", "*", "/", "min", "max", "abs", "neg", "pow", "<", "<=", ">", ">=", "==", "!=", "and", "or", "not", "if"]
    )
    if operator in {"abs", "neg", "not"}:
        return [operator, _random_expression(generator, depth + 1)]
    if operator == "if":
        return [operator] + [_random_expression(generator, depth + 1) for _ in range(3)]
    arity = generator.randint(2, 4) if operator in {"+", "-", "*", "/", "min", "max", "and", "or"} else 2
    return [operator] + [_random_expression(generator, depth + 1) for _ in range(arity)]
