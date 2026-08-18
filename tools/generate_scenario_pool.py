#!/usr/bin/env python3
"""Generate the curated solo- and duo-ladder scenario pools.

Run from the repository root. The scenario definitions in this file are the
source of truth; ``--write`` updates only the two ladder pool arrays in the
manifest.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "coworld_manifest.json"
VARIANT_ID = "solo-ladder"
DUO_VARIANT_ID = "duo-ladder"

DUO_COMPANION_TARGETS = {
    "wealth.skewed-gini-0.5": "wealth.egalitarian",
    "wealth.egalitarian": "wealth.skewed-gini-0.5",
    "population.carrying-capacity": "wealth.skewed-gini-0.5",
    "age-at-death.survivorship": "wealth.egalitarian",
    "price.equilibrium": "wealth.skewed-gini-0.5",
    "tribe.convergence": "tribe.diversity",
    "tribe.diversity": "tribe.convergence",
}


FAMILY_ORDER = [
    "wealth-skewed",
    "wealth-egalitarian",
    "capacity",
    "survivorship",
    "price",
    "tribe",
]

# Two hand-tuned worlds per family, carried verbatim from the retired
# 24-scenario pool. config_overrides must not be edited here; packs layer
# deltas on top.
BASE_WORLDS: list[dict[str, object]] = [
    {
        "family": "wealth-skewed",
        "id": "wealth-skewed.twin-peaks",
        "description": "Replacement economy on the classic offset twin-peak sugar landscape.",
        "config_overrides": {
            "startingAgents": 250,
            "agentMaxAge": [60, 100],
            "agentReplacements": 250,
            "agentStartingSugar": [5, 25],
            "agentSugarMetabolism": [1, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [1, 6],
            "agentVision": [1, 6],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 50,
            "environmentHeight": 50,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[15, 35, 4], [35, 15, 4]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["wealth.skewed-gini-0.5"],
    },
    {
        "family": "wealth-skewed",
        "id": "wealth-skewed.scarce-lowland",
        "description": "Dense replacement economy on scarce cap-two lowland terrain.",
        "config_overrides": {
            "startingAgents": 200,
            "agentMaxAge": [60, 100],
            "agentReplacements": 200,
            "agentStartingSugar": [4, 18],
            "agentSugarMetabolism": [2, 5],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [1, 5],
            "agentVision": [1, 4],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 40,
            "environmentHeight": 40,
            "environmentMaxSugar": 2,
            "environmentSugarPeaks": [[10, 30, 2], [30, 10, 2]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["wealth.skewed-gini-0.5"],
    },
    {
        "family": "wealth-egalitarian",
        "id": "wealth-egalitarian.central-plateau",
        "description": "Income-supported replacement economy around a broad central sugar peak.",
        "config_overrides": {
            "startingAgents": 300,
            "agentMaxAge": [35, 50],
            "agentReplacements": 300,
            "agentStartingSugar": [18, 26],
            "agentSugarMetabolism": [2, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [2, 4],
            "agentVision": [4, 7],
            "agentUniversalSugar": [1, 1],
            "agentUniversalSpice": [0, 0],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 52,
            "environmentHeight": 52,
            "environmentMaxSugar": 5,
            "environmentSugarPeaks": [[26, 26, 5]],
            "environmentSugarRegrowRate": 2,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentUniversalSugarIncomeInterval": 1,
            "environmentUniversalSpiceIncomeInterval": 1,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["wealth.egalitarian"],
    },
    {
        "family": "wealth-egalitarian",
        "id": "wealth-egalitarian.scarce-income",
        "description": "Universal income cushions a compact cap-two replacement economy.",
        "config_overrides": {
            "startingAgents": 200,
            "agentMaxAge": [32, 48],
            "agentReplacements": 200,
            "agentStartingSugar": [16, 22],
            "agentSugarMetabolism": [2, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [1, 3],
            "agentVision": [1, 4],
            "agentUniversalSugar": [1, 1],
            "agentUniversalSpice": [0, 0],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 42,
            "environmentHeight": 42,
            "environmentMaxSugar": 2,
            "environmentSugarPeaks": [[9, 32, 2], [32, 9, 2]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentUniversalSugarIncomeInterval": 1,
            "environmentUniversalSpiceIncomeInterval": 1,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["wealth.egalitarian"],
    },
    {
        "family": "capacity",
        "id": "capacity.compact-regrow-1",
        "description": "Immortal population on a compact twin-peak world with unit growback.",
        "config_overrides": {
            "startingAgents": 200,
            "agentMaxAge": [-1, -1],
            "agentReplacements": 0,
            "agentStartingSugar": [3, 10],
            "agentSugarMetabolism": [1, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [1, 6],
            "agentVision": [1, 6],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 40,
            "environmentHeight": 40,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[10, 30, 4], [30, 10, 4]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["population.carrying-capacity"],
    },
    {
        "family": "capacity",
        "id": "capacity.sparse-regrow-2",
        "description": "Immortal population between two meridian peaks with rapid growback.",
        "config_overrides": {
            "startingAgents": 320,
            "agentMaxAge": [-1, -1],
            "agentReplacements": 0,
            "agentStartingSugar": [3, 10],
            "agentSugarMetabolism": [1, 5],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [1, 5],
            "agentVision": [2, 6],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 56,
            "environmentHeight": 56,
            "environmentMaxSugar": 3,
            "environmentSugarPeaks": [[28, 12, 3], [28, 44, 3]],
            "environmentSugarRegrowRate": 2,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["population.carrying-capacity"],
    },
    {
        "family": "survivorship",
        "id": "survivorship.young-frontier",
        "description": "Younger replacement cohort crossing a medium frontier world.",
        "config_overrides": {
            "startingAgents": 240,
            "agentMaxAge": [55, 85],
            "agentReplacements": 240,
            "agentStartingSugar": [8, 30],
            "agentSugarMetabolism": [1, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [1, 7],
            "agentVision": [1, 5],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 46,
            "environmentHeight": 46,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[11, 34, 4], [34, 11, 4]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["age-at-death.survivorship"],
    },
    {
        "family": "survivorship",
        "id": "survivorship.long-lived",
        "description": "Long-lived replacement cohort on a broad three-peak landscape.",
        "config_overrides": {
            "startingAgents": 300,
            "agentMaxAge": [70, 110],
            "agentReplacements": 300,
            "agentStartingSugar": [10, 35],
            "agentSugarMetabolism": [1, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [2, 6],
            "agentVision": [2, 8],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 54,
            "environmentHeight": 54,
            "environmentMaxSugar": 5,
            "environmentSugarPeaks": [[10, 40, 4], [27, 27, 5], [40, 10, 4]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["age-at-death.survivorship"],
    },
    {
        "family": "price",
        "id": "price.overlapping-peaks",
        "description": "Immortal traders share overlapping sugar and spice markets.",
        "config_overrides": {
            "startingAgents": 200,
            "agentMaxAge": [-1, -1],
            "agentReplacements": 0,
            "agentStartingSugar": [25, 50],
            "agentStartingSpice": [25, 50],
            "agentSugarMetabolism": [1, 5],
            "agentSpiceMetabolism": [1, 5],
            "agentMovement": [1, 6],
            "agentVision": [1, 5],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [1, 1],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 1], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 50,
            "environmentHeight": 50,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[14, 14, 4], [36, 36, 4]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 4,
            "environmentSpicePeaks": [[14, 14, 4], [36, 36, 4]],
            "environmentSpiceRegrowRate": 1,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
            "environmentSpiceConsumptionPollutionFactor": 0,
            "environmentSpiceProductionPollutionFactor": 0,
        },
        "targets": ["price.equilibrium"],
    },
    {
        "family": "price",
        "id": "price.four-markets",
        "description": "Large immortal market with alternating sugar and spice centers.",
        "config_overrides": {
            "startingAgents": 320,
            "agentMaxAge": [-1, -1],
            "agentReplacements": 0,
            "agentStartingSugar": [25, 50],
            "agentStartingSpice": [25, 50],
            "agentSugarMetabolism": [2, 6],
            "agentSpiceMetabolism": [1, 4],
            "agentMovement": [1, 8],
            "agentVision": [2, 7],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [1, 1],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 1], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 60,
            "environmentHeight": 60,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[12, 12, 4], [48, 48, 4]],
            "environmentSugarRegrowRate": 2,
            "environmentMaxSpice": 4,
            "environmentSpicePeaks": [[12, 48, 4], [48, 12, 4]],
            "environmentSpiceRegrowRate": 2,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
            "environmentSpiceConsumptionPollutionFactor": 0,
            "environmentSpiceProductionPollutionFactor": 0,
        },
        "targets": ["price.equilibrium"],
    },
    {
        "family": "tribe",
        "id": "tribe-convergence.three-way-mixed",
        "description": "Three initially mixed tribes exchange cultural tags on twin peaks.",
        "config_overrides": {
            "startingAgents": 300,
            "agentMaxAge": [60, 100],
            "agentReplacements": 0,
            "agentStartingSugar": [50, 100],
            "agentSugarMetabolism": [1, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [1, 7],
            "agentVision": [1, 6],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [1, 1],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": True,
            "agentTagStringLength": 11,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 1]},
            "environmentWidth": 50,
            "environmentHeight": 50,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[15, 35, 4], [35, 15, 4]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentMaxTribes": 3,
            "environmentTribePerQuadrant": False,
            "environmentStartingQuadrants": [1, 2, 3, 4],
            "environmentQuadrantSizeFactor": 1,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["tribe.convergence"],
    },
    {
        "family": "tribe",
        "id": "tribe-diversity.opposite-quadrants",
        "description": "Two tribes begin in opposite, separated quadrants on a large world.",
        "config_overrides": {
            "startingAgents": 400,
            "agentMaxAge": [60, 100],
            "agentReplacements": 0,
            "agentStartingSugar": [50, 100],
            "agentSugarMetabolism": [1, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [1, 5],
            "agentVision": [1, 5],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [1, 1],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": True,
            "agentTagStringLength": 11,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 1]},
            "environmentWidth": 60,
            "environmentHeight": 60,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[12, 48, 4], [48, 12, 4]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentMaxTribes": 2,
            "environmentTribePerQuadrant": True,
            "environmentStartingQuadrants": [1, 3],
            "environmentQuadrantSizeFactor": 0.8,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["tribe.diversity"],
    }
]


SITUATIONAL_PACKS: dict[str, list[str]] = {
    "wealth-skewed": ["reproduction", "pollution"],
    "wealth-egalitarian": ["disease", "seasons"],
    "capacity": ["pollution", "seasons"],
    "survivorship": ["disease", "seasons"],
    "price": ["seasons", "disease"],
    "tribe": ["disease", "seasons"],
}

PACK_DESCRIPTIONS = {
    "spice": "Adds a spice resource and spice metabolism.",
    "market": "Adds spice and bilateral sugar-spice trade.",
    "combat": "Adds cultural tags and inter-tribe combat.",
    "disease": "Adds transmissible diseases.",
    "pollution": "Adds production and consumption pollution with diffusion.",
    "seasons": "Adds alternating seasons with delayed growback.",
    "reproduction": "Replaces automatic replacement with agent reproduction.",
    "everything": "Adds spice, trade, tags, combat, disease, pollution, and seasons.",
}


def _spice_delta(base: dict[str, object]) -> dict[str, object]:
    sugar_peaks = base["environmentSugarPeaks"]
    return {
        "agentSpiceMetabolism": [1, 4],
        "agentStartingSpice": [10, 30],
        "environmentMaxSpice": base["environmentMaxSugar"],
        # sorted(): DTL's verifyConfiguration sorts lists in place, and the
        # preservation test requires the manifest to hold canonical values.
        "environmentSpicePeaks": sorted([y, x, height] for x, y, height in sugar_peaks),
        "environmentSpiceRegrowRate": 1,
    }


def _market_delta(base: dict[str, object]) -> dict[str, object]:
    delta = _spice_delta(base)
    delta["agentTradeFactor"] = [1, 1]
    delta["trait_ranges"] = {"trade": [0, 1]}
    return delta


def _combat_delta(base: dict[str, object]) -> dict[str, object]:
    delta: dict[str, object] = {
        "agentAggressionFactor": [0, 2],
        "environmentMaxCombatLoot": 2,
        "trait_ranges": {"aggression": [0, 2]},
    }
    if not base.get("agentTagging"):
        # DTL combat needs tribes: prey must belong to a different tribe.
        delta["agentTagging"] = True
        delta["agentTagStringLength"] = 11
        delta["environmentMaxTribes"] = 2
    return delta


def _disease_delta(has_spice: bool) -> dict[str, object]:
    return {
        "startingDiseases": 40,
        "startingDiseasesPerAgent": [0, 3],
        "agentImmuneSystemLength": 35,
        "diseaseSugarMetabolismPenalty": [1, 3],
        # A spice-metabolism penalty in a spiceless world is a death
        # sentence, not a hazard: it creates metabolism with no supply.
        "diseaseSpiceMetabolismPenalty": [1, 3] if has_spice else [0, 0],
        "diseaseTransmissionChance": [1.0, 1.0],
        # Pin the DTL default side effects off: metabolism is the intended
        # disease pressure. The defaults' positive fertility modifier would
        # otherwise switch reproduction ON in fertility-zero worlds.
        "diseaseAggressionPenalty": [0, 0],
        "diseaseFertilityPenalty": [0, 0],
        "diseaseMovementPenalty": [0, 0],
        "diseaseVisionPenalty": [0, 0],
    }


def _pollution_delta(has_spice: bool) -> dict[str, object]:
    # Ranked episodes run 1000 timesteps; keep bounds explicit and
    # non-negative so verifyConfiguration preserves them byte-for-byte
    # (negative "whole episode" shorthand gets normalized and would fail
    # the preservation test). Diffusion needs a positive delay to run.
    delta: dict[str, object] = {
        "environmentSugarProductionPollutionFactor": 1,
        "environmentSugarConsumptionPollutionFactor": 1,
        "environmentPollutionTimeframe": [0, 1000],
        "environmentPollutionDiffusionTimeframe": [50, 1000],
        "environmentPollutionDiffusionDelay": 10,
    }
    if has_spice:
        delta["environmentSpiceProductionPollutionFactor"] = 1
        delta["environmentSpiceConsumptionPollutionFactor"] = 1
    return delta


def _seasons_delta() -> dict[str, object]:
    return {
        "environmentSeasonInterval": 50,
        "environmentSeasonalGrowbackDelay": 8,
    }


def _reproduction_delta() -> dict[str, object]:
    return {
        "agentFertilityFactor": [1, 1],
        "agentReplacements": 0,
        "trait_ranges": {"fertility": [0, 1]},
    }


def _merge_delta(overrides: dict[str, object], delta: dict[str, object]) -> None:
    for key, value in delta.items():
        if key == "trait_ranges":
            merged = dict(overrides.get("trait_ranges", {}))
            merged.update(value)
            overrides["trait_ranges"] = merged
        else:
            overrides[key] = deepcopy(value)


def _pack_delta(pack: str, base: dict[str, object]) -> dict[str, object]:
    base_has_spice = base["environmentMaxSpice"] > 0
    if pack == "spice":
        return _spice_delta(base)
    if pack == "market":
        return _market_delta(base)
    if pack == "combat":
        return _combat_delta(base)
    if pack == "disease":
        return _disease_delta(base_has_spice)
    if pack == "pollution":
        return _pollution_delta(base_has_spice)
    if pack == "seasons":
        return _seasons_delta()
    if pack == "reproduction":
        return _reproduction_delta()
    if pack == "everything":
        delta: dict[str, object] = {}
        if not base_has_spice:
            # Bases that already run a market (price family) keep their own
            # tuned spice endowments and trade knobs untouched.
            _merge_delta(delta, _market_delta(base))
        _merge_delta(delta, _combat_delta(base))
        _merge_delta(delta, _disease_delta(True))
        _merge_delta(delta, _pollution_delta(True))
        _merge_delta(delta, _seasons_delta())
        return delta
    raise ValueError(f"unknown pack: {pack}")


def _family_packs(family: str, base_overrides: dict[str, object]) -> list[str]:
    packs = ["baseline", "spice", "market", "combat"]
    if base_overrides["environmentMaxSpice"] > 0:
        packs = ["baseline", "combat"]  # spice and market are already on
    packs += SITUATIONAL_PACKS[family]
    packs.append("everything")
    return packs


def build_scenarios() -> list[dict[str, object]]:
    scenarios: list[dict[str, object]] = []
    for family in FAMILY_ORDER:
        for base in (world for world in BASE_WORLDS if world["family"] == family):
            base_overrides = base["config_overrides"]
            for pack in _family_packs(family, base_overrides):
                overrides = deepcopy(base_overrides)
                description = base["description"]
                scenario_id = base["id"]
                if pack != "baseline":
                    _merge_delta(overrides, _pack_delta(pack, base_overrides))
                    scenario_id = f"{base['id']}.{pack}"
                    description = f"{description} {PACK_DESCRIPTIONS[pack]}"
                scenarios.append(
                    {
                        "id": scenario_id,
                        "description": description,
                        "config_overrides": overrides,
                        "targets": deepcopy(base["targets"]),
                    }
                )
    return scenarios


SCENARIOS: list[dict[str, object]] = build_scenarios()


def duo_scenarios() -> list[dict[str, object]]:
    """Derive two-target worlds while alternating which target owns seat zero."""

    scenarios = deepcopy(SCENARIOS)
    for index, scenario in enumerate(scenarios):
        solo_target = scenario["targets"][0]
        targets = [solo_target, DUO_COMPANION_TARGETS[solo_target]]
        if index % 2:
            targets.reverse()
        scenario["targets"] = targets

        overrides = scenario["config_overrides"]
        if overrides["startingAgents"] % 2:
            overrides["startingAgents"] += 1
    return scenarios


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Load the manifest and require exactly one generated ladder variant of each size."""

    manifest = json.loads(path.read_text(encoding="utf-8"))
    for variant_id in (VARIANT_ID, DUO_VARIANT_ID):
        variants = [variant for variant in manifest["variants"] if variant.get("id") == variant_id]
        if len(variants) != 1:
            raise ValueError(f"expected exactly one {variant_id!r} variant, found {len(variants)}")
        game_config = variants[0].get("game_config")
        if not isinstance(game_config, dict) or "scenario_pool" not in game_config:
            raise ValueError(f"variant {variant_id!r} has no game_config.scenario_pool")
    return manifest


