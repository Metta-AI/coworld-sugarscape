from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import socket
from time import monotonic
from typing import AsyncIterator
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from coworld.server import (
    CatchUpBuffer,
    LiveFrame,
    LiveRunHub,
    SpectatorQueue,
    StudioRunStageServer,
)
from coworld.studio import StudioVariantCatalog
from coworld.studio_runs import ArtifactStore, RunCoordinator, RunRegistry


ROOT = Path(__file__).resolve().parents[1]
V1_FIXTURE = ROOT / "tests" / "fixtures" / "replay-viewer-v1-golden.json"
RUN_ID = "1" * 32


def serialized_frame(timestep: int, *, final: bool = False, padding: int = 0) -> bytes:
    return json.dumps(
        {
            "format": "sugarscape.frame.v1",
            "timestep": timestep,
            "final": final,
            "padding": "x" * padding,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def fixture_frames() -> list[bytes]:
    document = json.loads(V1_FIXTURE.read_text(encoding="utf-8"))
    return [
        json.dumps(frame, separators=(",", ":"), sort_keys=True).encode("utf-8")
        for frame in document["frames"]
    ]


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@asynccontextmanager
async def running_server(
    tmp_path: Path,
    *,
    run_ids: set[str] | None = None,
    live_run_ids: set[str] | None = None,
    linger_seconds: float = 2.0,
    catch_up_bytes: int = 24 * 1024 * 1024,
    max_frame_bytes: int = 8 * 1024 * 1024,
    spectator_queue_bytes: int = 24 * 1024 * 1024,
) -> AsyncIterator[tuple[StudioRunStageServer, ArtifactStore, list[tuple[str, str]]]]:
    artifacts = ArtifactStore(tmp_path / "runs")
    known = run_ids if run_ids is not None else {RUN_ID}
    live = live_run_ids if live_run_ids is not None else known
    errors: list[tuple[str, str]] = []
    port = unused_port()
    origin = f"http://127.0.0.1:{port}"
    server = StudioRunStageServer(
        run_exists=lambda run_id: run_id in known or artifacts.has_run(run_id),
        live_run_exists=lambda run_id: run_id in live,
        artifact_reader=artifacts.read_artifact,
        on_transport_error=lambda run_id, message: errors.append((run_id, message)),
        origin=origin,
        port=port,
        linger_seconds=linger_seconds,
        catch_up_bytes=catch_up_bytes,
        max_frame_bytes=max_frame_bytes,
        spectator_queue_bytes=spectator_queue_bytes,
    )
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.bound_port is not None:
                break
            if task.done():
                await task
            await asyncio.sleep(0.005)
        assert server.bound_port == port
        yield server, artifacts, errors
    finally:
        server.stop()
        await asyncio.wait_for(task, timeout=3)


async def fetch(url: str) -> tuple[int, bytes, str]:
    def request() -> tuple[int, bytes, str]:
        try:
            response = urlopen(url, timeout=2)
        except HTTPError as error:
            response = error
        return response.status, response.read(), response.headers.get_content_type()

    return await asyncio.to_thread(request)


def test_catch_up_buffer_accounts_exact_bytes_and_preserves_endpoints() -> None:
    buffer = CatchUpBuffer(max_bytes=100, max_frame_bytes=40)
    tick_zero = LiveFrame(b"0" * 30, 0, False)
    first = LiveFrame(b"1" * 30, 1, False)
    second = LiveFrame(b"2" * 30, 2, False)
    third = LiveFrame(b"3" * 30, 3, False)
    terminal = LiveFrame(b"f" * 30, 4, True)

    for frame in (tick_zero, first, second, third, terminal):
        buffer.append(frame)

    assert buffer.byte_count == sum(len(frame.payload) for frame in buffer.frames)
    assert buffer.byte_count <= 100
    assert buffer.frames[0] == tick_zero
    assert buffer.frames[-1] == terminal
    assert first not in buffer.frames


def test_catch_up_guard_drops_intermediates_and_disables_on_guaranteed_oversize() -> None:
    buffer = CatchUpBuffer(max_bytes=100, max_frame_bytes=40)

    accepted, error = buffer.append(LiveFrame(b"i" * 41, 1, False))
    assert (accepted, error, buffer.disabled) == (False, None, False)

    accepted, error = buffer.append(LiveFrame(b"0" * 41, 0, False))
    assert accepted is False
    assert "guaranteed" in error
    assert buffer.disabled is True
    assert buffer.byte_count == 0
    assert buffer.snapshot() == ()


def test_spectator_queue_coalesces_only_intermediates_and_guarantees_final() -> None:
    async def exercise() -> None:
        queue = SpectatorQueue(max_bytes=80)
        tick_zero = LiveFrame(b"0" * 30, 0, False)
        queue.seed((tick_zero,))
        queue.put(LiveFrame(b"1" * 30, 1, False))
        queue.put(LiveFrame(b"2" * 30, 2, False))
        terminal = LiveFrame(b"f" * 30, 3, True)
        queue.put(terminal)

        assert queue.byte_count == 60
        assert await queue.get() == tick_zero
        assert await queue.get() == terminal
        assert queue.byte_count == 0

    asyncio.run(exercise())


def test_live_hub_disables_oversized_bootstrap_and_reports_transport_error() -> None:
    async def exercise() -> None:
        errors: list[tuple[str, str]] = []
        hub = LiveRunHub(
            on_transport_error=lambda run_id, message: errors.append((run_id, message)),
            catch_up_bytes=300,
            max_frame_bytes=100,
            spectator_queue_bytes=300,
        )

        hub.publish(RUN_ID, serialized_frame(0, padding=100))

        assert errors and errors[0][0] == RUN_ID
        assert "size limit" in errors[0][1]
        assert hub.subscribe(RUN_ID) is None

    asyncio.run(exercise())


def test_prefixed_viewer_route_maps_to_sibling_socket_and_artifact(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with running_server(tmp_path) as (server, artifacts, _errors):
            artifacts.publish(
                RUN_ID,
                replay=b"canonical-v3-replay",
                results={"scores": [1.0]},
                studio={"seed": "1"},
            )
            base = f"http://127.0.0.1:{server.bound_port}"
            viewer_status, viewer, viewer_type = await fetch(
                f"{base}/runs/{RUN_ID}/client/replay"
                f"?replay=/runs/{RUN_ID}/replay.bin"
            )
            replay_status, replay, replay_type = await fetch(
                f"{base}/runs/{RUN_ID}/replay.bin"
            )
            missing_status, _, _ = await fetch(f"{base}/runs/{RUN_ID}/results.json")
            traversal_status, _, _ = await fetch(
                f"{base}/runs/{RUN_ID}/client/%2e%2e/replay.bin"
            )

            server.publish(RUN_ID, fixture_frames()[0])
            websocket_url = f"ws://127.0.0.1:{server.bound_port}/runs/{RUN_ID}/replay"
            async with connect(websocket_url, origin=server.origin, proxy=None) as websocket:
                message = await asyncio.wait_for(websocket.recv(), timeout=1)

        assert viewer_status == replay_status == 200
        assert viewer_type == "text/html"
        assert replay_type == "application/octet-stream"
        assert b"function socketUrl()" in viewer
        assert replay == b"canonical-v3-replay"
        assert missing_status == traversal_status == 404
        assert isinstance(message, str)
        assert json.loads(message)["timestep"] == 0

    asyncio.run(exercise())


def test_mid_run_join_gets_atomic_monotonic_catch_up_then_live(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with running_server(tmp_path) as (server, _artifacts, _errors):
            frames = fixture_frames()
            await asyncio.to_thread(server.publish, RUN_ID, frames[0])
            await asyncio.to_thread(server.publish, RUN_ID, frames[1])
            await asyncio.sleep(0)
            url = f"ws://127.0.0.1:{server.bound_port}/runs/{RUN_ID}/replay"
            async with connect(url, origin=server.origin, proxy=None) as websocket:
                messages = [
                    json.loads(await asyncio.wait_for(websocket.recv(), timeout=1))
                    for _ in range(2)
                ]
                await asyncio.to_thread(server.publish, RUN_ID, frames[2])
                messages.append(
                    json.loads(await asyncio.wait_for(websocket.recv(), timeout=1))
                )

        assert [message["timestep"] for message in messages] == [0, 1, 2]
        assert all(message["format"] == "sugarscape.frame.v1" for message in messages)

    asyncio.run(exercise())


def test_websocket_rejects_wrong_and_missing_origins(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with running_server(tmp_path) as (server, _artifacts, _errors):
            url = f"ws://127.0.0.1:{server.bound_port}/runs/{RUN_ID}/replay"
            with pytest.raises(InvalidStatus) as wrong:
                async with connect(url, origin="https://evil.example", proxy=None):
                    pass
            with pytest.raises(InvalidStatus) as missing:
                async with connect(url, proxy=None):
                    pass

        assert wrong.value.response.status_code == 403
        assert missing.value.response.status_code == 403

    asyncio.run(exercise())


def test_cancelled_stream_closes_without_synthesizing_a_final_frame(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with running_server(tmp_path) as (server, _artifacts, _errors):
            server.publish(RUN_ID, fixture_frames()[0])
            url = f"ws://127.0.0.1:{server.bound_port}/runs/{RUN_ID}/replay"
            async with connect(url, origin=server.origin, proxy=None) as websocket:
                first = json.loads(await asyncio.wait_for(websocket.recv(), timeout=1))
                server.close_run(RUN_ID)
                remainder = []
                async for message in websocket:
                    remainder.append(json.loads(message))

        assert first["final"] is False
        assert not any(frame["final"] for frame in remainder)

    asyncio.run(exercise())


def test_terminal_connection_lingers_long_enough_for_viewer_settle(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with running_server(tmp_path, linger_seconds=2.2) as (
            server,
            _artifacts,
            _errors,
        ):
            frames = fixture_frames()
            server.publish(RUN_ID, frames[0])
            server.publish(RUN_ID, frames[-1])
            url = f"ws://127.0.0.1:{server.bound_port}/runs/{RUN_ID}/replay"
            websocket = await connect(url, origin=server.origin, proxy=None)
            try:
                assert json.loads(await websocket.recv())["timestep"] == 0
                assert json.loads(await websocket.recv())["final"] is True
                started = monotonic()
                await websocket.wait_closed()
                elapsed = monotonic() - started
            finally:
                await websocket.close()

        assert server.linger_seconds >= 2.0
        assert elapsed >= 2.0

    asyncio.run(exercise())


def test_new_run_drops_previous_catch_up_and_closes_old_subscribers() -> None:
    async def exercise() -> None:
        hub = LiveRunHub(
            on_transport_error=lambda _run_id, _message: None,
            catch_up_bytes=300,
            max_frame_bytes=100,
            spectator_queue_bytes=300,
        )
        first_queue = hub.subscribe(RUN_ID)
        assert first_queue is not None
        hub.publish(RUN_ID, serialized_frame(0))
        next_run = "2" * 32
        hub.publish(next_run, serialized_frame(0))

        assert first_queue.closed is True
        assert hub.subscribe(RUN_ID) is None
        next_queue = hub.subscribe(next_run)
        assert next_queue is not None
        assert [frame.timestep for frame in next_queue.frames] == [0]

    asyncio.run(exercise())


def test_finished_run_can_be_followed_by_a_presubscribed_run() -> None:
    async def exercise() -> None:
        hub = LiveRunHub(
            on_transport_error=lambda _run_id, _message: None,
            catch_up_bytes=300,
            max_frame_bytes=100,
            spectator_queue_bytes=300,
        )
        first = hub.subscribe(RUN_ID)
        assert first is not None
        hub.publish(RUN_ID, serialized_frame(0))
        state = hub._runs[RUN_ID]
        hub.close_run(RUN_ID)

        assert state.buffer.byte_count == 0
        assert not state.spectators
        assert RUN_ID not in hub._runs
        assert hub._closed_run_id == RUN_ID

        next_run = "2" * 32
        second = hub.subscribe(next_run)
        assert second is not None
        hub.publish(next_run, serialized_frame(0))

        assert second.closed is False
        assert (await second.get()).timestep == 0

    asyncio.run(exercise())


def test_close_before_first_publish_rejects_a_late_subscriber() -> None:
    async def exercise() -> None:
        hub = LiveRunHub(
            on_transport_error=lambda _run_id, _message: None,
            catch_up_bytes=300,
            max_frame_bytes=100,
            spectator_queue_bytes=300,
        )
        hub.close_run(RUN_ID)

        assert hub.subscribe(RUN_ID) is None
        assert hub.subscribe("2" * 32) is not None

    asyncio.run(exercise())


def test_closed_active_run_is_vacated_for_the_next_subscriber() -> None:
    async def exercise() -> None:
        hub = LiveRunHub(
            on_transport_error=lambda _run_id, _message: None,
            catch_up_bytes=300,
            max_frame_bytes=100,
            spectator_queue_bytes=300,
        )
        assert hub.subscribe(RUN_ID) is not None
        hub.disable(RUN_ID, "transport failed")

        assert hub.subscribe("2" * 32) is not None

    asyncio.run(exercise())


def test_bad_spectator_queue_does_not_block_other_spectators() -> None:
    async def exercise() -> None:
        hub = LiveRunHub(
            on_transport_error=lambda _run_id, _message: None,
            catch_up_bytes=300,
            max_frame_bytes=100,
            spectator_queue_bytes=300,
        )
        bad = hub.subscribe(RUN_ID)
        good = hub.subscribe(RUN_ID)
        assert bad is not None and good is not None

        def reject(_frame: LiveFrame) -> None:
            raise RuntimeError("queue invariant failed")

        bad.put = reject
        hub.publish(RUN_ID, serialized_frame(0))

        assert bad.closed is True
        assert (await good.get()).timestep == 0

    asyncio.run(exercise())


def test_two_sequential_coordinator_runs_each_feed_a_presubscribed_spectator(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        loop = asyncio.get_running_loop()
        hub = LiveRunHub(
            on_transport_error=lambda _run_id, _message: None,
            catch_up_bytes=24 * 1024 * 1024,
            max_frame_bytes=8 * 1024 * 1024,
            spectator_queue_bytes=24 * 1024 * 1024,
        )
        releases = [asyncio.Event(), asyncio.Event()]
        attempt = 0

        def runner(config: dict, _rulesets: tuple, **kwargs: object) -> tuple:
            nonlocal attempt
            release = releases[attempt]
            attempt += 1
            asyncio.run_coroutine_threadsafe(release.wait(), loop).result(2)
            document = json.loads(
                (ROOT / "tests/fixtures/replay-viewer-v3-golden.json").read_text()
            )["document"]
            header = document["header"]
            header.pop("scores", None)
            header.pop("seat_details", None)
            header["config"]["timesteps"] = config["timesteps"]
            kwargs["header_sink"](header)
            for frame in document["frames"]:
                kwargs["frame_sink"](frame)
            return {"scores": [0.5, 0.75], "details": []}, b"replay", {}

        registry = RunRegistry()
        coordinator = RunCoordinator(
            registry,
            ArtifactStore(tmp_path / "runs"),
            publisher=lambda run_id, payload: loop.call_soon_threadsafe(
                hub.publish, run_id, payload
            ),
            run_finished=lambda run_id: loop.call_soon_threadsafe(hub.close_run, run_id),
            episode_runner=runner,
        )
        catalog = StudioVariantCatalog.load()
        ruleset = json.loads((ROOT / "rulesets/worked-example.json").read_text())

        for index, release in enumerate(releases):
            started = coordinator.start(
                catalog,
                ruleset=ruleset,
                variant_id="duo-ladder",
                mode="ranked-preview",
                seed=str(17 + index),
            )
            spectator = hub.subscribe(str(started["run_id"]))
            assert spectator is not None
            release.set()
            frame = await asyncio.wait_for(spectator.get(), timeout=2)
            assert frame is not None and frame.timestep == 0
            worker = registry.worker(str(started["run_id"]))
            assert worker is not None
            await asyncio.to_thread(worker.join, 3)
            await asyncio.sleep(0)

    asyncio.run(exercise())


def test_artifact_only_run_rejects_live_subscription_immediately(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with running_server(
            tmp_path,
            run_ids={RUN_ID},
            live_run_ids=set(),
        ) as (server, artifacts, _errors):
            artifacts.publish(
                RUN_ID,
                replay=b"replay",
                results={"scores": [1.0]},
                studio={"seed": "1"},
            )
            url = f"ws://127.0.0.1:{server.bound_port}/runs/{RUN_ID}/replay"
            async with connect(url, origin=server.origin, proxy=None) as websocket:
                await asyncio.wait_for(websocket.wait_closed(), timeout=1)
                assert websocket.close_code == 1008

    asyncio.run(exercise())
