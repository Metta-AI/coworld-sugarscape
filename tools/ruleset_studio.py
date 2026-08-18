#!/usr/bin/env python3
"""Launch Ruleset Studio, its local APIs, and the ux.surface bridge."""

from __future__ import annotations

import os
import sys


def _reexec_with_deterministic_hash_seed() -> None:
    if os.environ.get("PYTHONHASHSEED") == "0":
        return
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    os.execve(sys.executable, [sys.executable, *sys.argv], environment)


if __name__ == "__main__":
    _reexec_with_deterministic_hash_seed()


import argparse
import asyncio
from dataclasses import dataclass
import importlib.util
import logging
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
from threading import Event, Thread
import time
from types import ModuleType
from typing import Sequence
from urllib.parse import urlencode
import urllib.request
import webbrowser


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from coworld.server import StudioRunStageServer  # noqa: E402
from coworld.studio import StudioVariantCatalog  # noqa: E402
from coworld.studio_runs import ArtifactStore, RunCoordinator, RunRegistry  # noqa: E402


_LOGGER = logging.getLogger(__name__)
DEFAULT_METTA_ROOT = Path.home() / "coding" / "metta"
LINK_APP = Path("agent-plugins/ux/skills/ux.surface/app")
DEFAULT_SHUTDOWN_TIMEOUT = 10.0


def available_port(preferred: int, *, excluded: set[int] | None = None) -> int:
    """Return a free loopback port, avoiding ports already chosen by the launcher."""

    excluded = excluded or set()
    choices = [preferred, 0] if preferred else [0]
    for choice in choices:
        with socket.socket() as candidate:
            try:
                candidate.bind(("127.0.0.1", choice))
            except OSError:
                continue
            port = int(candidate.getsockname()[1])
            if port not in excluded:
                return port
    return available_port(0, excluded=excluded)


def resolve_link_server(
    argument: str | Path | None,
    metta_root: Path,
    environment: dict[str, str] | None = None,
) -> Path:
    environ = environment if environment is not None else os.environ
    configured = argument or environ.get("COWORLD_STUDIO_LINK_SERVER")
    path = Path(configured).expanduser() if configured else metta_root / LINK_APP / "link-server.mjs"
    if not path.is_file():
        raise FileNotFoundError(
            f"ux.surface link-server not found at {path}. "
            "Pass --link-server PATH or set COWORLD_STUDIO_LINK_SERVER."
        )
    return path.resolve()


def discover(
    metta_root: Path,
    link_server: str | Path | None = None,
    environment: dict[str, str] | None = None,
) -> tuple[str, Path, Path]:
    node = shutil.which("node")
    bridge = metta_root / LINK_APP / "link-bridge.mjs"
    try:
        server = resolve_link_server(link_server, metta_root, environment)
    except FileNotFoundError:
        environ = environment if environment is not None else os.environ
        configured = link_server or environ.get("COWORLD_STUDIO_LINK_SERVER")
        server = Path(configured).expanduser() if configured else metta_root / LINK_APP / "link-server.mjs"
        missing = [str(server)]
    else:
        missing = []
    for path in (REPO_ROOT / "ruleset-studio/server.py", REPO_ROOT / "ruleset-studio/src", bridge):
        if not path.exists():
            missing.append(str(path))
    if node is None:
        missing.append("node executable on PATH")
    if missing:
        raise RuntimeError(
            "Ruleset Studio prerequisites are missing:\n  "
            + "\n  ".join(missing)
            + "\nUse --link-server PATH or COWORLD_STUDIO_LINK_SERVER to override the link server."
        )
    return node, server, bridge


