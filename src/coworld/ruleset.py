"""SugarLang parsing, validation, and allocation-free expression evaluation.

SugarLang programs are data, never executable player code. Validation is the
trust boundary: compiled expressions only accept validated trees and evaluate
against a fixed-size, reusable :class:`FeatureContext`.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Callable, Mapping, Sequence


FEATURE_NAMES = (
    "agent.sugar",
    "agent.spice",
    "agent.wealth",
    "agent.sugarMetabolism",
    "agent.spiceMetabolism",
    "agent.vision",
    "agent.movement",
    "agent.age",
    "agent.ttl",
    "agent.mrs",
    "cell.sugar",
    "cell.spice",
    "cell.pollution",
    "cell.distance",
    "cell.occupied",
    "cell.preyWealth",
    "cell.welfare",
    "world.timestep",
    "world.population",
    "world.gini",
    "world.meanWealth",
)
FEATURE_INDEX = {name: index for index, name in enumerate(FEATURE_NAMES)}
TRAIT_NAMES = ("aggression", "trade", "lending", "fertility")

_NARY_OPERATORS = {"+", "-", "*", "/", "min", "max", "and", "or"}
_UNARY_OPERATORS = {"abs", "neg", "not"}
_BINARY_OPERATORS = {"pow", "<", "<=", ">", ">=", "==", "!="}
_TERNARY_OPERATORS = {"if"}
_OPERATORS = _NARY_OPERATORS | _UNARY_OPERATORS | _BINARY_OPERATORS | _TERNARY_OPERATORS | {"get"}

Evaluator = Callable[["FeatureContext"], float]


@dataclass(frozen=True, slots=True)
class RulesetLimits:
    """Submission limits enforced before a ruleset is compiled."""

    max_nodes: int = 256
    max_depth: int = 16
    max_bytes: int = 32_768


DEFAULT_LIMITS = RulesetLimits()


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One actionable SugarLang validation failure."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Normalized ruleset data and all validation findings."""

    normalized: dict[str, object] | None
    errors: tuple[ValidationIssue, ...]
    node_count: int
    byte_count: int

    @property
    def valid(self) -> bool:
        return not self.errors


class RulesetValidationError(ValueError):
    """Raised when compilation is requested for an invalid ruleset."""

    def __init__(self, errors: Sequence[ValidationIssue]):
        self.errors = tuple(errors)
        super().__init__("; ".join(str(error) for error in self.errors))


@dataclass(frozen=True, slots=True)
class TraitOverrides:
    """Unclamped submitted trait values; variants clamp them at agent spawn."""

    aggression: float | None = None
    trade: float | None = None
    lending: float | None = None
    fertility: float | None = None


@dataclass(frozen=True, slots=True)
class CompiledExpression:
    """A validated expression compiled to a reusable closure."""

    evaluate: Evaluator


@dataclass(frozen=True, slots=True)
class CompiledMovementRule:
    """One condition and score in a compiled movement decision list."""

    condition: CompiledExpression | None
    score: CompiledExpression


@dataclass(frozen=True, slots=True)
class CompiledRuleset:
    """A compiled SugarLang submission."""

    normalized: dict[str, object] | None
    traits: TraitOverrides
    movement: tuple[CompiledMovementRule, ...] | None
    node_count: int
    byte_count: int

    @property
    def is_null(self) -> bool:
        return self.movement is None and self.traits == TraitOverrides()

    def score_cell(self, context: FeatureContext) -> float:
        """Evaluate the first matching movement rule for one candidate cell."""

        if self.movement is None:
            raise RuntimeError("null and traits-only rulesets use DTL's stock ranking path")
        for rule in self.movement:
            if rule.condition is None or rule.condition.evaluate(context) != 0:
                return rule.score.evaluate(context)
        raise RuntimeError("validated movement lists always end with an unconditional rule")


