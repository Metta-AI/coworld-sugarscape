"""Episode configuration and deterministic scenario resolution."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import secrets
from typing import Callable, Mapping

from sugarscape.sugarscape import verifyConfiguration

from .ruleset import RulesetLimits
from .seats import parse_trait_ranges


_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "sugarscape" / "config.json"
_COWORLD_KEYS = {
    "measurement_window",
    "player_connect_timeout_seconds",
    "players",
    "replay_histogram_interval",
    "ruleset_limits",
    "scenario_pool",
    "scenario_index",
    "seats",
    "targets",
    "tokens",
    "trait_ranges",
}
_FORCED_DTL_OPTIONS: dict[str, object] = {
    "agentDecisionModel": None,
    "agentDecisionModels": ["ruleset"],
    "agentLeader": False,
    "agentLogfile": None,
    "debugMode": ["none"],
    "headlessMode": True,
    "keepAliveAtEnd": False,
    "logfile": None,
    "profileMode": False,
    "screenshots": False,
}


def load_dtl_defaults() -> dict[str, object]:
    """Load a fresh copy of the pinned upstream Sugarscape defaults."""

    with _DEFAULT_CONFIG_PATH.open(encoding="utf-8") as config_file:
        return json.load(config_file)["sugarscapeOptions"]


def resolve_episode_config(
    raw_config: Mapping[str, object],
    *,
    seed_source: Callable[[], int] | None = None,
) -> dict[str, object]:
    """Merge defaults, resolve the episode seed, and select one scenario.

    Scenario selection is arithmetic (``seed % len(pool)``) and therefore does
    not consume the process-global DTL random stream.
    """

    config = load_dtl_defaults()
    config.update(deepcopy(dict(raw_config)))
    seed = config.get("seed", -1)
    if seed == -1:
        source = seed_source or (lambda: secrets.randbits(63))
        seed = source()
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be -1, absent, or a non-negative integer")
    config["seed"] = seed

    pool = config.get("scenario_pool")
    if pool is not None:
        if not isinstance(pool, list) or not pool:
            raise ValueError("scenario_pool must be a non-empty array")
        scenario_index = seed % len(pool)
        scenario = pool[scenario_index]
        if not isinstance(scenario, Mapping):
            raise ValueError(f"scenario_pool[{scenario_index}] must be an object")
        overrides = scenario.get("config_overrides", {})
        if not isinstance(overrides, Mapping):
            raise ValueError(f"scenario_pool[{scenario_index}].config_overrides must be an object")
        if "seed" in overrides or "scenario_pool" in overrides:
            raise ValueError("scenario config_overrides cannot replace seed or scenario_pool")
        config.update(deepcopy(dict(overrides)))
        config["scenario_index"] = scenario_index
        if "targets" in scenario:
            config["targets"] = deepcopy(scenario["targets"])
    else:
        config["scenario_index"] = None

    seats = config.get("seats", 1)
    if isinstance(seats, bool) or not isinstance(seats, int) or seats <= 0:
        raise ValueError("seats must be a positive integer")
    starting_agents = config.get("startingAgents")
    if isinstance(starting_agents, bool) or not isinstance(starting_agents, int):
        raise ValueError("startingAgents must be an integer")
    if starting_agents % seats != 0:
        raise ValueError("startingAgents must be divisible by seats")
    replacements = config.get("agentReplacements")
    if isinstance(replacements, bool) or not isinstance(replacements, int):
        raise ValueError("agentReplacements must be an integer")
    if replacements > starting_agents:
        raise ValueError(
            "agentReplacements cannot exceed startingAgents because every replacement needs a dead agent seat"
        )
    config["seats"] = seats

    window = config.get("measurement_window", 100)
    if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
        raise ValueError("measurement_window must be a positive integer")
    config["measurement_window"] = window
    connect_timeout = config.get("player_connect_timeout_seconds", 180)
    if (
        isinstance(connect_timeout, bool)
        or not isinstance(connect_timeout, (int, float))
        or connect_timeout < 0
    ):
        raise ValueError("player_connect_timeout_seconds must be a non-negative number")
    config["player_connect_timeout_seconds"] = float(connect_timeout)
    replay_interval = config.get("replay_histogram_interval", 10)
    if isinstance(replay_interval, bool) or not isinstance(replay_interval, int) or replay_interval <= 0:
        raise ValueError("replay_histogram_interval must be a positive integer")
    config["replay_histogram_interval"] = replay_interval
    parse_trait_ranges(config.get("trait_ranges"))
    _parse_ruleset_limits(config.get("ruleset_limits"))
    return config


def build_dtl_config(resolved_config: Mapping[str, object]) -> dict[str, object]:
    """Produce the isolated DTL configuration used to construct a world."""

    config = {
        key: deepcopy(value)
        for key, value in resolved_config.items()
        if key not in _COWORLD_KEYS
    }
    config.update(deepcopy(_FORCED_DTL_OPTIONS))
    # DTL validation sorts many lists in place. Keep that mutation isolated.
    return verifyConfiguration(config)


def ruleset_limits(config: Mapping[str, object]) -> RulesetLimits:
    """Return validated submission limits from a resolved config."""

    return _parse_ruleset_limits(config.get("ruleset_limits"))


def _parse_ruleset_limits(raw: object) -> RulesetLimits:
    if raw is None:
        return RulesetLimits()
    if not isinstance(raw, Mapping):
        raise ValueError("ruleset_limits must be an object")
    unknown = set(raw) - {"max_nodes", "max_depth", "max_bytes"}
    if unknown:
        raise ValueError(f"unknown ruleset_limits entries: {', '.join(sorted(unknown))}")
    values = {
        name: raw.get(name, default)
        for name, default in (
            ("max_nodes", 256),
            ("max_depth", 16),
            ("max_bytes", 32_768),
        )
    }
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"ruleset_limits.{name} must be a positive integer")
    return RulesetLimits(**values)