def _load_studio_server() -> ModuleType:
    path = REPO_ROOT / "ruleset-studio" / "server.py"
    spec = importlib.util.spec_from_file_location("ruleset_studio_server", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load Studio API module at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def wait_url(url: str, label: str, *, process: subprocess.Popen[bytes] | None = None, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not ready"
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"{label} exited during startup with status {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=0.25) as response:
                if response.status < 500:
                    return
        except OSError as error:
            last_error = str(error)
        time.sleep(0.05)
    raise RuntimeError(f"{label} did not become ready: {last_error}")


def stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def bridge_command(node: str, link_bridge: Path, port: int) -> str:
    return f"LINK_PORT={port} {shlex.quote(node)} {shlex.quote(str(link_bridge))} watch"


class RunStageThread:
    def __init__(self, server: StudioRunStageServer) -> None:
        self.server = server
        self.error: BaseException | None = None
        self.thread = Thread(target=self._run, name="studio-run-stage", daemon=True)

    def start(self, timeout: float = 8.0) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while self.server.bound_port is None:
            if self.error is not None:
                raise RuntimeError("run-stage listener failed") from self.error
            if time.monotonic() >= deadline:
                raise RuntimeError("run-stage listener did not become ready")
            time.sleep(0.01)

    def stop(self) -> bool:
        if self.thread.ident is None:
            return True
        self.server.stop()
        self.thread.join(5)
        if self.thread.is_alive():
            _LOGGER.error("run-stage listener did not stop")
            return False
        if self.error is not None:
            _LOGGER.error(
                "run-stage listener failed during shutdown",
                exc_info=(type(self.error), self.error, self.error.__traceback__),
            )
            return False
        return True

    def _run(self) -> None:
        try:
            asyncio.run(self.server.serve())
        except BaseException as error:
            self.error = error


@dataclass(frozen=True, slots=True)
class LauncherConfig:
    metta_root: Path
    link_server: Path
    link_port: int
    api_port: int
    run_port: int
    runs_dir: Path
    shutdown_timeout: float
    open_browser: bool

    @property
    def link_origin(self) -> str:
        return f"http://localhost:{self.link_port}"

    @property
    def api_origin(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def run_origin(self) -> str:
        return f"http://localhost:{self.run_port}"

    @property
    def page_url(self) -> str:
        return f"{self.link_origin}/?{urlencode({'api': self.api_origin, 'run': self.run_origin})}"


class StudioLauncher:
    def __init__(self, config: LauncherConfig) -> None:
        self.config = config
        self.registry = RunRegistry()
        self.artifacts = ArtifactStore(config.runs_dir)
        self.coordinator: RunCoordinator | None = None
        self.run_stage: StudioRunStageServer | None = None
        self.run_thread: RunStageThread | None = None
        self.api = None
        self.api_thread: Thread | None = None
        self.link: subprocess.Popen[bytes] | None = None
        self.stopping = Event()
        self._shutdown_result: bool | None = None

    def start(self) -> tuple[str, Path]:
        node, link_server, bridge = discover(self.config.metta_root, self.config.link_server)
        catalog = StudioVariantCatalog.load()
        run_stage = StudioRunStageServer(
            run_exists=lambda run_id: self.coordinator is not None and self.coordinator.has_run(run_id),
            live_run_exists=lambda run_id: self.coordinator is not None and self.coordinator.is_live_run(run_id),
            artifact_reader=self.artifacts.read_artifact,
            on_transport_error=lambda run_id, message: self.coordinator and self.coordinator.record_transport_error(run_id, message),
            origin=self.config.run_origin,
            port=self.config.run_port,
        )
        coordinator = RunCoordinator(
            self.registry,
            self.artifacts,
            publisher=run_stage.publish,
            run_finished=run_stage.close_run,
        )
        self.run_stage = run_stage
        self.coordinator = coordinator
        self.run_thread = RunStageThread(run_stage)
        self.run_thread.start()

        module = _load_studio_server()
        self.api = module.create_server(
            "127.0.0.1",
            self.config.api_port,
            allowed_origin=self.config.link_origin,
            catalog=catalog,
            coordinator=coordinator,
        )
        self.api_thread = Thread(target=self.api.serve_forever, name="studio-api")
        self.api_thread.start()
        wait_url(f"{self.config.api_origin}/api/context", "studio API")

        environment = os.environ.copy()
        environment.update(
            LINK_APP_DIR=str(REPO_ROOT / "ruleset-studio/src"),
            LINK_PORT=str(self.config.link_port),
            LINK_TITLE="Ruleset Studio",
            LINK_NO_OPEN="1",
        )
        self.link = subprocess.Popen([node, str(link_server)], cwd=REPO_ROOT, env=environment)
        wait_url(self.config.link_origin, "ux.surface link server", process=self.link)
        return node, bridge

    def serve(self) -> int:
        while not self.stopping.wait(0.1):
            if self.link is not None and self.link.poll() is not None:
                self.registry.stop_accepting()
                drained = self._wait_for_active_run()
                return 0 if self.shutdown(cancel_active=not drained) else 1
        return 0 if self.shutdown(cancel_active=True) else 1

    def request_stop(self, _number: int | None = None, _frame: object = None) -> None:
        self.stopping.set()

    def shutdown(self, *, cancel_active: bool) -> bool:
        if self._shutdown_result is not None:
            return self._shutdown_result
        stopped = True
        if self.coordinator is not None:
            if cancel_active:
                stopped = self.coordinator.shutdown(self.config.shutdown_timeout)
                if not stopped:
                    print(
                        "Studio run worker did not stop before the shutdown timeout; "
                        "abandoning the daemon worker.",
                        file=sys.stderr,
                    )
            else:
                self.registry.stop_accepting()
                self.registry.reap_terminal()
        stop(self.link)
        if self.api is not None and self.api_thread is not None and self.api_thread.is_alive():
            self.api.shutdown()
        if self.api is not None:
            self.api.server_close()
        if self.api_thread is not None:
            self.api_thread.join(5)
        if self.run_thread is not None:
            stopped = self.run_thread.stop() and stopped
        self._shutdown_result = stopped
        return self._shutdown_result

    def _wait_for_active_run(self) -> bool:
        while True:
            snapshot = self.registry.active_worker_snapshot()
            if snapshot is None:
                return True
            if snapshot.worker is not None and not snapshot.worker.is_alive():
                self.registry.reap_terminal()
                return True
            if self.stopping.wait(0.1):
                return False


def parse_args(argv: Sequence[str] | None = None) -> LauncherConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metta-root", type=Path, default=DEFAULT_METTA_ROOT)
    parser.add_argument("--link-server")
    parser.add_argument("--link-port", type=int, default=4322)
    parser.add_argument("--api-port", type=int, default=4323)
    parser.add_argument("--run-port", type=int, default=4324)
    parser.add_argument("--runs-dir", type=Path, default=REPO_ROOT / "build" / "studio" / "runs")
    parser.add_argument("--shutdown-timeout", type=float, default=DEFAULT_SHUTDOWN_TIMEOUT)
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    arguments = parser.parse_args(argv)
    if arguments.shutdown_timeout < 0:
        parser.error("--shutdown-timeout must be non-negative")
    try:
        server = resolve_link_server(arguments.link_server, arguments.metta_root.resolve())
    except FileNotFoundError as error:
        parser.error(str(error))
    chosen: set[int] = set()
    ports = []
    for preferred in (arguments.link_port, arguments.api_port, arguments.run_port):
        port = available_port(preferred, excluded=chosen)
        chosen.add(port)
        ports.append(port)
    return LauncherConfig(
        arguments.metta_root.resolve(),
        server,
        ports[0],
        ports[1],
        ports[2],
        arguments.runs_dir.resolve(),
        arguments.shutdown_timeout,
        not arguments.no_open,
    )


def run(config: LauncherConfig) -> int:
    launcher = StudioLauncher(config)
    previous = {number: signal.signal(number, launcher.request_stop) for number in (signal.SIGINT, signal.SIGTERM)}
    exit_code = 1
    try:
        node, bridge = launcher.start()
        print(f"Ruleset Studio: {config.page_url}", flush=True)
        print(f"Studio API: {config.api_origin}", flush=True)
        print(f"Run stage: {config.run_origin}", flush=True)
        print("Connect this coding session with:", flush=True)
        print(f"  {bridge_command(node, bridge, config.link_port)}", flush=True)
        print("After each reply, run the same watch command again to re-arm the bridge.", flush=True)
        if config.open_browser:
            webbrowser.open(config.page_url)
        exit_code = launcher.serve()
    except Exception as error:
        print(f"Ruleset Studio could not start: {error}", file=sys.stderr)
    finally:
        if not launcher.shutdown(cancel_active=True):
            exit_code = 1
        for number, handler in previous.items():
            signal.signal(number, handler)
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