class FeatureContext:
    """Fixed-size feature storage reused across candidate-cell evaluations."""

    __slots__ = ("_values",)

    def __init__(self) -> None:
        self._values = [0.0] * len(FEATURE_NAMES)

    def value(self, index: int) -> float:
        """Return a feature by its compiler-resolved index."""

        return self._values[index]

    def set_feature(self, name: str, value: float) -> None:
        """Set one known feature, primarily for tests and non-hot-path setup."""

        self._values[FEATURE_INDEX[name]] = _finite(value)

    def update(self, features: Mapping[str, float]) -> None:
        """Set several known features without replacing the backing storage."""

        for name, value in features.items():
            self.set_feature(name, value)

    def set_agent_features(
        self,
        *,
        sugar: float,
        spice: float,
        wealth: float,
        sugar_metabolism: float,
        spice_metabolism: float,
        vision: float,
        movement: float,
        age: float,
        ttl: float,
        mrs: float,
    ) -> None:
        """Populate features memoized once for an agent's movement decision."""

        values = self._values
        values[0] = _finite(sugar)
        values[1] = _finite(spice)
        values[2] = _finite(wealth)
        values[3] = _finite(sugar_metabolism)
        values[4] = _finite(spice_metabolism)
        values[5] = _finite(vision)
        values[6] = _finite(movement)
        values[7] = _finite(age)
        values[8] = _finite(ttl)
        values[9] = _finite(mrs)

    def set_cell_features(
        self,
        *,
        sugar: float,
        spice: float,
        pollution: float,
        distance: float,
        occupied: float,
        prey_wealth: float,
        welfare: float,
    ) -> None:
        """Overwrite the candidate-cell slots before one score evaluation."""

        values = self._values
        values[10] = _finite(sugar)
        values[11] = _finite(spice)
        values[12] = _finite(pollution)
        values[13] = _finite(distance)
        values[14] = _finite(occupied)
        values[15] = _finite(prey_wealth)
        values[16] = _finite(welfare)

    def set_world_features(
        self,
        *,
        timestep: float,
        population: float,
        gini: float,
        mean_wealth: float,
    ) -> None:
        """Populate the features memoized once at the start of a tick."""

        values = self._values
        values[17] = _finite(timestep)
        values[18] = _finite(population)
        values[19] = _finite(gini)
        values[20] = _finite(mean_wealth)


class _ExpressionValidator:
    def __init__(self, limits: RulesetLimits, errors: list[ValidationIssue]):
        self.limits = limits
        self.errors = errors
        self.node_count = 0

    def validate(self, expression: object, path: str, depth: int = 1) -> None:
        self.node_count += 1
        if depth > self.limits.max_depth:
            self.errors.append(
                ValidationIssue(path, f"maximum expression depth {self.limits.max_depth} exceeded at depth {depth}")
            )
            return

        if _is_number(expression):
            if not _number_is_finite(expression):
                self.errors.append(ValidationIssue(path, "numeric literals must be finite"))
            return
        if not isinstance(expression, list):
            self.errors.append(ValidationIssue(path, "expression must be a number or an operator array"))
            return
        if not expression:
            self.errors.append(ValidationIssue(path, "operator array cannot be empty"))
            return

        operator = expression[0]
        if not isinstance(operator, str):
            self.errors.append(ValidationIssue(f"{path}[0]", "operator must be a string"))
            return
        if operator not in _OPERATORS:
            self.errors.append(ValidationIssue(f"{path}[0]", f'unknown operator "{operator}"'))
            return

        argument_count = len(expression) - 1
        if operator == "get":
            if argument_count != 1:
                self.errors.append(ValidationIssue(path, 'operator "get" expects exactly 1 argument'))
                return
            feature = expression[1]
            if not isinstance(feature, str):
                self.errors.append(ValidationIssue(f"{path}[1]", "feature name must be a string"))
            elif feature not in FEATURE_INDEX:
                self.errors.append(ValidationIssue(f"{path}[1]", f'unknown feature "{feature}"'))
            return

        if operator in _NARY_OPERATORS and argument_count < 2:
            self.errors.append(ValidationIssue(path, f'operator "{operator}" expects at least 2 arguments'))
        elif operator in _UNARY_OPERATORS and argument_count != 1:
            self.errors.append(ValidationIssue(path, f'operator "{operator}" expects exactly 1 argument'))
        elif operator in _BINARY_OPERATORS and argument_count != 2:
            self.errors.append(ValidationIssue(path, f'operator "{operator}" expects exactly 2 arguments'))
        elif operator in _TERNARY_OPERATORS and argument_count != 3:
            self.errors.append(ValidationIssue(path, f'operator "{operator}" expects exactly 3 arguments'))

        for index, argument in enumerate(expression[1:], start=1):
            self.validate(argument, f"{path}[{index}]", depth + 1)


