#!/usr/bin/env python3
"""Generate the curated solo-ladder scenario pool and probe configs.

Run from the repository root. The scenario definitions in this file are the
source of truth; ``--write`` updates only the pool array in the manifest.
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
DEFAULT_CONFIG_DIR = REPO_ROOT / "build" / "scenario-pool"
VARIANT_ID = "solo-ladder"


SCENARIOS: list[dict[str, object]] = [
    {
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
        "id": "wealth-skewed.mega-peak",
        "description": "Replacement economy concentrated around one high central sugar peak.",
        "config_overrides": {
            "startingAgents": 220,
            "agentMaxAge": [60, 100],
            "agentReplacements": 220,
            "agentStartingSugar": [5, 25],
            "agentSugarMetabolism": [1, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [2, 7],
            "agentVision": [1, 5],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 44,
            "environmentHeight": 44,
            "environmentMaxSugar": 6,
            "environmentSugarPeaks": [[22, 22, 6]],
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
        "id": "wealth-skewed.four-corners",
        "description": "Large replacement economy spread across four corner sugar peaks.",
        "config_overrides": {
            "startingAgents": 360,
            "agentMaxAge": [60, 100],
            "agentReplacements": 360,
            "agentStartingSugar": [6, 28],
            "agentSugarMetabolism": [1, 5],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [1, 8],
            "agentVision": [2, 7],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 60,
            "environmentHeight": 60,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[10, 10, 4], [10, 50, 4], [50, 10, 4], [50, 50, 4]],
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
        "targets": ["wealth.skewed-gini-0.5"],
    },
    {
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
        "id": "wealth-egalitarian.offset-twins",
        "description": "Short-lived replacement economy with income on offset twin peaks.",
        "config_overrides": {
            "startingAgents": 240,
            "agentMaxAge": [30, 45],
            "agentReplacements": 240,
            "agentStartingSugar": [20, 25],
            "agentSugarMetabolism": [3, 3],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [2, 2],
            "agentVision": [3, 3],
            "agentUniversalSugar": [1, 1],
            "agentUniversalSpice": [0, 0],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 48,
            "environmentHeight": 48,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[12, 34, 4], [34, 12, 4]],
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
        "id": "wealth-egalitarian.four-basins",
        "description": "Large income-supported economy distributed across four unequal basins.",
        "config_overrides": {
            "startingAgents": 400,
            "agentMaxAge": [28, 42],
            "agentReplacements": 400,
            "agentStartingSugar": [20, 28],
            "agentSugarMetabolism": [2, 3],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [1, 5],
            "agentVision": [2, 6],
            "agentUniversalSugar": [1, 1],
            "agentUniversalSpice": [0, 0],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 60,
            "environmentHeight": 60,
            "environmentMaxSugar": 5,
            "environmentSugarPeaks": [[12, 12, 3], [12, 48, 4], [48, 12, 5], [48, 48, 3]],
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
        "id": "capacity.wide-regrow-1",
        "description": "Immortal population on a wide separated-peak world with unit growback.",
        "config_overrides": {
            "startingAgents": 275,
            "agentMaxAge": [-1, -1],
            "agentReplacements": 0,
            "agentStartingSugar": [3, 10],
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
            "environmentWidth": 50,
            "environmentHeight": 50,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[8, 42, 4], [42, 8, 4]],
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
        "id": "capacity.dense-regrow-2",
        "description": "Four-peak immortal population on the largest world with rapid growback.",
        "config_overrides": {
            "startingAgents": 400,
            "agentMaxAge": [-1, -1],
            "agentReplacements": 0,
            "agentStartingSugar": [3, 10],
            "agentSugarMetabolism": [1, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [2, 8],
            "agentVision": [2, 7],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 60,
            "environmentHeight": 60,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[12, 12, 4], [12, 48, 4], [48, 12, 4], [48, 48, 4]],
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
        "id": "survivorship.scarce",
        "description": "Replacement cohort faces starvation pressure around one scarce peak.",
        "config_overrides": {
            "startingAgents": 200,
            "agentMaxAge": [60, 100],
            "agentReplacements": 200,
            "agentStartingSugar": [5, 20],
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
            "environmentMaxSugar": 3,
            "environmentSugarPeaks": [[20, 20, 3]],
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
        "id": "survivorship.seasonal-migration",
        "description": "Replacement cohort migrates through alternating wet and dry seasons.",
        "config_overrides": {
            "startingAgents": 360,
            "agentMaxAge": [65, 105],
            "agentReplacements": 360,
            "agentStartingSugar": [6, 24],
            "agentSugarMetabolism": [1, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [2, 8],
            "agentVision": [2, 7],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 60,
            "environmentHeight": 60,
            "environmentMaxSugar": 4,
            "environmentSugarPeaks": [[12, 45, 4], [45, 12, 4]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentSeasonInterval": 50,
            "environmentSeasonalGrowbackDelay": 8,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["age-at-death.survivorship"],
    },
    {
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
        "id": "price.opposite-corners",
        "description": "Immortal traders bridge sugar and spice in opposite corners.",
        "config_overrides": {
            "startingAgents": 240,
            "agentMaxAge": [-1, -1],
            "agentReplacements": 0,
            "agentStartingSugar": [25, 50],
            "agentStartingSpice": [25, 50],
            "agentSugarMetabolism": [1, 4],
            "agentSpiceMetabolism": [2, 5],
            "agentMovement": [2, 7],
            "agentVision": [2, 6],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [1, 1],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 1], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 56,
            "environmentHeight": 56,
            "environmentMaxSugar": 5,
            "environmentSugarPeaks": [[10, 10, 5]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 5,
            "environmentSpicePeaks": [[46, 46, 5]],
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
        "id": "price.split-centers",
        "description": "Compact immortal market split between two high resource centers.",
        "config_overrides": {
            "startingAgents": 220,
            "agentMaxAge": [-1, -1],
            "agentReplacements": 0,
            "agentStartingSugar": [25, 50],
            "agentStartingSpice": [25, 50],
            "agentSugarMetabolism": [1, 6],
            "agentSpiceMetabolism": [1, 6],
            "agentMovement": [1, 5],
            "agentVision": [1, 4],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [0, 0],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [1, 1],
            "agentTagging": False,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 1], "lending": [0, 0], "fertility": [0, 0]},
            "environmentWidth": 44,
            "environmentHeight": 44,
            "environmentMaxSugar": 5,
            "environmentSugarPeaks": [[12, 32, 5]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 5,
            "environmentSpicePeaks": [[32, 12, 5]],
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
        "id": "tribe-convergence.two-way-mixed",
        "description": "Two initially mixed tribes exchange cultural tags on a compact world.",
        "config_overrides": {
            "startingAgents": 240,
            "agentMaxAge": [55, 90],
            "agentReplacements": 0,
            "agentStartingSugar": [45, 90],
            "agentSugarMetabolism": [1, 5],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [2, 6],
            "agentVision": [2, 5],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [1, 1],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": True,
            "agentTagStringLength": 11,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 1]},
            "environmentWidth": 44,
            "environmentHeight": 44,
            "environmentMaxSugar": 5,
            "environmentSugarPeaks": [[10, 34, 4], [22, 22, 5], [34, 10, 4]],
            "environmentSugarRegrowRate": 2,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentMaxTribes": 2,
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
    },
    {
        "id": "tribe-diversity.three-quadrants",
        "description": "Three tribes begin in separated quadrants around asymmetric peaks.",
        "config_overrides": {
            "startingAgents": 360,
            "agentMaxAge": [65, 105],
            "agentReplacements": 0,
            "agentStartingSugar": [45, 95],
            "agentSugarMetabolism": [1, 4],
            "agentSpiceMetabolism": [0, 0],
            "agentStartingSpice": [0, 0],
            "agentMovement": [1, 4],
            "agentVision": [2, 6],
            "agentAggressionFactor": [0, 0],
            "agentFertilityFactor": [1, 1],
            "agentLendingFactor": [0, 0],
            "agentTradeFactor": [0, 0],
            "agentTagging": True,
            "agentTagStringLength": 11,
            "trait_ranges": {"aggression": [0, 0], "trade": [0, 0], "lending": [0, 0], "fertility": [0, 1]},
            "environmentWidth": 56,
            "environmentHeight": 56,
            "environmentMaxSugar": 5,
            "environmentSugarPeaks": [[10, 10, 4], [10, 46, 5], [46, 10, 3]],
            "environmentSugarRegrowRate": 1,
            "environmentMaxSpice": 0,
            "environmentSpicePeaks": [],
            "environmentSpiceRegrowRate": 0,
            "environmentMaxTribes": 3,
            "environmentTribePerQuadrant": True,
            "environmentStartingQuadrants": [1, 2, 4],
            "environmentQuadrantSizeFactor": 0.8,
            "environmentSeasonInterval": 0,
            "environmentSeasonalGrowbackDelay": 0,
            "environmentPollutionTimeframe": [0, 0],
            "environmentPollutionDiffusionTimeframe": [0, 0],
            "environmentSugarConsumptionPollutionFactor": 0,
            "environmentSugarProductionPollutionFactor": 0,
        },
        "targets": ["tribe.diversity"],
    },
]


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Load the manifest and require exactly one solo-ladder variant."""

    manifest = json.loads(path.read_text(encoding="utf-8"))
    variants = [variant for variant in manifest["variants"] if variant.get("id") == VARIANT_ID]
    if len(variants) != 1:
        raise ValueError(f"expected exactly one {VARIANT_ID!r} variant, found {len(variants)}")
    game_config = variants[0].get("game_config")
    if not isinstance(game_config, dict) or "scenario_pool" not in game_config:
        raise ValueError(f"variant {VARIANT_ID!r} has no game_config.scenario_pool")
    return manifest


