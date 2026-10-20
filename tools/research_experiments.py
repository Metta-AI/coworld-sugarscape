#!/usr/bin/env python3
"""Run named paper variants through the public game/player protocol before league evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from coworld.config import resolve_episode_config  # noqa: E402


def run_variant(variant, seed: int, output: Path, timesteps: int | None):
    output.mkdir(parents=True, exist_ok=False)
    config = {
        **variant["game_config"],
        "seed": seed,
        "tokens": ["local-research-controller"],
        "spectator_grace_seconds": 0,
        "player_connect_timeout_seconds": 10.0,
    }
    if timesteps is not None:
        config["timesteps"] = timesteps
    config = resolve_episode_config(config)
    config_path = output / "config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    results, replay = output / "results.json", output / "replay.bin"
    worker_paths = {
        "COWORLD_RESEARCH_PYTHON": ROOT / ".research-venv/bin/python",
        "COWORLD_RESEARCH_PYTHON_DOGAN": ROOT / ".dogan-venv/bin/python",
    }
    native_paths = {
        "COWORLD_NETLOGO_5": ROOT / "build/research-runtimes/netlogo-5.3.1",
        "COWORLD_NETLOGO_6": ROOT / "build/research-runtimes/netlogo-6.1.1",
    }
    environment = {
        **{name: str(path) for name, path in native_paths.items()},
        **{name: str(path) for name, path in worker_paths.items()},
        **os.environ,
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": str(ROOT / "src"),
        "COGAME_PLAYER_FAILURE_URI": (output / "player-failure.json").as_uri(),
    }
    command = [
        sys.executable,
        "-m",
        "coworld.server",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--config-uri",
        config_path.as_uri(),
        "--results-uri",
        results.as_uri(),
        "--replay-uri",
        replay.as_uri(),
    ]
    (output / "request.json").write_text(
        json.dumps(
            {
                "variant": variant["id"],
                "command": command,
                "duration_override": timesteps,
                "seed": seed,
            },
            indent=2,
        )
        + "\n"
    )
    with (output / "game.log").open("x") as log:
        server = subprocess.Popen(
            command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT
        )
        try:
            deadline = time.monotonic() + 15
            while '"event":"server_ready"' not in (output / "game.log").read_text():
                if server.poll() is not None:
                    raise RuntimeError(
                        f"game exited before readiness: {output / 'game.log'}"
                    )
                if time.monotonic() >= deadline:
                    raise TimeoutError("game readiness deadline exceeded")
                time.sleep(0.05)
            player_environment = {
                **environment,
                "COWORLD_PLAYER_WS_URL": f"ws://127.0.0.1:{port}/player?slot=0&token=local-research-controller",
            }
            with (output / "player.log").open("x") as player_log:
                player = subprocess.run(
                    [sys.executable, "-m", "players.baseline.player"],
                    cwd=ROOT,
                    env=player_environment,
                    stdout=player_log,
                    stderr=subprocess.STDOUT,
                    timeout=30,
                )
            if player.returncode != 0:
                raise RuntimeError(f"baseline player failed: {output / 'player.log'}")
            code = server.wait(timeout=600)
            if code != 0:
                raise RuntimeError(f"native episode failed: {output / 'game.log'}")
        finally:
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=10)
    result = json.loads(results.read_bytes())
    if result["result.timesteps_completed"] != config["timesteps"]:
        raise ValueError("native episode did not complete its declared horizon")
    return {
        "variant": variant["id"],
        "seed": seed,
        "scores": result["scores"],
        "details": result["details"],
        "replay_sha256": hashlib.sha256(replay.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", action="append", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1729])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--timesteps",
        type=int,
        help="Explicit smoke duration; recorded separately from the study horizon",
    )
    args = parser.parse_args()
    if len(args.seeds) != len(set(args.seeds)) or any(seed < 0 for seed in args.seeds):
        parser.error("seeds must be distinct non-negative integers")
    if len(args.variant) != len(set(args.variant)):
        parser.error("variants must be distinct")
    manifest = json.loads((ROOT / "coworld_manifest.json").read_bytes())
    variants = {
        v["id"]: v for v in manifest["variants"] if "research" in v["game_config"]
    }
    if not set(args.variant) <= set(variants):
        parser.error("available research variants: " + ", ".join(variants))
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    records = [
        run_variant(variants[name], seed, output / name / str(seed), args.timesteps)
        for name in args.variant
        for seed in args.seeds
    ]
    report = {
        "episodes": records,
        "manifest_sha256": hashlib.sha256(
            (ROOT / "coworld_manifest.json").read_bytes()
        ).hexdigest(),
        "scope": "Completed local game and player processes using the public WebSocket protocol. Not hosted certification or a full study campaign.",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {"completed_episodes": len(records), "report": str(output / "report.json")}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