def solo_ladder_config(manifest: dict[str, Any]) -> dict[str, Any]:
    return next(variant["game_config"] for variant in manifest["variants"] if variant.get("id") == VARIANT_ID)


def duo_ladder_config(manifest: dict[str, Any]) -> dict[str, Any]:
    return next(variant["game_config"] for variant in manifest["variants"] if variant.get("id") == DUO_VARIANT_ID)


def _skip_whitespace(source: str, offset: int) -> int:
    while offset < len(source) and source[offset].isspace():
        offset += 1
    return offset


def _object_member_span(source: str, object_start: int, key: str) -> tuple[int, int]:
    """Return the exact value span for one unique member of a JSON object."""

    decoder = json.JSONDecoder()
    offset = _skip_whitespace(source, object_start)
    if offset >= len(source) or source[offset] != "{":
        raise ValueError(f"expected JSON object while locating {key!r}")
    offset += 1
    matches: list[tuple[int, int]] = []
    while True:
        offset = _skip_whitespace(source, offset)
        if source[offset] == "}":
            break
        member, key_end = decoder.raw_decode(source, offset)
        if not isinstance(member, str):
            raise ValueError("JSON object member name is not a string")
        offset = _skip_whitespace(source, key_end)
        if source[offset] != ":":
            raise ValueError(f"missing colon after JSON member {member!r}")
        value_start = _skip_whitespace(source, offset + 1)
        _value, value_end = decoder.raw_decode(source, value_start)
        if member == key:
            matches.append((value_start, value_end))
        offset = _skip_whitespace(source, value_end)
        if source[offset] == ",":
            offset += 1
            continue
        if source[offset] == "}":
            break
        raise ValueError(f"malformed JSON object after member {member!r}")
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {key!r} member, found {len(matches)}")
    return matches[0]