def parse_ruleset(payload: str | bytes, limits: RulesetLimits = DEFAULT_LIMITS) -> ValidationResult:
    """Parse and validate a UTF-8 JSON SugarLang submission."""

    if isinstance(payload, bytes):
        byte_count = len(payload)
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            return ValidationResult(None, (ValidationIssue("$", f"ruleset is not valid UTF-8: {error}"),), 0, byte_count)
    else:
        text = payload
        byte_count = len(text.encode("utf-8"))

    if byte_count > limits.max_bytes:
        return _oversized_result(byte_count, limits)
    try:
        value = json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError, RecursionError) as error:
        return ValidationResult(None, (ValidationIssue("$", f"invalid JSON: {error}"),), 0, byte_count)
    return validate_ruleset(value, limits, encoded_size=byte_count)


def validate_ruleset(
    value: object,
    limits: RulesetLimits = DEFAULT_LIMITS,
    *,
    encoded_size: int | None = None,
) -> ValidationResult:
    """Validate already-decoded SugarLang data and return all findings."""

    errors: list[ValidationIssue] = []
    byte_count = encoded_size
    if byte_count is None:
        try:
            byte_count = len(_canonical_json(value))
        except (TypeError, ValueError, RecursionError) as error:
            return ValidationResult(None, (ValidationIssue("$", f"ruleset is not JSON data: {error}"),), 0, 0)
    if byte_count > limits.max_bytes:
        errors.append(
            ValidationIssue("$", f"ruleset is {byte_count} bytes; maximum is {limits.max_bytes} bytes")
        )

    if value is None:
        return ValidationResult(None, tuple(errors), 0, byte_count)
    if not isinstance(value, dict):
        errors.append(ValidationIssue("$", "ruleset must be an object or null"))
        return ValidationResult(None, tuple(errors), 0, byte_count)

    allowed_keys = {"version", "traits", "movement"}
    for key in sorted(value.keys(), key=str):
        if not isinstance(key, str):
            errors.append(ValidationIssue("$", "ruleset object keys must be strings"))
        elif key not in allowed_keys:
            errors.append(ValidationIssue(f"$.{key}", "unknown ruleset field"))

    has_behavior = "traits" in value or "movement" in value
    version = value.get("version")
    if has_behavior and "version" not in value:
        errors.append(ValidationIssue("$.version", "version is required when traits or movement is present"))
    elif "version" in value and (type(version) is not int or version != 1):
        errors.append(ValidationIssue("$.version", "only SugarLang version 1 is supported"))

    _validate_traits(value.get("traits"), "traits" in value, errors)

    expression_validator = _ExpressionValidator(limits, errors)
    _validate_movement(value.get("movement"), "movement" in value, expression_validator, errors)
    if expression_validator.node_count > limits.max_nodes:
        errors.append(
            ValidationIssue(
                "$.movement",
                f"expression node budget exceeded: {expression_validator.node_count} > {limits.max_nodes}",
            )
        )

    normalized = None
    if not errors:
        normalized = json.loads(_canonical_json(value))
    return ValidationResult(normalized, tuple(errors), expression_validator.node_count, byte_count)


def compile_ruleset(
    value: object | ValidationResult,
    limits: RulesetLimits = DEFAULT_LIMITS,
) -> CompiledRuleset:
    """Validate and compile a ruleset, raising on invalid input."""

    result = value if isinstance(value, ValidationResult) else validate_ruleset(value, limits)
    if not result.valid:
        raise RulesetValidationError(result.errors)

    normalized = result.normalized
    if normalized is None:
        return CompiledRuleset(None, TraitOverrides(), None, result.node_count, result.byte_count)

    traits_data = normalized.get("traits", {})
    assert isinstance(traits_data, dict)
    traits = TraitOverrides(**{name: float(traits_data[name]) for name in TRAIT_NAMES if name in traits_data})

    movement_data = normalized.get("movement")
    movement = None
    if movement_data is not None:
        assert isinstance(movement_data, list)
        compiled_rules: list[CompiledMovementRule] = []
        for rule in movement_data:
            assert isinstance(rule, dict)
            condition = CompiledExpression(_compile_expression(rule["if"])) if "if" in rule else None
            compiled_rules.append(
                CompiledMovementRule(condition, CompiledExpression(_compile_expression(rule["score"])))
            )
        movement = tuple(compiled_rules)

    return CompiledRuleset(normalized, traits, movement, result.node_count, result.byte_count)