def solo_ladder_config(manifest: dict[str, Any]) -> dict[str, Any]:
    return next(variant["game_config"] for variant in manifest["variants"] if variant.get("id") == VARIANT_ID)


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


def scenario_pool_span(source: str) -> tuple[int, int]:
    """Locate solo-ladder's pool through parsed object and array boundaries."""

    manifest = json.loads(source)
    matching_indexes = [
        index for index, variant in enumerate(manifest.get("variants", []))
        if isinstance(variant, dict) and variant.get("id") == VARIANT_ID
    ]
    if len(matching_indexes) != 1:
        raise ValueError(f"expected exactly one {VARIANT_ID!r} variant, found {len(matching_indexes)}")

    variants_start, _ = _object_member_span(source, 0, "variants")
    variant_spans = _array_element_spans(source, variants_start)
    if len(variant_spans) != len(manifest["variants"]):
        raise ValueError("parsed variant count does not match manifest data")
    variant_start, _ = variant_spans[matching_indexes[0]]
    game_config_start, _ = _object_member_span(source, variant_start, "game_config")
    pool_start, pool_end = _object_member_span(source, game_config_start, "scenario_pool")
    pool, decoded_end = json.JSONDecoder().raw_decode(source, pool_start)
    if decoded_end != pool_end or not isinstance(pool, list):
        raise ValueError(f"variant {VARIANT_ID!r} scenario_pool is not an array")
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