def _array_element_spans(source: str, array_start: int) -> list[tuple[int, int]]:
    decoder = json.JSONDecoder()
    offset = _skip_whitespace(source, array_start)
    if offset >= len(source) or source[offset] != "[":
        raise ValueError("expected JSON array")
    offset += 1
    spans: list[tuple[int, int]] = []
    while True:
        offset = _skip_whitespace(source, offset)
        if source[offset] == "]":
            return spans
        _value, value_end = decoder.raw_decode(source, offset)
        spans.append((offset, value_end))
        offset = _skip_whitespace(source, value_end)
        if source[offset] == ",":
            offset += 1
            continue
        if source[offset] == "]":
            return spans
        raise ValueError("malformed JSON array")


def scenario_pool_span(source: str, variant_id: str = VARIANT_ID) -> tuple[int, int]:
    """Locate one ladder variant's pool through parsed object and array boundaries."""

    manifest = json.loads(source)
    matching_indexes = [
        index for index, variant in enumerate(manifest.get("variants", []))
        if isinstance(variant, dict) and variant.get("id") == variant_id
    ]
    if len(matching_indexes) != 1:
        raise ValueError(f"expected exactly one {variant_id!r} variant, found {len(matching_indexes)}")

    variants_start, _ = _object_member_span(source, 0, "variants")
    variant_spans = _array_element_spans(source, variants_start)
    if len(variant_spans) != len(manifest["variants"]):
        raise ValueError("parsed variant count does not match manifest data")
    variant_start, _ = variant_spans[matching_indexes[0]]
    game_config_start, _ = _object_member_span(source, variant_start, "game_config")
    pool_start, pool_end = _object_member_span(source, game_config_start, "scenario_pool")
    pool, decoded_end = json.JSONDecoder().raw_decode(source, pool_start)
    if decoded_end != pool_end or not isinstance(pool, list):
        raise ValueError(f"variant {variant_id!r} scenario_pool is not an array")
    return pool_start, pool_end


