"""Async HTTP/WebSocket edge for the synchronous Sugarscape episode core."""

from __future__ import annotations

import os
import sys

if __name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0":
    _environment = os.environ.copy()
    _environment["PYTHONHASHSEED"] = "0"
    os.execve(
        sys.executable,
        [sys.executable, "-m", "coworld.server", *sys.argv[1:]],
        _environment,
    )

import argparse
import asyncio
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import secrets
import tempfile
from time import perf_counter_ns
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import urlopen

from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from .config import resolve_episode_config, ruleset_limits
from .episode import run_episode
from .ruleset import validate_ruleset
from .targets import load_target_catalog, resolve_seat_targets


PROTOCOL = "sugarscape-v3/1"
MAX_PLAYER_MESSAGE_BYTES = 64 * 1024
SPECTATOR_QUEUE_SIZE = 64
_LOGGER = logging.getLogger("coworld.server")
_PRIVATE_CONFIG_KEYS = {
    "agentLogfile",
    "debugMode",
    "headlessMode",
    "interfaceHeight",
    "interfaceWidth",
    "keepAliveAtEnd",
    "logfile",
    "logfileFormat",
    "profileMode",
    "scenario_index",
    "scenario_pool",
    "screenshots",
    "seed",
    "targets",
    "tokens",
}


@dataclass(slots=True)
class SeatTransitTiming:
    connect_ns: int | None = None
    observation_send_ns: int = 0
    action_transit_ns: int = 0
    validation_ns: int = 0
    ack_send_ns: int = 0

    def as_dict(self) -> dict[str, int | None]:
        return {
            "connect_ns": self.connect_ns,
            "observation_send_ns": self.observation_send_ns,
            "action_transit_ns": self.action_transit_ns,
            "validation_ns": self.validation_ns,
            "ack_send_ns": self.ack_send_ns,
        }