def evaluate_reference(expression: object, features: Mapping[str, float]) -> float:
    """Evaluate a validated expression directly for compiler-equivalence tests."""

    if _is_number(expression):
        return _finite(float(expression))
    if not isinstance(expression, list) or not expression:
        return 0.0
    operator = expression[0]
    if operator == "get":
        feature = expression[1]
        return _finite(features.get(feature, 0.0)) if isinstance(feature, str) else 0.0
    arguments = expression[1:]

    if operator == "and":
        for argument in arguments:
            if evaluate_reference(argument, features) == 0:
                return 0.0
        return 1.0
    if operator == "or":
        for argument in arguments:
            if evaluate_reference(argument, features) != 0:
                return 1.0
        return 0.0
    if operator == "if":
        branch = arguments[1] if evaluate_reference(arguments[0], features) != 0 else arguments[2]
        return evaluate_reference(branch, features)

    values = [evaluate_reference(argument, features) for argument in arguments]
    return _apply_operator(operator, values)


def _validate_traits(value: object, present: bool, errors: list[ValidationIssue]) -> None:
    if not present:
        return
    if not isinstance(value, dict):
        errors.append(ValidationIssue("$.traits", "traits must be an object"))
        return
    for key in sorted(value.keys(), key=str):
        path = f"$.traits.{key}"
        if not isinstance(key, str) or key not in TRAIT_NAMES:
            errors.append(ValidationIssue(path, "unknown trait"))
            continue
        trait_value = value[key]
        if not _is_number(trait_value) or not _number_is_finite(trait_value):
            errors.append(ValidationIssue(path, "trait value must be a finite number"))


def _validate_movement(
    value: object,
    present: bool,
    expression_validator: _ExpressionValidator,
    errors: list[ValidationIssue],
) -> None:
    if not present:
        return
    if not isinstance(value, list):
        errors.append(ValidationIssue("$.movement", "movement must be an array"))
        return
    if not value:
        errors.append(ValidationIssue("$.movement", "movement must contain at least one rule"))
        return

    for index, rule in enumerate(value):
        path = f"$.movement[{index}]"
        if not isinstance(rule, dict):
            errors.append(ValidationIssue(path, "movement rule must be an object"))
            continue
        for key in sorted(rule.keys(), key=str):
            if not isinstance(key, str) or key not in {"if", "score"}:
                errors.append(ValidationIssue(f"{path}.{key}", "unknown movement-rule field"))
        if "score" not in rule:
            errors.append(ValidationIssue(f"{path}.score", "movement rule requires a score expression"))
        else:
            expression_validator.validate(rule["score"], f"{path}.score")
        if "if" in rule:
            expression_validator.validate(rule["if"], f"{path}.if")

    final_rule = value[-1]
    if isinstance(final_rule, dict) and "if" in final_rule:
        errors.append(ValidationIssue("$.movement[-1]", 'final movement rule must omit "if"'))


