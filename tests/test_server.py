from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from urllib.request import urlopen

import pytest
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.sync.client import connect

from coworld.replay import decode_replay
from coworld.server import SugarscapeServer, atomic_write_uri, public_config


ROOT = Path(__file__).resolve().parents[1]


def test_public_config_removes_all_information_hygiene_fields(
    tiny_episode_config: dict[str, object],
) -> None:
    config = {
        **tiny_episode_config,
        "seed": 123,
        "tokens": ["one", "two"],
        "targets": ["wealth.skewed-gini-0.5", "wealth.egalitarian"],
        "scenario_index": 1,
        "scenario_pool": [{"targets": ["secret-a", "secret-b"]}],
        "nested": {"tokens": ["also-secret"], "mechanic": 7},
    }

    sanitized = public_config(config)

    assert "seed" not in sanitized
    assert "tokens" not in sanitized
    assert "targets" not in sanitized
    assert "scenario_index" not in sanitized
    assert "scenario_pool" not in sanitized
    assert sanitized["nested"] == {"mechanic": 7}
    assert sanitized["startingAgents"] == tiny_episode_config["startingAgents"]


def test_atomic_file_uri_write_replaces_complete_payload(tmp_path: Path) -> None:
    destination = tmp_path / "artifact.bin"
    destination.write_bytes(b"old")

    atomic_write_uri(destination.as_uri(), b"complete-new-payload")

    assert destination.read_bytes() == b"complete-new-payload"
    assert list(tmp_path.iterdir()) == [destination]


