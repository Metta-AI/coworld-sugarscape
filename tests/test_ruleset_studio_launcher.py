from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from tools import ruleset_studio as launcher


ROOT = Path(__file__).resolve().parents[1]
RULESET = json.loads((ROOT / "rulesets" / "worked-example.json").read_text())


def unused_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def write_link_server(path: Path) -> None:
    path.write_text(
        """
import http from "node:http";
const server = http.createServer((_request, response) => {
  response.writeHead(200, {"content-type": "text/plain"});
  response.end("ready");
});
server.listen(Number(process.env.LINK_PORT), "localhost");
for (const name of ["SIGINT", "SIGTERM"]) process.on(name, () => server.close(() => process.exit(0)));
""".strip(),
        encoding="utf-8",
    )


def fetch_json(request: Request | str) -> tuple[int, dict[str, object]]:
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as error:
        response = error
    return response.status, json.loads(response.read())


def launch_once(tmp_path: Path, link_server: Path, suffix: str) -> bytes:
    link_port, api_port, run_port = unused_port(), unused_port(), unused_port()
    runs = tmp_path / f"runs-{suffix}"
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools/ruleset_studio.py"),
            "--no-open",
            "--link-server", str(link_server),
            "--link-port", str(link_port),
            "--api-port", str(api_port),
            "--run-port", str(run_port),
            "--runs-dir", str(runs),
        ],
        cwd=ROOT,
        env={key: value for key, value in os.environ.items() if key != "PYTHONHASHSEED"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    api_origin = f"http://127.0.0.1:{api_port}"
    link_origin = f"http://localhost:{link_port}"
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(process.stdout.read().decode())
            try:
                if fetch_json(f"{api_origin}/api/context")[0] == 200:
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("launcher API did not become ready")
        request = Request(
            f"{api_origin}/api/run",
            data=json.dumps({"ruleset": RULESET, "variant": "local-default", "mode": "fixed", "seed": "9007199254740993", "timesteps": 8}).encode(),
            headers={"Content-Type": "application/json", "Origin": link_origin},
            method="POST",
        )
        status, started = fetch_json(request)
        assert status == 202
        run_id = str(started["run_id"])
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status, run = fetch_json(f"{api_origin}/api/run/{run_id}")
            assert status == 200
            if run["state"] == "done":
                return (runs / run_id / "replay.bin").read_bytes()
            time.sleep(0.05)
        raise AssertionError("studio run did not finish")
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
        process.wait(timeout=15)
        assert process.returncode == 0, process.stdout.read().decode()


def test_link_server_precedence_and_page_origins(tmp_path: Path) -> None:
    environment_server = tmp_path / "environment.mjs"
    argument_server = tmp_path / "argument.mjs"
    environment_server.write_text("", encoding="utf-8")
    argument_server.write_text("", encoding="utf-8")
    assert launcher.resolve_link_server(None, tmp_path, {"COWORLD_STUDIO_LINK_SERVER": str(environment_server)}) == environment_server
    assert launcher.resolve_link_server(argument_server, tmp_path, {"COWORLD_STUDIO_LINK_SERVER": str(environment_server)}) == argument_server
    with pytest.raises(FileNotFoundError, match="COWORLD_STUDIO_LINK_SERVER"):
        launcher.resolve_link_server(tmp_path / "missing.mjs", tmp_path, {})
    config = launcher.LauncherConfig(tmp_path, argument_server, 19001, 19002, 19003, tmp_path / "runs", 1, False)
    assert config.page_url == "http://localhost:19001/?api=http%3A%2F%2F127.0.0.1%3A19002&run=http%3A%2F%2Flocalhost%3A19003"


def test_hash_seed_reexec_preserves_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def execve(executable: str, arguments: list[str], environment: dict[str, str]) -> None:
        captured.update(executable=executable, arguments=arguments, environment=environment)
        raise RuntimeError("captured")

    monkeypatch.setenv("PYTHONHASHSEED", "17")
    monkeypatch.setattr(os, "execve", execve)
    monkeypatch.setattr(sys, "argv", ["ruleset_studio.py", "--no-open"])
    with pytest.raises(RuntimeError, match="captured"):
        launcher._reexec_with_deterministic_hash_seed()
    assert captured["arguments"] == [sys.executable, "ruleset_studio.py", "--no-open"]
    assert captured["environment"]["PYTHONHASHSEED"] == "0"


def test_signal_during_link_death_drain_cancels_active_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = launcher.LauncherConfig(
        tmp_path,
        tmp_path / "link.mjs",
        19001,
        19002,
        19003,
        tmp_path / "runs",
        1,
        False,
    )
    studio = launcher.StudioLauncher(config)
    studio.link = SimpleNamespace(poll=lambda: 0)

    class StopDuringDrain:
        calls = 0

        def wait(self, _timeout: float) -> bool:
            self.calls += 1
            return self.calls > 1

    studio.stopping = StopDuringDrain()
    monkeypatch.setattr(studio.registry, "stop_accepting", lambda: None)
    monkeypatch.setattr(
        studio.registry,
        "active_worker_snapshot",
        lambda: SimpleNamespace(worker=SimpleNamespace(is_alive=lambda: True)),
    )
    cancelled: list[bool] = []
    monkeypatch.setattr(
        studio,
        "shutdown",
        lambda *, cancel_active: cancelled.append(cancel_active) or True,
    )

    assert studio.serve() == 0
    assert cancelled == [True]


def test_run_tears_down_after_non_io_startup_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdowns: list[bool] = []

    class FailingLauncher:
        def __init__(self, _config: launcher.LauncherConfig) -> None:
            pass

        def request_stop(self, *_args: object) -> None:
            pass

        def start(self) -> tuple[str, Path]:
            raise ValueError("invalid catalog")

        def shutdown(self, *, cancel_active: bool) -> bool:
            shutdowns.append(cancel_active)
            return True

    monkeypatch.setattr(launcher, "StudioLauncher", FailingLauncher)
    config = launcher.LauncherConfig(
        tmp_path,
        tmp_path / "link.mjs",
        19001,
        19002,
        19003,
        tmp_path / "runs",
        1,
        False,
    )

    assert launcher.run(config) == 1
    assert shutdowns == [True]


def test_run_stage_stop_logs_listener_failure_without_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = launcher.RunStageThread(SimpleNamespace(stop=lambda: None))
    assert runner.thread.daemon is True
    runner.thread = SimpleNamespace(
        ident=1,
        join=lambda _timeout: None,
        is_alive=lambda: True,
    )

    assert runner.stop() is False
    assert "run-stage listener did not stop" in caplog.text


def test_shutdown_reports_abandoned_daemon_worker(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = launcher.LauncherConfig(
        tmp_path,
        tmp_path / "link.mjs",
        19001,
        19002,
        19003,
        tmp_path / "runs",
        0.01,
        False,
    )
    studio = launcher.StudioLauncher(config)
    studio.coordinator = SimpleNamespace(shutdown=lambda _timeout: False)

    assert studio.shutdown(cancel_active=True) is False
    assert "abandoning the daemon worker" in capsys.readouterr().err


def test_launcher_is_deterministic_across_fresh_processes(tmp_path: Path) -> None:
    link_server = tmp_path / "link-server.mjs"
    write_link_server(link_server)
    assert launch_once(tmp_path, link_server, "first") == launch_once(tmp_path, link_server, "second")
