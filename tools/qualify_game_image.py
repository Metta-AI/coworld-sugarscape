"""Qualify built images through their default commands and a native oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path


def oracle(root: Path) -> None:
    from coworld.episode import canonical_results_payload, run_episode
    from coworld.replay import decode_replay
    from coworld.server import SugarscapeServer
    from players.baseline.player import choose_ruleset

    config = json.loads((root / "config.json").read_text())
    ruleset = choose_ruleset(
        SugarscapeServer(config, "unused", "unused")._observation(0)["target"]
    )
    results, replay, _ = run_episode(
        config, [ruleset], submitted=[True], emit_timing_logs=False
    )
    served = json.loads((root / "results.json").read_text())
    assert canonical_results_payload(results) == canonical_results_payload(served)
    saved = decode_replay((root / "replay.bin").read_bytes())
    native = decode_replay(replay)
    assert saved["frames"] == native["frames"]
    for key in ["seed", "targets", "rulesets", "initial_agents", "initial_grid"]:
        assert saved["header"][key] == native["header"][key]
    assert len(saved["frames"]) == results["timesteps_completed"]
    (root / "oracle.json").write_text(
        json.dumps(
            {
                "canonical_results_equal": True,
                "all_gameplay_frames_equal": True,
                "ticks": len(saved["frames"]),
                "scores": results["scores"],
                "python": sys.version,
                "replay_sha256": hashlib.sha256(
                    (root / "replay.bin").read_bytes()
                ).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )


def qualify(root: Path, game_image: str, player_image: str) -> None:
    name = "relh-53-image-" + uuid.uuid4().hex
    network = name + "-network"
    owned: list[str] = []
    processes: list[subprocess.Popen] = []
    logs = []

    def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, check=check, timeout=30
        )

    def start(suffix: str, image: str, *args: str) -> str:
        container = name + "-" + suffix
        owned.append(container)
        docker(
            "run",
            "--detach",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--name",
            container,
            "--network",
            network,
            "--mount",
            f"type=bind,src={root},dst=/proof",
            *args,
            image,
        )
        return container

    def wait(container: str, seconds: int = 180) -> int:
        log = (root / (container.rsplit("-", 1)[-1] + "-wait.log")).open("w")
        logs.append(log)
        process = subprocess.Popen(["docker", "wait", container], stdout=log)
        processes.append(process)
        assert process.wait(timeout=seconds) == 0
        log.flush()
        return int(Path(log.name).read_text())

    def terminate(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    docker("network", "create", network)
    try:
        images = {}
        for role, image, command in [
            ("game", game_image, ["python", "-m", "coworld.server"]),
            ("player", player_image, ["python", "-m", "players.baseline.player"]),
        ]:
            identity = json.loads(docker("image", "inspect", image).stdout)[0]
            assert identity["Config"]["Cmd"] == command
            images[role] = identity
        (root / "images.json").write_text(json.dumps(images, indent=2))
        config = json.loads((root / "config.json").read_text())
        assert config["seats"] == 1 and config["seed"] >= 0
        assert config["timesteps"] <= 1000
        assert "scenario_pool" not in config
        assert config["player_connect_timeout_seconds"] <= 30
        config["tokens"] = ["local-image-proof"]
        config["players"] = [{"name": "bundled-baseline"}]
        (root / "config.json").write_text(json.dumps(config))
        environment = [
            "-e",
            "COGAME_CONFIG_URI=file:///proof/config.json",
            "-e",
            "COGAME_RESULTS_URI=file:///proof/results.json",
            "-e",
            "COGAME_SAVE_REPLAY_URI=file:///proof/replay.bin",
        ]
        game = start(
            "game",
            game_image,
            "--cpus=.75",
            "--memory=512m",
            "--network-alias=game",
            *environment,
        )
        ready = False
        for _ in range(30):
            health = docker(
                "exec",
                game,
                "python",
                "-c",
                "import urllib.request; assert urllib.request.urlopen('http://localhost:8080/healthz').status==200",
                check=False,
            )
            if health.returncode == 0:
                ready = True
                break
            time.sleep(0.5)
        assert ready, health.stderr
        docker(
            "exec",
            game,
            "python",
            "-c",
            "import os; os.setpriority(os.PRIO_PROCESS,1,19); assert os.getpriority(os.PRIO_PROCESS,1)==19",
        )
        probe = docker(
            "exec",
            game,
            "python",
            "-c",
            "import http.client; c=http.client.HTTPConnection('localhost',8080); "
            "c.request('GET','/player?slot=0&token=wrong',headers={'Connection':'Upgrade','Upgrade':'websocket',"
            "'Sec-WebSocket-Key':'MTIzNDU2Nzg5MDEyMzQ1Ng==','Sec-WebSocket-Version':'13'}); "
            "r=c.getresponse(); print(r.status); assert r.status==403",
        )
        (root / "invalid-token.log").write_text(probe.stdout + probe.stderr)
        player = start(
            "player",
            player_image,
            "--cpus=.25",
            "--memory=128m",
            "-e",
            "COWORLD_PLAYER_WS_URL=ws://game:8080/player?slot=0&token=local-image-proof",
        )
        assert wait(player, 30) == 0
        assert wait(game) == 0
        assert (root / "results.json").is_file() and (root / "replay.bin").is_file()
        oracle_name = name + "-oracle"
        owned.append(oracle_name)
        docker(
            "run",
            "--detach",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--name",
            oracle_name,
            "--network",
            network,
            "--cpus=1",
            "--memory=512m",
            "--mount",
            f"type=bind,src={root},dst=/proof",
            "--entrypoint=nice",
            "-e",
            "PYTHONPATH=/app/src:/proof/source",
            game_image,
            "-n",
            "19",
            "python",
            "/proof/source/tools/qualify_game_image.py",
            "--oracle",
            "--output",
            "/proof",
        )
        assert wait(oracle_name) == 0
        bad = root / "invalid.json"
        bad.write_text(json.dumps({**config, "tokens": []}))
        invalid = start(
            "invalid",
            game_image,
            "--cpus=.25",
            "--memory=128m",
            "-e",
            "COGAME_CONFIG_URI=file:///proof/invalid.json",
            "-e",
            "COGAME_RESULTS_URI=file:///proof/invalid-results.json",
            "-e",
            "COGAME_SAVE_REPLAY_URI=file:///proof/invalid-replay.bin",
        )
        assert wait(invalid, 30) != 0
        assert not (root / "invalid-results.json").exists()
        (root / "acceptance.json").write_text(
            json.dumps(
                {
                    "default_game_and_player_commands": True,
                    "invalid_token_status": 403,
                    "invalid_config_refused_without_results": True,
                    "oracle": json.loads((root / "oracle.json").read_text()),
                },
                indent=2,
            )
            + "\n"
        )
    finally:
        for container in owned:
            if docker("inspect", container, check=False).returncode == 0:
                docker("stop", "--time=5", container)
                docker("wait", container)
                (root / (container.rsplit("-", 1)[-1] + ".log")).write_text(
                    docker("logs", container, check=False).stdout
                    + docker("logs", container, check=False).stderr
                )
                (root / (container.rsplit("-", 1)[-1] + "-inspect.json")).write_text(
                    docker("inspect", container).stdout
                )
                docker("rm", container)
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=30)
        for log in logs:
            log.close()
        docker("network", "rm", network)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--game-image")
    parser.add_argument("--player-image")
    parser.add_argument("--oracle", action="store_true")
    args = parser.parse_args()
    if args.oracle:
        oracle(args.output)
    else:
        assert args.game_image and args.player_image
        qualify(args.output.resolve(), args.game_image, args.player_image)