def test_artifact_upload_does_not_block_websocket_event_loop(
    tiny_episode_config: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow hosted artifact PUT must not delay protocol-level Pong frames."""

    upload_started = threading.Event()
    allow_upload = threading.Event()
    write_count = 0

    def fake_run_episode(*_args: object, **_kwargs: object):
        return (
            {
                "scores": [1.0, 1.0],
                "details": [{}, {}],
                "score.match_mean": 1.0,
                "score.match_min": 1.0,
                "result.population_final": 8,
            },
            b"replay",
            {},
        )

    def slow_artifact_write(_uri: str, _data: bytes) -> int:
        nonlocal write_count
        write_count += 1
        if write_count == 1:
            upload_started.set()
            if not allow_upload.wait(timeout=1):
                raise AssertionError("artifact upload blocked the WebSocket event loop")
        return 1

    monkeypatch.setattr("coworld.server.run_episode", fake_run_episode)
    monkeypatch.setattr("coworld.server._timed_atomic_write", slow_artifact_write)
    monkeypatch.setattr("coworld.server._encode_results", lambda _results: b"{}")

    config = {
        **tiny_episode_config,
        "tokens": ["zero", "one"],
        "players": [{"name": "Zero"}, {"name": "One"}],
        "targets": ["wealth.skewed-gini-0.5", "wealth.egalitarian"],
        "measurement_window": 2,
    }
    server = SugarscapeServer(config, "https://results.test", "https://replay.test")

    async def exercise() -> None:
        episode = asyncio.create_task(server._execute_episode(asyncio.get_running_loop()))
        assert await asyncio.to_thread(upload_started.wait, 0.5)
        allow_upload.set()
        await asyncio.wait_for(episode, timeout=1)

    asyncio.run(exercise())
    assert write_count == 2


def test_server_entry_reexecutes_with_zero_hash_seed() -> None:
    environment = os.environ.copy()
    environment.update({"PYTHONHASHSEED": "1", "PYTHONPATH": str(ROOT / "src")})
    completed = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "coworld.server", "--help"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Sugarscape v3 coworld server" in completed.stdout


def test_server_end_to_end_contract(tmp_path: Path) -> None:
    config = json.loads((ROOT / "tests" / "fixtures" / "certification-config.json").read_text())
    config.update(
        {
            "tokens": ["token-zero", "token-one"],
            "players": [{"name": "Zero"}, {"name": "One"}],
            "player_connect_timeout_seconds": 5,
            # These tests drive the episode to completion and then wait for the
            # process to EXIT, so they opt out of the post-episode grace that
            # keeps /global reachable for the hosted certifier's probe.
            # test_global_answers_a_ping_after_the_episode_has_finished is the
            # one that needs it, and sets its own.
            "spectator_grace_seconds": 0,
        }
    )
    config_path = tmp_path / "config.json"
    results_path = tmp_path / "results.json"
    replay_path = tmp_path / "replay.bin"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    port = _unused_port()
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": str(ROOT / "src"),
            "COGAME_HOST": "127.0.0.1",
            "COGAME_PORT": str(port),
            "COGAME_CONFIG_URI": config_path.as_uri(),
            "COGAME_RESULTS_URI": results_path.as_uri(),
            "COGAME_SAVE_REPLAY_URI": replay_path.as_uri(),
        }
    )
    process = subprocess.Popen(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "coworld.server"],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_http = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(base_http, process)
        assert urlopen(f"{base_http}/healthz").read() == b"ok\n"
        assert b"Sugarscape player" in urlopen(
            f"{base_http}/client/player?slot=0&token=token-zero"
        ).read()
        assert b"Sugarscape spectator" in urlopen(f"{base_http}/client/global").read()

        with pytest.raises(InvalidStatus) as bad_token:
            connect(f"ws://127.0.0.1:{port}/player?slot=0&token=wrong", proxy=None)
        assert bad_token.value.response.status_code == 403
        with pytest.raises(InvalidStatus) as bad_slot:
            connect(f"ws://127.0.0.1:{port}/player?slot=9&token=token-zero", proxy=None)
        assert bad_slot.value.response.status_code == 403

        oversized = connect(
            f"ws://127.0.0.1:{port}/player?slot=0&token=token-zero",
            proxy=None,
        )
        oversized.recv()
        with pytest.raises(InvalidStatus) as duplicate:
            connect(f"ws://127.0.0.1:{port}/player?slot=0&token=token-zero", proxy=None)
        assert duplicate.value.response.status_code == 409
        oversized.send("x" * (64 * 1024 + 1))
        with pytest.raises(ConnectionClosedError) as oversized_close:
            oversized.recv()
        assert oversized_close.value.rcvd is not None
        assert oversized_close.value.rcvd.code == 1009
        oversized.close()

        player_zero = _retry_connect(
            f"ws://127.0.0.1:{port}/player?slot=0&token=token-zero"
        )
        player_one = connect(
            f"ws://127.0.0.1:{port}/player?slot=1&token=token-one",
            proxy=None,
        )
        spectator = connect(f"ws://127.0.0.1:{port}/global", proxy=None)
        # The hosted runner's viewer probe fails the episode unless /global
        # produces a message within 10 s of connecting — long before any
        # player has submitted. The greeting must arrive immediately.
        greeting = json.loads(spectator.recv(timeout=5))
        assert greeting["type"] == "status"
        assert greeting["phase"] == "submission_window"
        assert greeting["seats"] == 2
        observation_zero = json.loads(player_zero.recv())
        observation_one = json.loads(player_one.recv())
        assert observation_zero["type"] == "observation"
        assert observation_zero["protocol"] == "sugarscape-v3/1"
        assert observation_zero["target"]["id"] == "wealth.skewed-gini-0.5"
        assert observation_one["target"]["id"] == "wealth.egalitarian"
        for observation in (observation_zero, observation_one):
            assert "seed" not in observation["config"]
            assert "tokens" not in observation["config"]
            assert "targets" not in observation["config"]
            assert observation["ruleset_schema"]["limits"]["max_bytes"] == 32_768

        invalid_action = {
            "type": "action",
            "ruleset": {"version": 1, "movement": [{"score": ["bogus", 1]}]},
        }
        player_zero.send(json.dumps(invalid_action))
        invalid_ack = json.loads(player_zero.recv())
        assert invalid_ack["type"] == "ack"
        assert invalid_ack["valid"] is False
        assert invalid_ack["errors"]

        player_zero.send(json.dumps({"type": "action", "ruleset": None}))
        player_one.send(json.dumps({"type": "action", "ruleset": None}))
        assert json.loads(player_zero.recv()) == {"type": "ack", "valid": True}
        assert json.loads(player_one.recv()) == {"type": "ack", "valid": True}
        terminal_zero = json.loads(player_zero.recv())
        terminal_one = json.loads(player_one.recv())
        assert terminal_zero["type"] == terminal_one["type"] == "result"
        assert len(terminal_zero["scores"]) == 2

        spectator_messages = []
        while True:
            message = json.loads(spectator.recv())
            spectator_messages.append(message)
            if message["type"] == "result":
                break
        assert any(message["type"] == "frame" for message in spectator_messages)
        player_zero.close()
        player_one.close()
        spectator.close()

        output, _ = process.communicate(timeout=10)
        assert process.returncode == 0, output
        results = json.loads(results_path.read_text(encoding="utf-8"))
        assert len(results["scores"]) == 2
        assert "server" in results["timings"]
        assert "artifact_writes" in results["timings"]
        assert results["timings"]["artifact_writes"]["results_provisional_payload_ns"] > 0
        assert results["result.replay_compressed_bytes"] == replay_path.stat().st_size
        replay = decode_replay(replay_path.read_bytes())
        assert len(replay["frames"]) == config["timesteps"]
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_certification_fixture_completes_with_bundled_baseline_players(tmp_path: Path) -> None:
    config = json.loads((ROOT / "tests" / "fixtures" / "certification-config.json").read_text())
    config.update(
        {
            "tokens": ["baseline-zero", "baseline-one"],
            "players": [{"name": "Baseline 0"}, {"name": "Baseline 1"}],
            "player_connect_timeout_seconds": 5,
            # These tests drive the episode to completion and then wait for the
            # process to EXIT, so they opt out of the post-episode grace that
            # keeps /global reachable for the hosted certifier's probe.
            # test_global_answers_a_ping_after_the_episode_has_finished is the
            # one that needs it, and sets its own.
            "spectator_grace_seconds": 0,
        }
    )
    config_path = tmp_path / "config.json"
    results_path = tmp_path / "results.json"
    replay_path = tmp_path / "replay.bin"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    port = _unused_port()
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": str(ROOT / "src"),
            "COGAME_HOST": "127.0.0.1",
            "COGAME_PORT": str(port),
            "COGAME_CONFIG_URI": config_path.as_uri(),
            "COGAME_RESULTS_URI": results_path.as_uri(),
            "COGAME_SAVE_REPLAY_URI": replay_path.as_uri(),
        }
    )
    game = subprocess.Popen(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "coworld.server"],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_health(f"http://127.0.0.1:{port}", game)
        players = []
        for slot, token in enumerate(config["tokens"]):
            player_environment = environment.copy()
            player_environment["PYTHONPATH"] = str(ROOT)
            player_environment["COWORLD_PLAYER_WS_URL"] = (
                f"ws://127.0.0.1:{port}/player?slot={slot}&token={token}"
            )
            players.append(
                subprocess.Popen(
                    [str(ROOT / ".venv" / "bin" / "python"), "-m", "players.baseline.player"],
                    cwd=ROOT,
                    env=player_environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            )
        for player in players:
            output, _ = player.communicate(timeout=10)
            assert player.returncode == 0, output
        game_output, _ = game.communicate(timeout=10)
        assert game.returncode == 0, game_output
        results = json.loads(results_path.read_text(encoding="utf-8"))
        assert len(results["scores"]) == 2
        assert all(detail["submitted"] for detail in results["details"])
        assert replay_path.stat().st_size == results["result.replay_compressed_bytes"]
    finally:
        if game.poll() is None:
            game.terminate()
            game.wait(timeout=5)


def _unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(base_http: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output, _ = process.communicate()
            raise AssertionError(f"server exited before health check:\n{output}")
        try:
            with urlopen(f"{base_http}/healthz", timeout=0.2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.02)
    raise AssertionError("server didn't become healthy")


def _retry_connect(url: str):
    deadline = time.monotonic() + 2
    while True:
        try:
            return connect(url, proxy=None)
        except InvalidStatus as error:
            if error.response.status_code != 409 or time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def test_global_answers_a_ping_after_the_episode_has_finished(
    tmp_path: Path,
    tiny_episode_config: dict[str, object],
) -> None:
    """A finished /global connection must survive until the certifier pings it.

    This is the failure that kept every published version uncertified — the
    reported reason being "Game websocket did not answer a WebSocket Ping with
    Pong: ws://127.0.0.1:8080/global". Three causes are covered here:

    1. The server closed as soon as its already-connected readers drained, which
       on a small config is ~2 s after start. The probe arrived at nothing.
    2. Once it outlived the episode, a finished spectator was sent the result and
       immediately disconnected from THIS side, so the ping met a closed socket.
    3. The hosted certifier connects before the episode but waits for Kubernetes
       player pods to start before sending Ping. Reusing the late-arrival grace
       for that established connection closed it while the certifier was waiting.

    This test reaches the same terminal lifecycle directly: finish the episode,
    connect inside the late-arrival grace, wait beyond that grace, then ping.
    """

    config = {
        **tiny_episode_config,
        "seed": 7,
        "seats": 1,
        "players": [{"name": "solo"}],
        "tokens": ["token-zero"],
        "targets": ["wealth.skewed-gini-0.5"],
        # The hosted certifier connects first, then waits for Kubernetes player
        # pods to start before it sends Ping. Keep the late-arrival grace short
        # here so this test proves an established spectator outlives that wait.
        "spectator_grace_seconds": 0.2,
        "player_connect_timeout_seconds": 2,
    }
    config_path = tmp_path / "config.json"
    results_path = tmp_path / "results.json"
    replay_path = tmp_path / "replay.bin"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    port = _unused_port()
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": str(ROOT / "src"),
            "COGAME_HOST": "127.0.0.1",
            "COGAME_PORT": str(port),
            "COGAME_CONFIG_URI": config_path.as_uri(),
            "COGAME_RESULTS_URI": results_path.as_uri(),
            "COGAME_SAVE_REPLAY_URI": replay_path.as_uri(),
        }
    )
    process = subprocess.Popen(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "coworld.server"],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_health(f"http://127.0.0.1:{port}", process)
        # Play the episode out so the server reaches its post-episode state.
        player = _retry_connect(f"ws://127.0.0.1:{port}/player?slot=0&token=token-zero")
        json.loads(player.recv(timeout=15))  # observation
        # `type: action` with a null ruleset is the documented "no ruleset"
        # submission the other tests use; it closes the window and runs the world.
        player.send(json.dumps({"type": "action", "ruleset": None}))
        deadline = time.time() + 60
        while time.time() < deadline and not results_path.exists():
            time.sleep(0.2)
        player.close()
        assert results_path.exists(), "the episode never wrote its results"

        # Reproduce the certifier's established-but-delayed Ping lifecycle.
        spectator = connect(f"ws://127.0.0.1:{port}/global", proxy=None)
        try:
            assert json.loads(spectator.recv(timeout=10))["type"] in {"status", "result"}
            time.sleep(0.3)
            # ping() returns once the peer's Pong comes back; a closed or
            # unresponsive socket raises instead.
            spectator.ping().wait(timeout=10)
            spectator.ping().wait(timeout=10)
        finally:
            spectator.close()
    finally:
        process.terminate()
        process.wait(timeout=30)
