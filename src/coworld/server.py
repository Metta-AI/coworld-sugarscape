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
from collections import deque
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import re
import secrets
import tempfile
from time import perf_counter_ns, sleep
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import Request as UploadRequest, urlopen

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
# Give a newly connected spectator time to complete protocol probes before live
# frames can fill a client's receive queue. The hosted certifier deliberately
# sends Ping before calling recv(); without this pause, a short episode can put
# more than websockets' default 16 messages ahead of the automatic Pong.
SPECTATOR_STREAM_START_DELAY_SECONDS = 3.0
# How long the server keeps listening after the episode's artifacts are written.
# The hosted certifier's viewer probe connects to /global and pings it, and on a
# small config the episode is over in ~2s — so a server that closed as soon as
# its already-connected readers drained was simply not there when the probe
# arrived. Bounded: a game container that never exits is a hung job.
SPECTATOR_GRACE_SECONDS = 30.0
STUDIO_CATCH_UP_BYTES = 24 * 1024 * 1024
STUDIO_MAX_FRAME_BYTES = 8 * 1024 * 1024
STUDIO_SPECTATOR_QUEUE_BYTES = 24 * 1024 * 1024
STUDIO_FINAL_LINGER_SECONDS = 2.0
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


@dataclass(frozen=True, slots=True)
class LiveFrame:
    """One validated serialized v1 frame plus queue-policy metadata."""

    payload: bytes
    timestep: int
    final: bool

    @property
    def guaranteed(self) -> bool:
        return self.timestep == 0 or self.final

    @classmethod
    def parse(cls, payload: bytes) -> LiveFrame:
        try:
            frame = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("live payload must be UTF-8 JSON") from error
        if not isinstance(frame, dict) or frame.get("format") != "sugarscape.frame.v1":
            raise ValueError("live payload must be a sugarscape.frame.v1 object")
        timestep = frame.get("timestep")
        final = frame.get("final")
        if isinstance(timestep, bool) or not isinstance(timestep, int) or timestep < 0:
            raise ValueError("live frame timestep must be a non-negative integer")
        if not isinstance(final, bool):
            raise ValueError("live frame final must be a boolean")
        return cls(payload, timestep, final)


class CatchUpBuffer:
    """Retain serialized frames under exact byte and preservation policies."""

    def __init__(
        self,
        *,
        max_bytes: int = STUDIO_CATCH_UP_BYTES,
        max_frame_bytes: int = STUDIO_MAX_FRAME_BYTES,
    ) -> None:
        if max_bytes <= 0 or max_frame_bytes <= 0:
            raise ValueError("live buffer byte limits must be positive")
        self.max_bytes = max_bytes
        self.max_frame_bytes = max_frame_bytes
        self.frames: deque[LiveFrame] = deque()
        self.byte_count = 0
        self.disabled = False

    def append(self, frame: LiveFrame) -> tuple[bool, str | None]:
        if self.disabled:
            return False, None
        size = len(frame.payload)
        if size > self.max_frame_bytes:
            if frame.guaranteed:
                return False, self._disable("a guaranteed live frame exceeds the size limit")
            return False, None

        self.frames.append(frame)
        self.byte_count += size
        accepted = True
        while self.byte_count > self.max_bytes:
            victim = next((item for item in self.frames if not item.guaranteed), None)
            if victim is None:
                return False, self._disable("guaranteed live frames exceed the buffer limit")
            self.frames.remove(victim)
            self.byte_count -= len(victim.payload)
            if victim is frame:
                accepted = False
        return accepted, None

    def snapshot(self) -> tuple[LiveFrame, ...]:
        return tuple(self.frames)

    def clear(self) -> None:
        self.frames.clear()
        self.byte_count = 0

    def _disable(self, message: str) -> str:
        self.clear()
        self.disabled = True
        return message