def rendered_pool(indent: int = 8) -> str:
    rendered = _render_json(SCENARIOS)
    lines = rendered.splitlines()
    return lines[0] + "\n" + "\n".join(" " * indent + line for line in lines[1:])


def write_manifest(path: Path = MANIFEST_PATH) -> bool:
    source = path.read_text(encoding="utf-8")
    start, end = scenario_pool_span(source)
    updated = source[:start] + rendered_pool() + source[end:]
    if updated == source:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def check_manifest(path: Path = MANIFEST_PATH) -> list[str]:
    manifest = load_manifest(path)
    actual = solo_ladder_config(manifest)["scenario_pool"]
    if actual == SCENARIOS:
        return []
    actual_by_id = {
        entry.get("id"): entry for entry in actual if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    expected_by_id = {entry["id"]: entry for entry in SCENARIOS}
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


def emit_configs(output_dir: Path, manifest_path: Path = MANIFEST_PATH) -> list[Path]:
    manifest = load_manifest(manifest_path)
    base_config = deepcopy(solo_ladder_config(manifest))
    base_config.pop("seed", None)
    base_config.pop("scenario_pool", None)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for scenario in SCENARIOS:
        config = deepcopy(base_config)
        config.update(deepcopy(scenario["config_overrides"]))
        config["targets"] = deepcopy(scenario["targets"])
        path = output_dir / f"{scenario['id']}.json"
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update the manifest pool")
    parser.add_argument("--check", action="store_true", help="verify the manifest pool")
    parser.add_argument(
        "--emit-configs",
        nargs="?",
        const=str(DEFAULT_CONFIG_DIR),
        metavar="DIR",
        help="write merged standalone configs (default: build/scenario-pool)",
    )
    args = parser.parse_args()
    if not args.write and not args.check and args.emit_configs is None:
        parser.error("choose --write, --check, or --emit-configs")

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
        if args.emit_configs is not None:
            paths = emit_configs(Path(args.emit_configs))
            print(f"wrote {len(paths)} configs to {Path(args.emit_configs)}")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"error: {error}") from error


if __name__ == "__main__":
    main()