def _compile_expression(expression: object) -> Evaluator:
    if _is_number(expression):
        literal = _finite(float(expression))

        def evaluate_literal(context: FeatureContext) -> float:
            return literal

        return evaluate_literal

    assert isinstance(expression, list) and expression
    operator = expression[0]
    assert isinstance(operator, str)
    if operator == "get":
        index = FEATURE_INDEX[expression[1]]

        def evaluate_feature(context: FeatureContext) -> float:
            return context.value(index)

        return evaluate_feature

    compiled_arguments = tuple(_compile_expression(argument) for argument in expression[1:])
    if operator == "and":
        def evaluate_and(context: FeatureContext) -> float:
            for argument in compiled_arguments:
                if argument(context) == 0:
                    return 0.0
            return 1.0

        return evaluate_and
    if operator == "or":
        def evaluate_or(context: FeatureContext) -> float:
            for argument in compiled_arguments:
                if argument(context) != 0:
                    return 1.0
            return 0.0

        return evaluate_or
    if operator == "if":
        condition, when_true, when_false = compiled_arguments

        def evaluate_if(context: FeatureContext) -> float:
            return when_true(context) if condition(context) != 0 else when_false(context)

        return evaluate_if

    if operator in {"+", "-", "*", "/", "min", "max"}:
        def evaluate_arithmetic(context: FeatureContext) -> float:
            first = compiled_arguments[0](context)
            if operator == "+":
                result = first
                index = 1
                while index < len(compiled_arguments):
                    result += compiled_arguments[index](context)
                    index += 1
                return _finite(result)
            if operator == "-":
                result = first
                index = 1
                while index < len(compiled_arguments):
                    result -= compiled_arguments[index](context)
                    index += 1
                return _finite(result)
            if operator == "*":
                result = first
                index = 1
                while index < len(compiled_arguments):
                    result *= compiled_arguments[index](context)
                    index += 1
                return _finite(result)
            if operator == "/":
                result = first
                index = 1
                while index < len(compiled_arguments):
                    divisor = compiled_arguments[index](context)
                    if divisor == 0:
                        return 0.0
                    result /= divisor
                    index += 1
                return _finite(result)
            result = first
            index = 1
            while index < len(compiled_arguments):
                value = compiled_arguments[index](context)
                if operator == "min" and value < result:
                    result = value
                elif operator == "max" and value > result:
                    result = value
                index += 1
            return result

        return evaluate_arithmetic

    if operator in _UNARY_OPERATORS:
        argument = compiled_arguments[0]
        if operator == "abs":
            def evaluate_abs(context: FeatureContext) -> float:
                return _finite(abs(argument(context)))

            return evaluate_abs
        if operator == "neg":
            def evaluate_neg(context: FeatureContext) -> float:
                return _finite(-argument(context))

            return evaluate_neg

        def evaluate_not(context: FeatureContext) -> float:
            return float(argument(context) == 0)

        return evaluate_not

    left, right = compiled_arguments
    if operator == "pow":
        def evaluate_pow(context: FeatureContext) -> float:
            return _safe_pow(left(context), right(context))

        return evaluate_pow
    if operator == "<":
        return lambda context: float(left(context) < right(context))
    if operator == "<=":
        return lambda context: float(left(context) <= right(context))
    if operator == ">":
        return lambda context: float(left(context) > right(context))
    if operator == ">=":
        return lambda context: float(left(context) >= right(context))
    if operator == "==":
        return lambda context: float(left(context) == right(context))
    return lambda context: float(left(context) != right(context))


def _apply_operator(operator: object, values: Sequence[float]) -> float:
    if operator == "+":
        result = values[0]
        for value in values[1:]:
            result += value
        return _finite(result)
    if operator == "-":
        result = values[0]
        for value in values[1:]:
            result -= value
        return _finite(result)
    if operator == "*":
        result = values[0]
        for value in values[1:]:
            result *= value
        return _finite(result)
    if operator == "/":
        result = values[0]
        for value in values[1:]:
            if value == 0:
                return 0.0
            result /= value
        return _finite(result)
    if operator == "min":
        return min(values)
    if operator == "max":
        return max(values)
    if operator == "abs":
        return _finite(abs(values[0]))
    if operator == "neg":
        return _finite(-values[0])
    if operator == "pow":
        return _safe_pow(values[0], values[1])
    if operator == "<":
        return float(values[0] < values[1])
    if operator == "<=":
        return float(values[0] <= values[1])
    if operator == ">":
        return float(values[0] > values[1])
    if operator == ">=":
        return float(values[0] >= values[1])
    if operator == "==":
        return float(values[0] == values[1])
    if operator == "!=":
        return float(values[0] != values[1])
    if operator == "not":
        return float(values[0] == 0)
    return 0.0


def _safe_pow(base: float, exponent: float) -> float:
    clamped_base = max(base, 0.0)
    clamped_exponent = max(-8.0, min(8.0, exponent))
    try:
        return _finite(clamped_base**clamped_exponent)
    except (OverflowError, ValueError, ZeroDivisionError):
        return 0.0


def _finite(value: float) -> float:
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return 0.0
    return numeric if math.isfinite(numeric) else 0.0


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number_is_finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _oversized_result(byte_count: int, limits: RulesetLimits) -> ValidationResult:
    return ValidationResult(
        None,
        (ValidationIssue("$", f"ruleset is {byte_count} bytes; maximum is {limits.max_bytes} bytes"),),
        0,
        byte_count,
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value} is not allowed")