class SpectatorQueue:
    """Byte-bound one client while preserving bootstrap and terminal frames."""

    def __init__(self, *, max_bytes: int = STUDIO_SPECTATOR_QUEUE_BYTES) -> None:
        if max_bytes <= 0:
            raise ValueError("spectator queue byte limit must be positive")
        self.max_bytes = max_bytes
        self.frames: deque[LiveFrame] = deque()
        self.byte_count = 0
        self.closed = False
        self._available = asyncio.Event()

    def seed(self, frames: tuple[LiveFrame, ...]) -> None:
        size = sum(len(frame.payload) for frame in frames)
        if size > self.max_bytes:
            raise ValueError("catch-up snapshot exceeds spectator queue limit")
        self.frames.extend(frames)
        self.byte_count += size
        if frames:
            self._available.set()

    def put(self, frame: LiveFrame) -> None:
        if self.closed:
            return
        if not frame.guaranteed:
            if self.byte_count + len(frame.payload) > self.max_bytes:
                self._remove_intermediates()
                if self.byte_count + len(frame.payload) > self.max_bytes:
                    return
        else:
            while self.byte_count + len(frame.payload) > self.max_bytes:
                victim = next((item for item in self.frames if not item.guaranteed), None)
                if victim is None:
                    raise RuntimeError("guaranteed frames exceed spectator queue limit")
                self.frames.remove(victim)
                self.byte_count -= len(victim.payload)
        self.frames.append(frame)
        self.byte_count += len(frame.payload)
        self._available.set()

    async def get(self) -> LiveFrame | None:
        while not self.frames:
            if self.closed:
                return None
            self._available.clear()
            await self._available.wait()
        frame = self.frames.popleft()
        self.byte_count -= len(frame.payload)
        return frame

    def close(self) -> None:
        self.closed = True
        self._available.set()

    def _remove_intermediates(self) -> None:
        retained = deque(frame for frame in self.frames if frame.guaranteed)
        self.frames = retained
        self.byte_count = sum(len(frame.payload) for frame in retained)


@dataclass(slots=True)
class _LiveRunState:
    buffer: CatchUpBuffer
    spectators: set[SpectatorQueue] = field(default_factory=set)
    closed: bool = False


class LiveRunHub:
    """Own catch-up and subscriber ordering on one loop for one server lifetime."""

    def __init__(
        self,
        *,
        on_transport_error: Callable[[str, str], None],
        catch_up_bytes: int = STUDIO_CATCH_UP_BYTES,
        max_frame_bytes: int = STUDIO_MAX_FRAME_BYTES,
        spectator_queue_bytes: int = STUDIO_SPECTATOR_QUEUE_BYTES,
    ) -> None:
        if spectator_queue_bytes < catch_up_bytes:
            raise ValueError("spectator queues must hold one complete catch-up snapshot")
        if spectator_queue_bytes < 2 * max_frame_bytes:
            raise ValueError("spectator queues must hold tick 0 and the terminal frame")
        self.on_transport_error = on_transport_error
        self.catch_up_bytes = catch_up_bytes
        self.max_frame_bytes = max_frame_bytes
        self.spectator_queue_bytes = spectator_queue_bytes
        self._runs: dict[str, _LiveRunState] = {}
        self._closed_run_id: str | None = None
        self._active_run_id: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def publish(self, run_id: str, payload: bytes) -> None:
        self._assert_loop()
        try:
            frame = LiveFrame.parse(payload)
        except ValueError:
            self.disable(run_id, "live frame serialization is invalid")
            return
        self.publish_frame(run_id, frame)

    def publish_frame(self, run_id: str, frame: LiveFrame) -> None:
        self._assert_loop()
        if self._active_run_id is None:
            self._active_run_id = run_id
        elif self._active_run_id != run_id:
            self.close_all()
            self._runs.clear()
            self._active_run_id = run_id
        state = self._runs.setdefault(run_id, self._new_state())
        if state.closed or state.buffer.disabled:
            return
        accepted, error = state.buffer.append(frame)
        if error is not None:
            self._disable(run_id, state, error)
            return
        if accepted:
            for spectator in tuple(state.spectators):
                try:
                    spectator.put(frame)
                except RuntimeError:
                    spectator.close()
                    state.spectators.discard(spectator)
                    _LOGGER.warning("studio spectator queue rejected a guaranteed frame")

    def subscribe(self, run_id: str) -> SpectatorQueue | None:
        self._assert_loop()
        active = (
            self._runs.get(self._active_run_id)
            if self._active_run_id is not None
            else None
        )
        if self._active_run_id is not None and (
            self._active_run_id == self._closed_run_id
            or (active is not None and active.closed)
        ):
            self._active_run_id = None
        if run_id == self._closed_run_id:
            return None
        if self._active_run_id not in {None, run_id}:
            return None
        state = self._runs.setdefault(run_id, self._new_state())
        if state.closed or state.buffer.disabled:
            return None
        if self._active_run_id is None:
            self._active_run_id = run_id
            self._closed_run_id = None
        queue = SpectatorQueue(max_bytes=self.spectator_queue_bytes)
        # No await between snapshot and subscription: a loop callback cannot
        # publish into the gap and duplicate or skip a frame.
        queue.seed(state.buffer.snapshot())
        state.spectators.add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: SpectatorQueue) -> None:
        self._assert_loop()
        state = self._runs.get(run_id)
        if state is not None:
            state.spectators.discard(queue)

    def close_run(self, run_id: str) -> None:
        self._assert_loop()
        state = self._runs.pop(run_id, None)
        if state is not None:
            state.closed = True
            state.buffer.clear()
            for spectator in tuple(state.spectators):
                spectator.close()
            state.spectators.clear()
        self._closed_run_id = run_id
        if self._active_run_id == run_id:
            self._active_run_id = None

    def close_all(self) -> None:
        self._assert_loop()
        for run_id in tuple(self._runs):
            self.close_run(run_id)

    def disable(self, run_id: str, message: str) -> None:
        self._assert_loop()
        if self._active_run_id is None:
            self._active_run_id = run_id
        elif self._active_run_id != run_id:
            self.close_all()
            self._runs.clear()
            self._active_run_id = run_id
        self._disable(run_id, self._runs.setdefault(run_id, self._new_state()), message)

    def _disable(self, run_id: str, state: _LiveRunState, message: str) -> None:
        if state.closed:
            return
        state.closed = True
        for spectator in tuple(state.spectators):
            spectator.close()
        try:
            self.on_transport_error(run_id, message)
        except Exception:
            _LOGGER.exception("studio transport error callback failed")

    def _new_state(self) -> _LiveRunState:
        return _LiveRunState(
            CatchUpBuffer(
                max_bytes=self.catch_up_bytes,
                max_frame_bytes=self.max_frame_bytes,
            )
        )

    def _assert_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("LiveRunHub may only be used by its owning asyncio loop")