def _contains_nested_object(value: object) -> bool:
    if isinstance(value, dict):
        return any(isinstance(item, dict) or _contains_nested_object(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_nested_object(item) for item in value)
    return False


def _render_json(value: object) -> str:
    inline = json.dumps(value, ensure_ascii=False)
    if not isinstance(value, (dict, list)) or not value or (
        len(inline) <= 140 and not _contains_nested_object(value)
    ):
        return inline
    opening, closing = ("{", "}") if isinstance(value, dict) else ("[", "]")
    entries = value.items() if isinstance(value, dict) else enumerate(value)
    lines = [opening]
    rendered_entries = []
    for key, item in entries:
        rendered = _render_json(item)
        prefix = f"{json.dumps(key)}: " if isinstance(value, dict) else ""
        item_lines = rendered.splitlines()
        rendered_entries.append(
            "  " + prefix + item_lines[0]
            + "".join("\n  " + line for line in item_lines[1:])
        )
    lines.append(",\n".join(rendered_entries))
    lines.append(closing)
    return "\n".join(lines)


def rendered_pool(scenarios: object = SCENARIOS, indent: int = 8) -> str:
    rendered = _render_json(scenarios)
    lines = rendered.splitlines()
    return lines[0] + "\n" + "\n".join(" " * indent + line for line in lines[1:])


def write_manifest(path: Path = MANIFEST_PATH) -> bool:
    source = path.read_text(encoding="utf-8")
    replacements = [
        (*scenario_pool_span(source, VARIANT_ID), rendered_pool(SCENARIOS)),
        (*scenario_pool_span(source, DUO_VARIANT_ID), rendered_pool(duo_scenarios())),
    ]
    updated = source
    for start, end, replacement in sorted(replacements, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    if updated == source:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def check_manifest(path: Path = MANIFEST_PATH) -> list[str]:
    manifest = load_manifest(path)
    expected_pools = {
        VARIANT_ID: SCENARIOS,
        DUO_VARIANT_ID: duo_scenarios(),
    }
    actual_pools = {
        VARIANT_ID: solo_ladder_config(manifest)["scenario_pool"],
        DUO_VARIANT_ID: duo_ladder_config(manifest)["scenario_pool"],
    }
    if actual_pools == expected_pools:
        return []
    summary = []
    for variant_id, expected in expected_pools.items():
        actual = actual_pools[variant_id]
        if actual == expected:
            continue
        summary.extend(f"{variant_id}: {item}" for item in _pool_diff(actual, expected))
    return summary


def _pool_diff(actual: list[object], expected: list[dict[str, object]]) -> list[str]:
    actual_by_id = {
        entry.get("id"): entry for entry in actual if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    expected_by_id = {entry["id"]: entry for entry in expected}
    actual_ids = list(actual_by_id)
    expected_ids = list(expected_by_id)
    summary = []
    missing = [scenario_id for scenario_id in expected_ids if scenario_id not in actual_by_id]
    extra = [scenario_id for scenario_id in actual_ids if scenario_id not in expected_by_id]
    changed = [
        scenario_id for scenario_id in expected_ids
        if scenario_id in actual_by_id and actual_by_id[scenario_id] != expected_by_id[scenario_id]
    ]
    if missing:
        summary.append(f"missing: {', '.join(missing)}")
    if extra:
        summary.append(f"extra: {', '.join(extra)}")
    if changed:
        summary.append(f"changed: {', '.join(changed)}")
    if not missing and not extra and actual_ids != expected_ids:
        summary.append("scenario order differs")
    if not summary:
        summary.append("pool structure differs")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update the manifest pools")
    parser.add_argument("--check", action="store_true", help="verify the manifest pools")
    args = parser.parse_args()
    if not args.write and not args.check:
        parser.error("choose --write or --check")

    try:
        if args.write:
            changed = write_manifest()
            print(f"{'updated' if changed else 'unchanged'}: {MANIFEST_PATH}")
        if args.check:
            differences = check_manifest()
            if differences:
                print("scenario pool differs from generator:", file=sys.stderr)
                for difference in differences:
                    print(f"  {difference}", file=sys.stderr)
                raise SystemExit(1)
            print("scenario pool matches generator")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"error: {error}") from error


if __name__ == "__main__":
    main()
