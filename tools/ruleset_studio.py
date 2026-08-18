#!/usr/bin/env python3
"""Launch Ruleset Studio and its ux.surface bridge server."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import shlex
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlencode
import urllib.request
import webbrowser


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METTA_ROOT = Path.home() / "coding" / "metta"
LINK_APP = Path("agent-plugins/ux/skills/ux.surface/app")


def available_port(preferred: int) -> int:
    """Return the preferred loopback port when free, otherwise an ephemeral one."""
    with socket.socket() as candidate:
        try:
            candidate.bind(("127.0.0.1", preferred))
        except OSError:
            candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def discover(metta_root: Path) -> tuple[str, Path, Path]:
    node = shutil.which("node")
    link_server = metta_root / LINK_APP / "link-server.mjs"
    link_bridge = metta_root / LINK_APP / "link-bridge.mjs"
    missing = [str(path) for path in (REPO_ROOT / "ruleset-studio/server.py", REPO_ROOT / "ruleset-studio/src", link_server, link_bridge) if not path.exists()]
    if node is None:
        missing.append("node executable on PATH")
    if missing:
        raise RuntimeError("Ruleset Studio prerequisites are missing:\n  " + "\n  ".join(missing))
    return node, link_server, link_bridge


def wait_ready(process: subprocess.Popen[bytes], url: str, label: str, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not ready"
    while time.monotonic() < deadline:
        status = process.poll()
        if status is not None:
            raise RuntimeError(f"{label} exited during startup with status {status}")
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


def run(*, metta_root: Path, link_port: int, api_port: int, open_browser: bool) -> int:
    node, link_server, link_bridge = discover(metta_root.resolve())
    link_port = available_port(link_port)
    api_port = available_port(api_port)
    if link_port == api_port:
        api_port = available_port(0)
    origin = f"http://localhost:{link_port}"
    api_origin = f"http://127.0.0.1:{api_port}"
    url = f"{origin}/?{urlencode({'api': api_origin})}"

    environment = os.environ.copy()
    environment.update(
        LINK_APP_DIR=str(REPO_ROOT / "ruleset-studio/src"),
        LINK_PORT=str(link_port),
        LINK_TITLE="Ruleset Studio",
        LINK_NO_OPEN="1",
    )
    api_environment = os.environ.copy()
    existing_pythonpath = api_environment.get("PYTHONPATH")
    api_environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(REPO_ROOT / "src"), existing_pythonpath) if part
    )
    api: subprocess.Popen[bytes] | None = None
    link: subprocess.Popen[bytes] | None = None
    stopping = False

    def request_stop(_number: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    previous = {number: signal.signal(number, request_stop) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        api = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "ruleset-studio/server.py"), "--port", str(api_port), "--origin", origin],
            cwd=REPO_ROOT,
            env=api_environment,
        )
        link = subprocess.Popen([node, str(link_server)], cwd=REPO_ROOT, env=environment)
        wait_ready(api, f"{api_origin}/api/context", "studio API")
        wait_ready(link, origin, "ux.surface link server")

        print(f"Ruleset Studio: {url}", flush=True)
        print("Connect this coding session with:", flush=True)
        print(f"  {bridge_command(node, link_bridge, link_port)}", flush=True)
        print("After each reply, run the same watch command again to re-arm the bridge.", flush=True)
        if open_browser:
            webbrowser.open(url)

        while not stopping:
            api_status = api.poll()
            link_status = link.poll()
            if link_status is not None:
                if link_status == 0:
                    return 0
                print(f"ux.surface link server exited unexpectedly with status {link_status}", file=sys.stderr)
                return 1
            if api_status is not None:
                print(f"Ruleset Studio API exited unexpectedly with status {api_status}", file=sys.stderr)
                return 1
            time.sleep(0.1)
        return 0
    except (OSError, RuntimeError) as error:
        print(f"Ruleset Studio could not start: {error}", file=sys.stderr)
        return 1
    finally:
        stop(link)
        stop(api)
        for number, handler in previous.items():
            signal.signal(number, handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metta-root", type=Path, default=DEFAULT_METTA_ROOT)
    parser.add_argument("--link-port", type=int, default=4322)
    parser.add_argument("--api-port", type=int, default=4323)
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    arguments = parser.parse_args()
    raise SystemExit(
        run(
            metta_root=arguments.metta_root,
            link_port=arguments.link_port,
            api_port=arguments.api_port,
            open_browser=not arguments.no_open,
        )
    )


if __name__ == "__main__":
    main()