class StudioRunStageServer:
    """Single-serve listener for Studio viewers, artifacts, and live sockets."""

    def __init__(
        self,
        *,
        run_exists: Callable[[str], bool],
        live_run_exists: Callable[[str], bool],
        artifact_reader: Callable[[str, str], bytes],
        on_transport_error: Callable[[str, str], None],
        origin: str,
        host: str = "127.0.0.1",
        port: int = 8766,
        viewer_path: Path | str | None = None,
        linger_seconds: float = STUDIO_FINAL_LINGER_SECONDS,
        catch_up_bytes: int = STUDIO_CATCH_UP_BYTES,
        max_frame_bytes: int = STUDIO_MAX_FRAME_BYTES,
        spectator_queue_bytes: int = STUDIO_SPECTATOR_QUEUE_BYTES,
    ) -> None:
        if linger_seconds < STUDIO_FINAL_LINGER_SECONDS:
            raise ValueError("studio final-frame linger must be at least two seconds")
        self.run_exists = run_exists
        self.live_run_exists = live_run_exists
        self.artifact_reader = artifact_reader
        self.origin = origin
        self.host = host
        self.port = port
        self.viewer = Path(
            viewer_path
            or Path(__file__).resolve().parents[2] / "replay-viewer" / "index.html"
        ).read_bytes()
        self.linger_seconds = linger_seconds
        self.bound_port: int | None = None
        self.hub = LiveRunHub(
            on_transport_error=on_transport_error,
            catch_up_bytes=catch_up_bytes,
            max_frame_bytes=max_frame_bytes,
            spectator_queue_bytes=spectator_queue_bytes,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._on_transport_error = on_transport_error
        self._served = False

    async def serve(self) -> None:
        if self._served:
            raise RuntimeError("studio run-stage server instances are single-serve")
        self._served = True
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        try:
            async with serve(
                self._handler,
                self.host,
                self.port,
                process_request=self._process_request,
                origins=[self.origin],
                max_size=MAX_PLAYER_MESSAGE_BYTES,
            ) as websocket_server:
                self.bound_port = websocket_server.sockets[0].getsockname()[1]
                await self._stop.wait()
                self.hub.close_all()
        finally:
            self.bound_port = None
            self._stop = None
            self._loop = None

    def publish(self, run_id: str, payload: bytes) -> None:
        """Schedule one serialized frame from a worker thread without blocking."""

        loop = self._loop
        if loop is None or loop.is_closed():
            self._report_transport_error(run_id, "live listener is unavailable")
            return
        try:
            frame = LiveFrame.parse(payload)
        except ValueError:
            callback = self.hub.disable
            arguments = (run_id, "live frame serialization is invalid")
        else:
            callback = self.hub.publish_frame
            arguments = (run_id, frame)
        try:
            loop.call_soon_threadsafe(callback, *arguments)
        except RuntimeError:
            self._report_transport_error(run_id, "live listener is unavailable")

    def close_run(self, run_id: str) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self.hub.close_run, run_id)

    def stop(self) -> None:
        loop = self._loop
        stop = self._stop
        if loop is not None and stop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop.set)

    async def _process_request(
        self,
        connection: ServerConnection,
        request: Request,
    ) -> Response | None:
        parsed = urlsplit(request.path)
        route = self._run_route(parsed.path)
        if request.method != "GET" or route is None:
            return _http_bytes_response(404, b"not found\n", "text/plain; charset=utf-8")
        run_id, endpoint = route
        if not await asyncio.to_thread(self.run_exists, run_id):
            return _http_bytes_response(404, b"run not found\n", "text/plain; charset=utf-8")
        if endpoint == "client/replay":
            return _http_bytes_response(200, self.viewer, "text/html; charset=utf-8")
        if endpoint == "replay.bin":
            try:
                replay = await asyncio.to_thread(
                    self.artifact_reader,
                    run_id,
                    "replay.bin",
                )
            except (FileNotFoundError, ValueError):
                return _http_bytes_response(
                    404,
                    b"run artifact not found\n",
                    "text/plain; charset=utf-8",
                )
            except Exception:
                _LOGGER.exception("studio replay artifact read failed")
                return _http_bytes_response(
                    500,
                    b"could not read run artifact\n",
                    "text/plain; charset=utf-8",
                )
            return _http_bytes_response(200, replay, "application/octet-stream")
        return None

    async def _handler(self, connection: ServerConnection) -> None:
        route = self._run_route(urlsplit(connection.request.path).path)
        if route is None or route[1] != "replay":
            await connection.close(code=1008, reason="unsupported websocket path")
            return
        run_id = route[0]
        if not await asyncio.to_thread(self.live_run_exists, run_id):
            await connection.close(code=1008, reason="live stream unavailable")
            return
        queue = self.hub.subscribe(run_id)
        if queue is None:
            await connection.close(code=1008, reason="live stream unavailable")
            return
        try:
            while True:
                frame = await self._next_frame(connection, queue)
                if frame is None:
                    return
                await connection.send(frame.payload.decode("utf-8"))
                if frame.final:
                    await self._linger(connection)
                    return
        except ConnectionClosed:
            return
        finally:
            self.hub.unsubscribe(run_id, queue)

    @staticmethod
    async def _next_frame(
        connection: ServerConnection,
        queue: SpectatorQueue,
    ) -> LiveFrame | None:
        frame_ready = asyncio.create_task(queue.get())
        connection_closed = asyncio.create_task(connection.wait_closed())
        try:
            done, _pending = await asyncio.wait(
                {frame_ready, connection_closed},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if connection_closed in done:
                return None
            return frame_ready.result()
        finally:
            for task in (frame_ready, connection_closed):
                if not task.done():
                    task.cancel()
            await asyncio.gather(frame_ready, connection_closed, return_exceptions=True)

    async def _linger(self, connection: ServerConnection) -> None:
        try:
            await asyncio.wait_for(
                connection.wait_closed(),
                timeout=self.linger_seconds,
            )
        except (ConnectionClosed, TimeoutError):
            return

    @staticmethod
    def _run_route(path: str) -> tuple[str, str] | None:
        decoded = unquote(path)
        match = re.fullmatch(
            r"/runs/([0-9a-f]{32})/(client/replay|replay\.bin|replay)",
            decoded,
        )
        if match is None:
            return None
        return match.group(1), match.group(2)

    def _report_transport_error(self, run_id: str, message: str) -> None:
        try:
            self._on_transport_error(run_id, message)
        except Exception:
            _LOGGER.exception("studio transport error callback failed")


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
            # The hosted runner's viewer probe requires the first /global
            # message within 10 seconds of connecting, while the simulation
            # only emits frames after every player has submitted — tens of
            # seconds into a hosted episode. Greet every spectator immediately
            # so the stream is never silent (v1 satisfied the same probe via
            # its catch-up frame buffer).
            await connection.send(
                _json_message(
                    {
                        "type": "status",
                        "protocol": PROTOCOL,
                        "phase": "run" if self._window_closed else "submission_window",
                        "seats": len(self._submitted),
                        "submitted": sum(self._submitted),
                    }
                )
            )
            # Arrived after the episode finished: hand over the result rather
            # than holding a connection open on a world that is already decided.
            # Truthiness, NOT `is not None`: the field defaults to "" rather than
            # None, so an identity check fires during the submission window and
            # hands every spectator an empty message before the world has run.
            if self._result_message:
                await connection.send(self._result_message)
                await self._linger(connection)
                return
            stream_started = False
            while True:
                message = await queue.get()
                message_type = json.loads(message).get("type")
                if message_type == "frame" and not stream_started:
                    delay = float(
                        self.config.get(
                            "spectator_stream_start_delay_seconds",
                            SPECTATOR_STREAM_START_DELAY_SECONDS,
                        )
                    )
                    await asyncio.sleep(max(0.0, delay))
                    stream_started = True
                await connection.send(message)
                if message_type == "result":
                    await self._linger(connection)
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
        replay_write_ns, results_write_ns = await asyncio.to_thread(
            _publish_episode_artifacts,
            self.replay_uri,
            self.results_uri,
            replay,
            results,
            timings,
        )
        _log(
            "artifact_writes_complete",
            replay_os_replace_ns=replay_write_ns,
            results_os_replace_ns=results_write_ns,
        )
        terminal = {
            "type": "result",
            "protocol": PROTOCOL,
            "score_method": results["score_method"],
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

    async def _linger(self, connection: ServerConnection) -> None:
        """Hold a finished spectator connection open until the peer hangs up.

        Sending the result and returning closes the socket from this side, and a
        reader that wanted to ping it then gets `no close frame received or
        sent`. That is the second half of the certification failure: even once
        the server outlived the episode, the probe's connection was torn down
        before its ping could be answered. Waiting on the peer keeps the
        connection alive, and the websockets library answers Pings from its own
        reader task while we sit here.
        """

        # A connected certifier may be waiting for Kubernetes player pods to
        # start before it sends Ping, so it must outlive the late-arrival grace.
        # Keep the wait bounded by the existing player startup timeout so an
        # abandoned spectator still cannot hang the game container forever.
        linger = self._spectator_linger_seconds()
        if linger <= 0:
            return
        try:
            await asyncio.wait_for(connection.wait_closed(), timeout=linger)
        except (ConnectionClosed, TimeoutError):
            return

    async def _wait_for_terminal_delivery(self) -> None:
        """Stay reachable after the episode, for readers that have not arrived yet.

        This used to wait up to two seconds and ONLY while someone was already
        connected, then return — closing the websocket server. Anything that
        connected after that found nothing listening, which is why hosted
        certification failed every version with "Game websocket did not answer a
        WebSocket Ping with Pong: ws://127.0.0.1:8080/global": the viewer probe
        was arriving at a socket that had already shut down. On the shipped
        20x20 config the whole episode is over in about two seconds, so the
        window it had to hit was essentially zero.

        So the server holds open for a bounded grace whether or not anyone is
        connected, and a spectator arriving inside that window is handed the
        finished result immediately (see _spectator_handler). An established
        spectator may remain through the longer player startup timeout because
        hosted certification waits for those pods before sending Ping. Both
        deadlines are bounded so an abandoned reader cannot hang the container.
        """

        loop = asyncio.get_running_loop()
        grace = float(
            self.config.get("spectator_grace_seconds", SPECTATOR_GRACE_SECONDS)
        )
        grace_deadline = loop.time() + max(0.0, grace)
        linger = self._spectator_linger_seconds()
        linger_deadline = loop.time() + max(0.0, linger)
        _log("terminal_grace_open", seconds=grace, connected_seconds=linger)
        # Stay available for late readers through the grace period. A reader
        # already attached extends shutdown through the player startup timeout,
        # which covers the certifier's connect -> wait for players -> Ping order.
        while loop.time() < grace_deadline or (
            self._spectators and loop.time() < linger_deadline
        ):
            await asyncio.sleep(0.05)
        _log("terminal_grace_closed")

    def _spectator_linger_seconds(self) -> float:
        grace = float(
            self.config.get("spectator_grace_seconds", SPECTATOR_GRACE_SECONDS)
        )
        player_startup = float(
            self.config.get("player_connect_timeout_seconds", 180)
        )
        return max(grace, player_startup)

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


_UPLOAD_ATTEMPTS = 4
_UPLOAD_RETRY_DELAY_SECONDS = 2.0


def atomic_write_uri(
    uri: str,
    data: bytes,
    *,
    retry_delay_seconds: float = _UPLOAD_RETRY_DELAY_SECONDS,
) -> None:
    """Publish an artifact: atomic replace for file://, PUT for http(s)://.

    HTTP uploads retry transient failures (connection errors and 5xx) with a
    linear backoff; 4xx responses fail fast — the platform handed us a URI the
    server rejects, and retrying cannot fix a client error.
    """

    parsed = urlsplit(uri)
    if parsed.scheme in {"http", "https"}:
        _put_with_retries(uri, data, retry_delay_seconds=retry_delay_seconds)
        return
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


def _put_with_retries(uri: str, data: bytes, *, retry_delay_seconds: float) -> None:
    last_error: Exception | None = None
    for attempt in range(1, _UPLOAD_ATTEMPTS + 1):
        try:
            request = UploadRequest(
                uri,
                data=data,
                method="PUT",
                headers={"Content-Type": "application/octet-stream"},
            )
            with urlopen(request, timeout=60):  # noqa: S310 - platform-provided URI.
                return  # urlopen raises on any non-success status
        except HTTPError as error:
            if 400 <= error.code < 500:
                raise RuntimeError(
                    f"artifact upload to {uri} rejected with HTTP {error.code}"
                ) from error
            last_error = error
        except (URLError, OSError, TimeoutError) as error:
            last_error = error
        if attempt < _UPLOAD_ATTEMPTS:
            _log(
                "artifact_upload_retry",
                uri=uri,
                attempt=attempt,
                error=str(last_error),
            )
            sleep(retry_delay_seconds * attempt)
    raise RuntimeError(
        f"artifact upload to {uri} failed after {_UPLOAD_ATTEMPTS} attempts: {last_error}"
    )


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
    return _http_bytes_response(status, body.encode("utf-8"), content_type)


def _http_bytes_response(status: int, body: bytes, content_type: str) -> Response:
    headers = Headers(
        {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Connection": "close",
        }
    )
    return Response(status, "OK" if status == 200 else "Error", headers, body)


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


def _publish_episode_artifacts(
    replay_uri: str,
    results_uri: str,
    replay: bytes,
    results: Mapping[str, object],
    timings: dict[str, object],
) -> tuple[int, int]:
    """Publish artifacts without blocking the WebSocket event loop."""

    replay_write_ns = _timed_atomic_write(replay_uri, replay)
    artifact_timings = {
        "replay_os_replace_ns": replay_write_ns,
        "results_provisional_payload_ns": 0,
    }
    timings["artifact_writes"] = artifact_timings
    provisional_started = perf_counter_ns()
    _encode_results(results)
    artifact_timings["results_provisional_payload_ns"] = (
        perf_counter_ns() - provisional_started
    )
    results_write_ns = _timed_atomic_write(results_uri, _encode_results(results))
    return replay_write_ns, results_write_ns


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
