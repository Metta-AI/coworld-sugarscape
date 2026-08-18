#!/usr/bin/env python3
"""Benchmark real replay ingestion and painting in headless Chrome.

The harness regenerates two shipped 1,000-tick scenarios with a fixed seed,
loads their compressed artifacts through the self-contained viewer, forces
garbage collection through Chrome DevTools Protocol, and prints JSON metrics.

    .venv/bin/python tools/benchmark_replay_viewer.py
    .venv/bin/python tools/benchmark_replay_viewer.py --output build/viewer-perf.json

The Phase 0 commit recorded a baseline without enforcing the approved
post-FrameStore heap budgets. The current harness enforces them and also checks
every materialized frame against the independent eager Python converter.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TOOLS))

from coworld.episode import run_episode  # noqa: E402
from coworld.v1_frames import convert_document  # noqa: E402
from generate_scenario_pool import load_manifest, solo_ladder_config  # noqa: E402
from v3_to_v1_replay import load_v3  # noqa: E402

SCENARIOS = (
    ("capacity.compact-regrow-1", 6 * 1024 * 1024),
    # This 56x56, 320-agent replacement is smaller than the retired 60x60,
    # 400-agent dense case. Keep 10 MiB pending the next real browser run.
    ("capacity.sparse-regrow-2", 10 * 1024 * 1024),
)
SEED = 11


def find_chrome(explicit: str | None) -> Path:
    candidates = [
        explicit,
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise SystemExit("Chrome or Chromium not found; pass --chrome /path/to/browser")


def generate_replays(directory: Path) -> list[dict[str, object]]:
    manifest = load_manifest()
    ladder_config = deepcopy(solo_ladder_config(manifest))
    scenario_pool = {
        scenario["id"]: scenario
        for scenario in ladder_config.pop("scenario_pool")
    }
    ladder_config.pop("seed", None)
    replays: list[dict[str, object]] = []
    for scenario, retained_budget in SCENARIOS:
        pool_entry = scenario_pool[scenario]
        config = deepcopy(ladder_config)
        config.update(deepcopy(pool_entry["config_overrides"]))
        config["targets"] = deepcopy(pool_entry["targets"])
        config["seed"] = SEED
        started = perf_counter()
        results, replay, _ = run_episode(config, [None], emit_timing_logs=False)
        generation_ms = (perf_counter() - started) * 1000
        replay_path = directory / f"{scenario}.replay"
        replay_path.write_bytes(replay)
        oracle_path = directory / f"{scenario}.v1.json"
        oracle_path.write_text(
            json.dumps(convert_document(load_v3(replay_path)), separators=(",", ":")),
            encoding="utf-8",
        )
        replays.append(
            {
                "scenario": scenario,
                "path": str(replay_path),
                "oracle_path": str(oracle_path),
                "compressed_bytes": len(replay),
                "raw_bytes": int(results["result.replay_raw_bytes"]),
                "expected_frames": int(config["timesteps"]) + 1,
                "generation_ms": round(generation_ms, 3),
                "retained_budget_bytes": retained_budget,
            }
        )
    return replays


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", help="Chrome/Chromium executable")
    parser.add_argument("--output", type=Path, help="also write the JSON report here")
    args = parser.parse_args()

    chrome = find_chrome(args.chrome)
    with tempfile.TemporaryDirectory(prefix="sugarscape-viewer-bench-") as temporary:
        directory = Path(temporary)
        browser_results: list[dict[str, object]] = []
        for index, replay in enumerate(generate_replays(directory)):
            # One Chrome process per case gives each replay a genuine empty-page
            # heap baseline; navigated-away renderer heaps otherwise skew later
            # cases even after a forced collection.
            manifest = {
                "viewer": str(ROOT / "replay-viewer" / "index.html"),
                "chrome": str(chrome),
                "seed": SEED,
                "budgets_enforced": True,
                "paint_budgets_enforced": True,
                "replays": [replay],
            }
            manifest_path = directory / f"manifest-{index}.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            completed = subprocess.run(
                ["node", str(TOOLS / "benchmark_replay_viewer.mjs"), str(manifest_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                sys.stderr.write(completed.stderr)
                return completed.returncode
            browser_results.extend(json.loads(completed.stdout)["results"])
        report = {
            "browser": str(chrome),
            "budgets_enforced": True,
            "paint_budgets_enforced": True,
            "results": browser_results,
        }

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    sys.stdout.write(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
