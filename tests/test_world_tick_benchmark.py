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


@pytest.mark.parametrize('mode', ['episodes', 'simulation'])
def test_extinct_world_counts_actual_ticks(tiny_episode_config, mode):
    config = {**tiny_episode_config, 'startingAgents': 0, 'agentReplacements': 0, 'keepAlive': False}
    report = benchmark(config, workers=1, worlds=1, seed=17, mode=mode)
    assert report['completed_world_ticks'] == 0
    assert report['world_ticks_per_second'] == 0


@pytest.mark.parametrize('workers,worlds,seed', [(0, 1, 1), (1, 0, 1), (1, 1, -1)])
def test_invalid_benchmark_dimensions(workers, worlds, seed):
    with pytest.raises(ValueError):
        benchmark({}, workers=workers, worlds=worlds, seed=seed)


def test_simulation_matches_full_episode_each_tick(tiny_episode_config, monkeypatch):
    import coworld.episode as episode
    from benchmark_world_ticks import prepare_config, prepare_simulation, state_hash
    from coworld.simulation import CoworldSugarscape

    observed = []

    class CapturedWorld(CoworldSugarscape):
        def doTimestep(self):
            super().doTimestep()
            observed.append(state_hash(self))

    monkeypatch.setattr(episode, 'CoworldSugarscape', CapturedWorld)
    config = {**tiny_episode_config, 'timesteps': 20, 'agentReplacements': 8}
    _, rulesets = prepare_config(config)
    results, _, _ = episode.run_episode(config, rulesets, emit_timing_logs=False)
    world, resolved, _ = prepare_simulation(config)
    assert world.measurements is None
    assert world.replay_writer is None
    assert not world.instrumentation.enabled
    plain = []
    for _ in range(resolved['timesteps']):
        if not world.agents and not world.keepAlive:
            break
        world.doTimestep()
        plain.append(state_hash(world))
    assert plain == observed
    assert world.timestep == results['timesteps_completed']
    assert len(world.agents) == results['result.population_final']


def test_simulation_parallel_worlds_match_independent_runs(tiny_episode_config):
    two = benchmark(tiny_episode_config, workers=2, worlds=2, seed=17, mode='simulation')
    independent = [benchmark(tiny_episode_config, workers=1, worlds=1, seed=seed, mode='simulation')['worlds'][0] for seed in (17, 18)]
    assert two['worlds'] == independent
    assert two['completed_world_ticks'] == 8
    assert not two['replay_enabled']
    assert not two['measurement_enabled']
    assert not two['inference_enabled']


def test_simulation_requires_one_world_per_worker(tiny_episode_config):
    with pytest.raises(ValueError, match='worlds == workers'):
        benchmark(tiny_episode_config, workers=1, worlds=2, seed=17, mode='simulation')


def test_simulation_preparation_failure_does_not_hang(tiny_episode_config):
    import multiprocessing
    before = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises((RuntimeError, EOFError)):
        benchmark({**tiny_episode_config, 'targets': ['missing-target']}, workers=2, worlds=2, seed=17, mode='simulation', timeout=5)

    assert {child.pid for child in multiprocessing.active_children()} == before


def test_simulation_timeout_cleans_children(tiny_episode_config):
    import multiprocessing
    before = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises(TimeoutError):
        benchmark(tiny_episode_config, workers=2, worlds=2, seed=17, mode='simulation', timeout=0.000001)
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_simulation_cli_exits_without_cleanup_warnings(tmp_path):
    import os
    import subprocess

    completed = subprocess.run(
        [sys.executable, str(ROOT / 'tools/benchmark_world_ticks.py'), '--mode', 'simulation',
         '--workers', '2', '--worlds', '2', '--timesteps', '1', '--output', str(tmp_path / 'report.json')],
        cwd=ROOT, env={**os.environ, 'PYTHONHASHSEED': '0'},
        capture_output=True, text=True, timeout=30, check=True,
    )
    assert completed.stderr == ''
