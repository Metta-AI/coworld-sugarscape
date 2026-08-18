"""Ruleset Studio variant catalog and run-configuration composition."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
import secrets
from typing import Literal

from .config import resolve_episode_config
from .targets import (
    DEFAULT_CATALOG_PATH,
    Target,
    load_target_catalog,
    resolve_seat_targets,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config.json"
DEFAULT_MANIFEST_PATH = ROOT / "coworld_manifest.json"
DEFAULT_VARIANT_ID = "solo-ladder"
LOCAL_VARIANT_ID = "local-default"
TIMESTEP_MIN = 1
TIMESTEP_MAX = 2_000
_CANONICAL_SEED = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_MANIFEST_VARIANT_KINDS: dict[str, Literal["pooled", "fixed"]] = {
    "solo-wealth": "fixed",
    "solo-ladder": "pooled",
    "duo-ladder": "pooled",
    "commonwealth": "fixed",
}
_EXCLUDED_VARIANTS = {"duel-4seat"}


@dataclass(frozen=True, slots=True)
class StudioVariant:
    id: str
    name: str
    description: str
    kind: Literal["pooled", "fixed"]
    game_config: dict[str, object]
    scenarios: tuple[dict[str, object], ...]

    def public_dict(self) -> dict[str, object]:
        modes = ["ranked-preview", "exploration"] if self.kind == "pooled" else ["fixed"]
        context_id = "default" if self.id == LOCAL_VARIANT_ID else self.id
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "modes": modes,
            "context_id": context_id,
            "seats": self.game_config["seats"],
            "timesteps": self.game_config.get("timesteps"),
            "measurement_window": self.game_config.get("measurement_window"),
            "players": deepcopy(self.game_config.get("players") or []),
            "scenarios": [
                {
                    "id": scenario["id"],
                    "context_id": f"{self.id}:{scenario['id']}",
                    "description": scenario.get("description", ""),
                    "targets": deepcopy(scenario.get("targets") or []),
                }
                for scenario in self.scenarios
            ],
        }


class StudioVariantCatalog:
    """Load explicitly classified Studio variants and scoped scenarios."""

    def __init__(self, variants: list[StudioVariant]) -> None:
        self._variants: dict[str, StudioVariant] = {}
        for variant in variants:
            if variant.id in self._variants:
                raise ValueError(f'duplicate studio variant id "{variant.id}"')
            scenario_ids: set[str] = set()
            for scenario in variant.scenarios:
                scenario_id = scenario.get("id")
                if not isinstance(scenario_id, str) or not scenario_id:
                    raise ValueError(f"{variant.id} scenario ids must be non-empty strings")
                if scenario_id in scenario_ids:
                    raise ValueError(
                        f'{variant.id} has duplicate scenario id "{scenario_id}"'
                    )
                scenario_ids.add(scenario_id)
            self._variants[variant.id] = variant
        if DEFAULT_VARIANT_ID not in self._variants:
            raise ValueError(f'default studio variant "{DEFAULT_VARIANT_ID}" is missing')

    @classmethod
    def load(
        cls,
        *,
        manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
        local_config_path: Path | str = DEFAULT_CONFIG_PATH,
    ) -> StudioVariantCatalog:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        local_config = json.loads(Path(local_config_path).read_text(encoding="utf-8"))
        variants = [
            StudioVariant(
                LOCAL_VARIANT_ID,
                "Local default",
                "The repository's quick local development configuration.",
                "fixed",
                local_config,
                (),
            )
        ]
        for raw in manifest.get("variants") or []:
            variant_id = raw.get("id")
            if variant_id in _EXCLUDED_VARIANTS:
                continue
            kind = _MANIFEST_VARIANT_KINDS.get(variant_id)
            if kind is None:
                raise ValueError(f'studio kind is not declared for variant "{variant_id}"')
            game_config = deepcopy(raw["game_config"])
            scenarios = tuple(deepcopy(game_config.get("scenario_pool") or []))
            if kind == "pooled" and not scenarios:
                raise ValueError(f'pooled variant "{variant_id}" has no scenarios')
            if kind == "fixed" and scenarios:
                raise ValueError(f'fixed variant "{variant_id}" cannot have scenarios')
            variants.append(
                StudioVariant(
                    variant_id,
                    str(raw.get("name") or variant_id),
                    str(raw.get("description") or ""),
                    kind,
                    game_config,
                    scenarios,
                )
            )
        return cls(variants)

    def variant(self, variant_id: str) -> StudioVariant:
        try:
            return self._variants[variant_id]
        except KeyError as error:
            raise ValueError(f'unknown studio variant "{variant_id}"') from error

    def scenario(self, variant_id: str, scenario_id: str) -> dict[str, object]:
        variant = self.variant(variant_id)
        for scenario in variant.scenarios:
            if scenario["id"] == scenario_id:
                return deepcopy(scenario)
        raise ValueError(f'unknown scenario "{scenario_id}" for variant "{variant_id}"')

    def public_dict(self) -> dict[str, object]:
        return {
            "default_variant": DEFAULT_VARIANT_ID,
            "variants": [variant.public_dict() for variant in self._variants.values()],
        }


@dataclass(frozen=True, slots=True)
class StudioRunConfig:
    variant_id: str
    mode: Literal["ranked-preview", "exploration", "fixed"]
    seed: str
    scenario_id: str | None
    context_id: str
    engine_config: dict[str, object]
    resolved_config: dict[str, object]
    resolved_targets: tuple[Target, ...]


def compose_run_config(
    catalog: StudioVariantCatalog,
    *,
    variant_id: str,
    mode: Literal["ranked-preview", "exploration", "fixed"],
    seed: str | None,
    scenario_id: str | None = None,
    timesteps: int | None = None,
    seed_source: Callable[[], int] | None = None,
    target_catalog_path: Path | str = DEFAULT_CATALOG_PATH,
) -> StudioRunConfig:
    """Compose one Studio request while keeping seed text lossless at its boundary."""

    variant = catalog.variant(variant_id)
    seed_text, seed_value = _resolve_seed(seed, seed_source)
    config = deepcopy(variant.game_config)
    # Platform tokens override declared seats. They have no role in local Play,
    # where the selected variant is the source of arity.
    config.pop("tokens", None)
    config["seed"] = seed_value

    if variant.kind == "pooled":
        if mode == "ranked-preview":
            if scenario_id is not None or timesteps is not None:
                raise ValueError("ranked-preview derives its scenario and timesteps")
        elif mode == "exploration":
            if scenario_id is None:
                raise ValueError("exploration requires a scenario")
            scenario = deepcopy(catalog.scenario(variant_id, scenario_id))
            if timesteps is not None:
                overrides = scenario.get("config_overrides")
                if isinstance(overrides, dict):
                    overrides.pop("timesteps", None)
                config["timesteps"] = _validate_timesteps(timesteps)
            config["scenario_pool"] = [scenario]
        else:
            raise ValueError(
                f'pooled variant "{variant_id}" requires ranked-preview or exploration'
            )
    else:
        if mode != "fixed":
            raise ValueError(f'fixed variant "{variant_id}" requires fixed mode')
        if scenario_id is not None:
            raise ValueError("fixed variants do not accept a scenario")
        if timesteps is not None:
            config["timesteps"] = _validate_timesteps(timesteps)

    resolved = resolve_episode_config(config)
    selected_scenario = scenario_id
    if variant.kind == "pooled" and mode == "ranked-preview":
        selected_scenario = variant.scenarios[int(resolved["scenario_index"])]["id"]
    context_id = (
        f"{variant_id}:{selected_scenario}"
        if selected_scenario is not None
        else "default" if variant_id == LOCAL_VARIANT_ID else variant_id
    )
    seats = int(resolved["seats"])
    targets = resolve_seat_targets(
        resolved.get("targets"),
        seats=seats,
        measurement_window=int(resolved["measurement_window"]),
        catalog=load_target_catalog(target_catalog_path),
    )
    return StudioRunConfig(
        variant_id,
        mode,
        seed_text,
        selected_scenario,
        context_id,
        config,
        resolved,
        targets,
    )


def _resolve_seed(
    seed: str | None,
    seed_source: Callable[[], int] | None,
) -> tuple[str, int]:
    if seed is None:
        value = (seed_source or (lambda: secrets.randbits(63)))()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("seed source must return a non-negative integer")
        return str(value), value
    if not isinstance(seed, str) or not _CANONICAL_SEED.fullmatch(seed):
        raise ValueError("seed must be a canonical non-negative decimal string")
    return seed, int(seed)


def _validate_timesteps(timesteps: int) -> int:
    if (
        isinstance(timesteps, bool)
        or not isinstance(timesteps, int)
        or not TIMESTEP_MIN <= timesteps <= TIMESTEP_MAX
    ):
        raise ValueError(
            f"timesteps must be an integer from {TIMESTEP_MIN} to {TIMESTEP_MAX}"
        )
    return timesteps
