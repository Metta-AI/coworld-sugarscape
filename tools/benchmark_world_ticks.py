#!/usr/bin/env python3
"""Measure complete CPU episodes across isolated spawned worker processes."""
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
import subprocess
import sys
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / 'src'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from coworld.config import resolve_episode_config
from coworld.episode import canonical_results_payload, run_episode
from coworld.targets import load_target_catalog, resolve_seat_targets
from players.baseline.player import choose_ruleset


def run_world(config: dict[str, object]) -> dict[str, object]:
    resolved = resolve_episode_config(config)
    targets = resolve_seat_targets(
        resolved.get('targets'), seats=int(resolved['seats']),
        measurement_window=int(resolved['measurement_window']), catalog=load_target_catalog(),
    )
    rulesets = [choose_ruleset(target.as_dict()) for target in targets]
    results, replay, _ = run_episode(config, rulesets, emit_timing_logs=False)
    return {
        'seed': resolved['seed'], 'config': resolved, 'rulesets': rulesets,
        'timesteps_completed': results['timesteps_completed'],
        'population_final': results['result.population_final'],
        'world_width': resolved['environmentWidth'], 'world_height': resolved['environmentHeight'],
        'results_sha256': hashlib.sha256(canonical_results_payload(results)).hexdigest(),
        'replay_sha256': hashlib.sha256(replay).hexdigest(),
        'replay_bytes': len(replay),
    }


def benchmark(config: dict[str, object], *, workers: int, worlds: int, seed: int) -> dict[str, object]:
    if workers < 1 or worlds < 1 or seed < 0:
        raise ValueError('workers/worlds must be positive and seed nonnegative')
    # Spawned interpreters must agree on hashes used by DTL inheritance.
    os.environ['PYTHONHASHSEED'] = '0'
    configs = [{**config, 'seed': seed + index} for index in range(worlds)]
    started = perf_counter()
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        completed = list(pool.map(run_world, configs))
    elapsed = perf_counter() - started
    ticks = sum(world['timesteps_completed'] for world in completed)
    rate = ticks / elapsed
    return {
        'backend': 'cpu', 'metric': 'completed_whole_world_ticks_per_wall_second',
        'timing_scope': 'end-to-end: process startup/shutdown, episode setup, simulation, statistics, scoring, replay and result transfer',
        'workers': workers, 'world_count': worlds, 'elapsed_seconds': elapsed,
        'completed_world_ticks': ticks, 'world_ticks_per_second': rate,
        'target_world_ticks_per_second': 30000, 'target_met': rate >= 30000,
        'worlds': completed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
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
        report = benchmark(config, workers=args.workers, worlds=args.worlds, seed=args.seed)
        report['metadata'] = metadata
        json.dump(report, file, indent=2, allow_nan=False)
    print(json.dumps({'report': str(output), 'world_ticks_per_second': report['world_ticks_per_second'], 'target_met': report['target_met']}))


if __name__ == '__main__':
    main()