@dataclass(slots=True)
class SugarscapeServer:
    """Own one submission window and one episode."""

    config: dict[str, object]
    results_uri: str
    replay_uri: str
    host: str = "0.0.0.0"
    port: int = 8080
    config_read_ns: int = 0
    bound_port: int | None = None
    _window_started_ns: int = field(init=False, default=0)
    _submission_window_ns: int = field(init=False, default=0)
    _deadline: float = field(init=False, default=0.0)
    _window_closed: bool = field(init=False, default=False)
    _submitted: list[bool] = field(init=False)
    _rulesets: list[object] = field(init=False)
    _claimed_slots: set[int] = field(init=False, default_factory=set)
    _reservations: dict[int, int] = field(init=False, default_factory=dict)
    _active_players: dict[int, ServerConnection] = field(init=False, default_factory=dict)
    _spectators: set[asyncio.Queue[str]] = field(init=False, default_factory=set)
    _all_submitted: asyncio.Event = field(init=False, default_factory=asyncio.Event)
    _result_ready: asyncio.Event = field(init=False, default_factory=asyncio.Event)
    _result_message: str = field(init=False, default="")
    _seat_timings: list[SeatTransitTiming] = field(init=False)
    _targets: tuple[Any, ...] = field(init=False)

    def __post_init__(self) -> None:
        seats = int(self.config["seats"])
        tokens = self.config.get("tokens")
        players = self.config.get("players")
        if not isinstance(tokens, list) or len(tokens) != seats:
            raise ValueError("config.tokens must contain one token per seat")
        if not all(isinstance(token, str) and token for token in tokens):
            raise ValueError("config.tokens entries must be non-empty strings")
        if not isinstance(players, list) or len(players) != seats:
            raise ValueError("config.players must contain one {name} object per seat")
        self._submitted = [False] * seats
        self._rulesets = [None] * seats
        self._seat_timings = [SeatTransitTiming() for _ in range(seats)]
        catalog = load_target_catalog()
        self._targets = resolve_seat_targets(
            self.config.get("targets"),
            seats=seats,
            measurement_window=int(self.config["measurement_window"]),
            catalog=catalog,
        )

    async def serve(self) -> None:
        """Serve the submission window, run the episode, publish artifacts, exit."""

        async with serve(
            self._handler,
            self.host,
            self.port,
            process_request=self._process_request,
            max_size=MAX_PLAYER_MESSAGE_BYTES,
        ) as websocket_server:
            self.bound_port = websocket_server.sockets[0].getsockname()[1]
            loop = asyncio.get_running_loop()
            self._window_started_ns = perf_counter_ns()
            timeout = float(self.config.get("player_connect_timeout_seconds", 180))
            self._deadline = loop.time() + timeout
            _log("server_ready", host=self.host, port=self.bound_port, timeout_seconds=timeout)
            await self._submission_window()
            await self._execute_episode(loop)
            await self._wait_for_terminal_delivery()

    def _process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        parsed = urlsplit(request.path)
        if parsed.path == "/healthz":
            return _http_response(200, "ok\n", "text/plain; charset=utf-8")
        if parsed.path == "/client/player":
            return _http_response(200, _player_page(), "text/html; charset=utf-8")
        if parsed.path == "/client/global":
            return _http_response(200, _global_page(), "text/html; charset=utf-8")
        if parsed.path == "/global":
            return None
        if parsed.path != "/player":
            return connection.respond(404, "not found\n")
        if self._window_closed:
            return connection.respond(410, "submission window closed\n")

        query = parse_qs(parsed.query, keep_blank_values=True)
        slot_values = query.get("slot", [])
        token_values = query.get("token", [])
        if len(slot_values) != 1 or len(token_values) != 1:
            return connection.respond(400, "slot and token are required\n")
        try:
            slot = int(slot_values[0])
        except ValueError:
            return connection.respond(400, "slot must be an integer\n")
        if not 0 <= slot < len(self._submitted):
            return connection.respond(403, "invalid slot or token\n")
        token = self.config["tokens"][slot]
        if not secrets.compare_digest(token_values[0], token):
            return connection.respond(403, "invalid slot or token\n")
        if slot in self._claimed_slots:
            return connection.respond(409, "slot already connected or submitted\n")
        self._claimed_slots.add(slot)
        self._reservations[id(connection)] = slot
        return None

    async def _handler(self, connection: ServerConnection) -> None:
        path = urlsplit(connection.request.path).path
        if path == "/global":
            await self._spectator_handler(connection)
            return
        if path != "/player":
            await connection.close(code=1008, reason="unsupported websocket path")
            return
        slot = self._reservations.pop(id(connection))
        self._active_players[slot] = connection
        timing = self._seat_timings[slot]
        timing.connect_ns = perf_counter_ns() - self._window_started_ns
        observation_sent_ns = perf_counter_ns()
        try:
            observation = self._observation(slot)
            started = perf_counter_ns()
            await connection.send(_json_message(observation))
            timing.observation_send_ns += perf_counter_ns() - started
            observation_sent_ns = perf_counter_ns()
            await self._action_loop(connection, slot, timing, observation_sent_ns)
            await self._result_ready.wait()
            await connection.send(self._result_message)
        except ConnectionClosed:
            _log("player_disconnected", seat=slot, close_code=connection.close_code)
        finally:
            self._active_players.pop(slot, None)
            if not self._submitted[slot]:
                self._claimed_slots.discard(slot)

    async def _action_loop(
        self,
        connection: ServerConnection,
        slot: int,
        timing: SeatTransitTiming,
        observation_sent_ns: int,
    ) -> None:
        loop = asyncio.get_running_loop()
        limits = ruleset_limits(self.config)
        while not self._window_closed and not self._submitted[slot]:
            remaining = self._deadline - loop.time()
            if remaining <= 0:
                return
            try:
                message = await asyncio.wait_for(connection.recv(), timeout=remaining)
            except TimeoutError:
                return
            if loop.time() > self._deadline:
                return
            timing.action_transit_ns += perf_counter_ns() - observation_sent_ns
            action, envelope_errors = _parse_action(message)
            started = perf_counter_ns()
            validation = validate_ruleset(action, limits=limits) if not envelope_errors else None
            timing.validation_ns += perf_counter_ns() - started
            errors = envelope_errors
            if validation is not None:
                errors = [
                    {"path": issue.path, "message": issue.message}
                    for issue in validation.errors
                ]
            ack_started = perf_counter_ns()
            if errors:
                await connection.send(_json_message({"type": "ack", "valid": False, "errors": errors}))
                timing.ack_send_ns += perf_counter_ns() - ack_started
                observation_sent_ns = perf_counter_ns()
                continue
            assert validation is not None
            self._rulesets[slot] = validation.normalized
            self._submitted[slot] = True
            await connection.send(_json_message({"type": "ack", "valid": True}))
            timing.ack_send_ns += perf_counter_ns() - ack_started
            if all(self._submitted):
                self._all_submitted.set()

    async def _spectator_handler(self, connection: ServerConnection) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=SPECTATOR_QUEUE_SIZE)
        self._spectators.add(queue)
        try:
            while True:
                message = await queue.get()
                await connection.send(message)
                if json.loads(message).get("type") == "result":
                    return
        except ConnectionClosed:
            return
        finally:
            self._spectators.discard(queue)

    async def _submission_window(self) -> None:
        remaining = max(0.0, self._deadline - asyncio.get_running_loop().time())
        try:
            await asyncio.wait_for(self._all_submitted.wait(), timeout=remaining)
        except TimeoutError:
            pass
        self._window_closed = True
        self._submission_window_ns = perf_counter_ns() - self._window_started_ns
        _log(
            "submission_window_closed",
            duration_ns=self._submission_window_ns,
            submitted=sum(self._submitted),
        )

    async def _execute_episode(self, loop: asyncio.AbstractEventLoop) -> None:
        def frame_sink(frame: dict[str, object]) -> None:
            loop.call_soon_threadsafe(self._fan_out, _json_message(frame))

        results, replay, timings = await asyncio.to_thread(
            run_episode,
            self.config,
            self._rulesets,
            submitted=self._submitted,
            frame_sink=frame_sink,
        )
        await asyncio.sleep(0)
        timings["server"] = {
            "config_read_ns": self.config_read_ns,
            "submission_window_ns": self._submission_window_ns,
            "seats": [timing.as_dict() for timing in self._seat_timings],
        }
        replay_write_ns = _timed_atomic_write(self.replay_uri, replay)
        timings["artifact_writes"] = {
            "replay_os_replace_ns": replay_write_ns,
            "results_provisional_payload_ns": 0,
        }
        provisional_started = perf_counter_ns()
        _encode_results(results)
        timings["artifact_writes"]["results_provisional_payload_ns"] = (
            perf_counter_ns() - provisional_started
        )
        final_payload = _encode_results(results)
        results_write_ns = _timed_atomic_write(self.results_uri, final_payload)
        _log(
            "artifact_writes_complete",
            replay_os_replace_ns=replay_write_ns,
            results_os_replace_ns=results_write_ns,
        )
        terminal = {
            "type": "result",
            "protocol": PROTOCOL,
            "scores": results["scores"],
            "details": results["details"],
            "summary": {
                "score.match_mean": results["score.match_mean"],
                "score.match_min": results["score.match_min"],
                "result.population_final": results["result.population_final"],
            },
        }
        self._result_message = _json_message(terminal)
        self._fan_out(self._result_message)
        self._result_ready.set()

    async def _wait_for_terminal_delivery(self) -> None:
        deadline = asyncio.get_running_loop().time() + 2.0
        while (self._active_players or self._spectators) and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)

    def _fan_out(self, message: str) -> None:
        for queue in tuple(self._spectators):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(message)

    def _observation(self, slot: int) -> dict[str, object]:
        limits = ruleset_limits(self.config)
        return {
            "type": "observation",
            "protocol": PROTOCOL,
            "seat": slot,
            "config": public_config(self.config),
            "target": self._targets[slot].as_dict(),
            "ruleset_schema": {
                "version": 1,
                "limits": {
                    "max_nodes": limits.max_nodes,
                    "max_depth": limits.max_depth,
                    "max_bytes": limits.max_bytes,
                },
            },
        }


