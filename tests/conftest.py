from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def tiny_episode_config() -> dict[str, object]:
    """Small, valid world whose resource peaks fit inside its bounds."""

    return {
        "seed": 17,
        "seats": 2,
        "timesteps": 4,
        "startingAgents": 8,
        "startingDiseases": 0,
        "environmentWidth": 12,
        "environmentHeight": 12,
        "environmentSugarPeaks": [[3, 8, 4], [8, 3, 4]],
        "environmentSpicePeaks": [[3, 3, 4], [8, 8, 4]],
        "trait_ranges": {
            "aggression": [0, 1],
            "trade": [0, 1],
            "lending": [0, 1],
            "fertility": [0.5, 2],
        },
    }
