from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from benchmark_world_ticks import benchmark


def test_spawned_workers_preserve_world_results_and_replay(tiny_episode_config):
    one = benchmark(tiny_episode_config, workers=1, worlds=2, seed=1729)
    two = benchmark(tiny_episode_config, workers=2, worlds=2, seed=1729)
    assert one['worlds'] == two['worlds']
    assert [world['seed'] for world in one['worlds']] == [1729, 1730]
    for report in (one, two):
        ticks = sum(world['timesteps_completed'] for world in report['worlds'])
        assert ticks == 8
        assert report['completed_world_ticks'] == ticks
        assert report['world_ticks_per_second'] == ticks / report['elapsed_seconds']
        assert report['backend'] == 'cpu'


def test_extinct_world_counts_actual_ticks(tiny_episode_config):
    config = {**tiny_episode_config, 'startingAgents': 0, 'agentReplacements': 0, 'keepAlive': False}
    report = benchmark(config, workers=1, worlds=1, seed=17)
    assert report['completed_world_ticks'] == 0
    assert report['world_ticks_per_second'] == 0


@pytest.mark.parametrize('workers,worlds,seed', [(0, 1, 1), (1, 0, 1), (1, 1, -1)])
def test_invalid_benchmark_dimensions(workers, worlds, seed):
    with pytest.raises(ValueError):
        benchmark({}, workers=workers, worlds=worlds, seed=seed)