def public_config(config: Mapping[str, object]) -> dict[str, object]:
    """Return effective mechanics without tokens, seed, or hidden assignments."""

    return {
        key: _strip_tokens(value)
        for key, value in config.items()
        if key not in _PRIVATE_CONFIG_KEYS and not key.startswith("__")
    }


def read_json_uri(uri: str) -> tuple[dict[str, object], int]:
    """Read one JSON object from file:// or HTTP(S), returning elapsed ns."""

    started = perf_counter_ns()
    parsed = urlsplit(uri)
    if parsed.scheme in {"http", "https"}:
        with urlopen(uri, timeout=30) as response:  # noqa: S310 - platform-provided URI.
            data = response.read()
    else:
        path = _file_uri_path(uri)
        data = path.read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("game config must be a JSON object")
    return value, perf_counter_ns() - started


def atomic_write_uri(uri: str, data: bytes) -> None:
    """Atomically replace a file:// artifact; HTTP uploads are a documented TODO."""

    parsed = urlsplit(uri)
    if parsed.scheme in {"http", "https"}:
        raise NotImplementedError("TODO: HTTP(S) artifact uploads aren't implemented")
    path = _file_uri_path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as file:
            temporary_path = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def ensure_python_hash_seed() -> None:
    """Re-exec the server before imports can observe a non-zero hash seed."""

    if os.environ.get("PYTHONHASHSEED") == "0":
        return
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    os.execve(
        sys.executable,
        [sys.executable, "-m", "coworld.server", *sys.argv[1:]],
        environment,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sugarscape v3 coworld server")
    parser.add_argument("--host", default=os.environ.get("COGAME_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("COGAME_PORT", "8080")))
    parser.add_argument("--config-uri", default=os.environ.get("COGAME_CONFIG_URI"))
    parser.add_argument("--results-uri", default=os.environ.get("COGAME_RESULTS_URI"))
    parser.add_argument("--replay-uri", default=os.environ.get("COGAME_SAVE_REPLAY_URI"))
    args = parser.parse_args(argv)
    if not args.config_uri or not args.results_uri or not args.replay_uri:
        parser.error("config, results, and replay URIs are required")
    raw_config, config_read_ns = read_json_uri(args.config_uri)
    resolved = resolve_episode_config(raw_config)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    server = SugarscapeServer(
        resolved,
        args.results_uri,
        args.replay_uri,
        host=args.host,
        port=args.port,
        config_read_ns=config_read_ns,
    )
    asyncio.run(server.serve())
    return 0


def _parse_action(message: str | bytes) -> tuple[object, list[dict[str, str]]]:
    try:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        value = json.loads(message)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, [{"path": "$", "message": f"invalid action JSON: {error}"}]
    if not isinstance(value, dict):
        return None, [{"path": "$", "message": "action must be an object"}]
    if value.get("type") != "action":
        return None, [{"path": "$.type", "message": 'expected "action"'}]
    if "ruleset" not in value:
        return None, [{"path": "$.ruleset", "message": "field is required"}]
    return value["ruleset"], []


def _http_response(status: int, body: str, content_type: str) -> Response:
    encoded = body.encode("utf-8")
    headers = Headers(
        {
            "Content-Type": content_type,
            "Content-Length": str(len(encoded)),
            "Connection": "close",
        }
    )
    return Response(status, "OK" if status == 200 else "Error", headers, encoded)


def _player_page() -> str:
    return """<!doctype html><meta charset=utf-8><title>Sugarscape player</title>
<pre id=log>Connecting…</pre><script>
const q=new URLSearchParams(location.search);const slot=q.get('slot');const token=q.get('token');
const scheme=location.protocol==='https:'?'wss':'ws';
const playerUrl=`${scheme}://${location.host}/player?slot=${encodeURIComponent(slot)}`+
  `&token=${encodeURIComponent(token)}`;
const ws=new WebSocket(playerUrl);
ws.onmessage=e=>document.querySelector('#log').textContent=e.data;
</script>"""


def _global_page() -> str:
    return """<!doctype html><meta charset=utf-8><title>Sugarscape spectator</title>
<pre id=log>Connecting…</pre><script>
const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/global`);
ws.onmessage=e=>document.querySelector('#log').textContent=e.data;
</script>"""


def _file_uri_path(uri: str) -> Path:
    parsed = urlsplit(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError(f"unsupported URI scheme: {parsed.scheme}")
    if parsed.scheme == "file" and parsed.netloc not in {"", "localhost"}:
        raise ValueError("file URI host must be empty or localhost")
    return Path(unquote(parsed.path if parsed.scheme else uri))


def _strip_tokens(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _strip_tokens(item) for key, item in value.items() if key != "tokens"}
    if isinstance(value, list):
        return [_strip_tokens(item) for item in value]
    return value


def _timed_atomic_write(uri: str, data: bytes) -> int:
    started = perf_counter_ns()
    atomic_write_uri(uri, data)
    return perf_counter_ns() - started


def _encode_results(results: Mapping[str, object]) -> bytes:
    return json.dumps(
        results,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _json_message(value: Mapping[str, object]) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _log(event: str, **fields: object) -> None:
    _LOGGER.info(_json_message({"event": event, **fields}))


if __name__ == "__main__":
    ensure_python_hash_seed()
    raise SystemExit(main())
