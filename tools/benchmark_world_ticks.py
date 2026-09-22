#!/usr/bin/env python3
"""Measure CPU simulation ticks or complete episodes across isolated processes."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
from time import perf_counter, sleep
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / 'src'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from coworld.config import build_dtl_config, resolve_episode_config, ruleset_limits
from coworld.episode import canonical_results_payload, run_episode
from coworld.ruleset import compile_ruleset
from coworld.seats import parse_trait_ranges
from coworld.simulation import CoworldSugarscape
from coworld.targets import load_target_catalog, resolve_seat_targets
from players.baseline.player import choose_ruleset


def prepare_config(config: dict[str, object]) -> tuple[dict[str, object], list[dict[str, object]]]:
    resolved = resolve_episode_config(config)
    targets = resolve_seat_targets(
        resolved.get('targets'), seats=int(resolved['seats']),
        measurement_window=int(resolved['measurement_window']), catalog=load_target_catalog(),
    )
    rulesets = [choose_ruleset(target.as_dict()) for target in targets]
    return resolved, rulesets


def run_world(config: dict[str, object]) -> dict[str, object]:
    resolved, rulesets = prepare_config(config)
    results, replay, timings = run_episode(config, rulesets, emit_timing_logs=False)
    return {
        'seed': resolved['seed'], 'config': resolved, 'rulesets': rulesets,
        'timesteps_completed': results['timesteps_completed'],
        'population_final': results['result.population_final'],
        'world_width': resolved['environmentWidth'], 'world_height': resolved['environmentHeight'],
        'results_sha256': hashlib.sha256(canonical_results_payload(results)).hexdigest(),
        'replay_sha256': hashlib.sha256(replay).hexdigest(),
        'replay_bytes': len(replay),
        'timings': {'phases_ns': timings['phases_ns'], 'subphases_ns': timings['simulation']['subphases_ns']},
    }



def prepare_simulation(config: dict[str, object]):
    resolved, rulesets = prepare_config(config)
    compiled = [compile_ruleset(rule, limits=ruleset_limits(resolved)) for rule in rulesets]
    world = CoworldSugarscape(build_dtl_config(resolved), compiled, parse_trait_ranges(resolved.get('trait_ranges')))
    world.updateRuntimeStats()
    return world, resolved, rulesets


def state_hash(world: CoworldSugarscape) -> str:
    """Hash observable state, agent order and RNG; this is not a complete checkpoint."""
    state = {
        'timestep': world.timestep, 'runtime_stats': world.runtimeStats,
        'agents': [(a.ID, a.seat, a.cell.x, a.cell.y, a.sugar, a.spice, a.age, a.alive, a.timeToLive) for a in world.agents],
        'cells': [(c.x, c.y, c.sugar, c.spice, c.pollution, c.agent.ID if c.agent else None) for column in world.environment.grid for c in column],
        'rng': random.getstate(),
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True, allow_nan=False).encode()).hexdigest()


def run_simulation(config, ready, start, done, collect, output, timeout):
    try:
        world, resolved, rulesets = prepare_simulation(config)
        ready.set()
        if not start.wait(timeout):
            raise TimeoutError('simulation start was not released')
        for _ in range(int(resolved['timesteps'])):
            if not world.agents and not world.keepAlive:
                break
            world.doTimestep()
        finished = perf_counter()
        done.set()
        if not collect.wait(timeout):
            raise TimeoutError('simulation results were not released')
        output.send({
            'seed': resolved['seed'], 'config': resolved, 'rulesets': rulesets,
            'timesteps_completed': world.timestep, 'population_final': len(world.agents),
            'world_width': resolved['environmentWidth'], 'world_height': resolved['environmentHeight'],
            'finished_at': finished, 'state_sha256': state_hash(world),
        })
    finally:
        output.close()


def simulate_worlds(configs, *, timeout):
    context = multiprocessing.get_context('spawn')
    start = context.Event()
    collect = context.Event()
    children = []
    try:
        for config in configs:
            reader, writer = context.Pipe(duplex=False)
            ready = context.Event()
            done = context.Event()
            process = context.Process(target=run_simulation, args=(config, ready, start, done, collect, writer, timeout))
            process.start()
            writer.close()
            children.append((process, ready, done, reader))
        deadline = perf_counter() + timeout
        while not all(ready.is_set() for _, ready, _, _ in children):
            for process, _, _, _ in children:
                if process.exitcode is not None:
                    raise RuntimeError(f'simulation worker {process.pid} exited during preparation: {process.exitcode}')
            if perf_counter() >= deadline:
                raise TimeoutError('simulation workers did not become ready')
            sleep(0.01)
        started = perf_counter()
        start.set()
        while not all(done.is_set() for _, _, done, _ in children):
            for process, _, _, _ in children:
                if process.exitcode is not None:
                    raise RuntimeError(f'simulation worker {process.pid} exited during ticks: {process.exitcode}')
            if perf_counter() - started >= timeout:
                raise TimeoutError('simulation workers did not finish ticks')
            sleep(0.01)
        collect.set()
        completed = []
        pending = list(children)
        while pending:
            for child in pending[:]:
                process, _, _, reader = child
                if reader.poll():
                    completed.append(reader.recv())
                    pending.remove(child)
                elif process.exitcode is not None:
                    raise RuntimeError(f'simulation worker {process.pid} exited without results: {process.exitcode}')
            if perf_counter() - started >= timeout:
                raise TimeoutError('simulation workers did not finish')
            if pending:
                sleep(0.01)
        elapsed = max(world['finished_at'] for world in completed) - started
        return sorted(completed, key=lambda world: world['seed']), elapsed
    finally:
        for process, _, _, reader in children:
            process.join(timeout=0.1)
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
            reader.close()

def benchmark(config: dict[str, object], *, workers: int, worlds: int, seed: int, mode: str = 'episodes', timeout: float = 600) -> dict[str, object]:
    if workers < 1 or worlds < 1 or seed < 0:
        raise ValueError('workers/worlds must be positive and seed nonnegative')
    if mode not in {'episodes', 'simulation'} or timeout <= 0:
        raise ValueError('mode must be episodes/simulation and timeout positive')
    if mode == 'simulation' and worlds != workers:
        raise ValueError('simulation requires worlds == workers')
    # Spawned interpreters must agree on hashes used by DTL inheritance.
    os.environ['PYTHONHASHSEED'] = '0'
    configs = [{**config, 'seed': seed + index} for index in range(worlds)]
    if mode == 'simulation':
        completed, elapsed = simulate_worlds(configs, timeout=timeout)
    else:
        started = perf_counter()
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn')) as pool:
            completed = list(pool.map(run_world, configs))
        elapsed = perf_counter() - started
    if mode == 'episodes':
        worker_timings = [{'seed': world['seed'], **world.pop('timings')} for world in completed]
    else:
        worker_timings = [{'seed': world['seed'], 'finished_at': world.pop('finished_at')} for world in completed]
    ticks = sum(world['timesteps_completed'] for world in completed)
    rate = ticks / elapsed
    return {
        'backend': 'cpu', 'metric': 'completed_whole_world_ticks_per_wall_second',
        'mode': mode, 'replay_enabled': mode == 'episodes', 'inference_enabled': False,
        'measurement_enabled': mode == 'episodes', 'instrumentation_enabled': mode == 'episodes',
        'timing_scope': ('synchronized simulation: release through last completed tick; includes scheduling and intrinsic DTL runtime statistics; excludes setup, measurements, scoring, replay, hashing and result transfer' if mode == 'simulation' else 'end-to-end: process startup/shutdown, episode setup, simulation, statistics, scoring, replay and result transfer'),
        'workers': workers, 'world_count': worlds, 'elapsed_seconds': elapsed,
        'completed_world_ticks': ticks, 'world_ticks_per_second': rate,
        'target_world_ticks_per_second': 30000, 'target_met': rate >= 30000,
        'worker_timings': worker_timings,
        'worker_timings_note': 'Per-worker elapsed phase/subphase durations overlap and cannot be summed as benchmark walltime.',
        'worlds': completed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['episodes', 'simulation'], default='episodes')
    parser.add_argument('--timeout-seconds', type=float, default=600)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--worlds', type=int, default=1)
    parser.add_argument('--timesteps', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=1729)
    parser.add_argument('--variant', default='commonwealth')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--source-revision', help='Source revision when running a snapshot without Git')
    parser.add_argument('--upstream-revision', help='Pinned DTL revision for a snapshot without Git')
    args = parser.parse_args()
    if not (ROOT / '.git').exists() and not (args.source_revision and args.upstream_revision):
        parser.error('snapshots require --source-revision and --upstream-revision')
    if args.workers < 1 or args.worlds < 1 or args.seed < 0:
        parser.error('workers/worlds must be positive and seed nonnegative')
    if args.mode == 'simulation' and args.worlds != args.workers:
        parser.error('simulation requires --worlds == --workers')
    if args.timeout_seconds <= 0:
        parser.error('--timeout-seconds must be positive')
    if args.timesteps < 1:
        parser.error('--timesteps must be positive')
    manifest = json.loads((ROOT / 'coworld_manifest.json').read_text())
    variant = next(item for item in manifest['variants'] if item['id'] == args.variant)
    config = {**variant['game_config'], 'timesteps': args.timesteps}
    digest = hashlib.sha256()
    paths = [ROOT / 'coworld_manifest.json', ROOT / 'tools/benchmark_world_ticks.py']
    for directory in ('src', 'players', 'targets'):
        paths.extend(path for path in (ROOT / directory).rglob('*') if path.is_file() and path.suffix in {'.py', '.json'})
    for path in sorted(paths):
        relative = str(path.relative_to(ROOT)).encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, 'big') + relative)
        digest.update(len(content).to_bytes(8, 'big') + content)
    metadata = {
        'variant': args.variant, 'python': sys.version, 'platform': platform.platform(),
        'processor': platform.processor(), 'logical_cpu_count': os.cpu_count(),
        'commit': args.source_revision or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_tree_sha256': digest.hexdigest(),
        'source_tree_scope': 'src, players, targets Python/JSON files; manifest; benchmark harness',
        'dirty_status': 'snapshot; see source_tree_sha256' if args.source_revision else subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True),
        'upstream_commit': args.upstream_revision or subprocess.check_output(['git', '-C', 'src/sugarscape', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'pythonhashseed': '0', 'created_at': datetime.now(timezone.utc).isoformat(),
    }
    output = args.output or ROOT / 'build' / 'benchmarks' / f'world-ticks-{uuid4().hex}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as file:
        report = benchmark(config, workers=args.workers, worlds=args.worlds, seed=args.seed, mode=args.mode, timeout=args.timeout_seconds)
        report['metadata'] = metadata
        json.dump(report, file, indent=2, allow_nan=False)
    print(json.dumps({'report': str(output), 'world_ticks_per_second': report['world_ticks_per_second'], 'target_met': report['target_met']}))


if __name__ == '__main__':
    main()
