from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from http.client import HTTPResponse
import json
from pathlib import Path
from threading import Event, Thread
from typing import Callable, Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from coworld.episode import run_episode
from coworld.replay import decode_replay
from coworld.studio import StudioVariant, StudioVariantCatalog
from coworld.studio_runs import (
    ArtifactStore,
    RunCoordinator,
    RunRegistry,
    RunServerStopping,
    StudioRunNotFound,
    SampledLiveRun,
)
from coworld.v1_frames import convert_document
from ruleset_studio_import import load_studio_server


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "replay-viewer-v3-golden.json"
STARTER = json.loads((ROOT / "rulesets" / "worked-example.json").read_text(encoding="utf-8"))
ORIGIN = "http://127.0.0.1:4173"
studio_server = load_studio_server(ROOT / "ruleset-studio" / "server.py")


def fixture_document() -> dict:
    return deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))["document"])


def fixture_header() -> dict:
    header = fixture_document()["header"]
    header.pop("scores", None)
    header.pop("seat_details", None)
    return header


def fixture_results() -> dict[str, object]:
    return {
        "scores": [0.5, 0.75],
        "details": [],
        "seed": 17,
        "marker": "engine-result",
        "rulesets_identical": False,
    }


def successful_fixture_runner(capture: dict | None = None) -> Callable[..., tuple]:
    def runner(config: dict, rulesets: tuple, **kwargs: object) -> tuple:
        document = fixture_document()
        header = fixture_header()
        header["config"]["timesteps"] = config["timesteps"]
        kwargs["header_sink"](header)
        for frame in document["frames"]:
            kwargs["frame_sink"](frame)
        results = fixture_results()
        replay = b"engine-replay-bytes"
        if capture is not None:
            capture.update(
                {
                    "config": config,
                    "rulesets": rulesets,
                    "submitted": kwargs["submitted"],
                    "results": results,
                    "replay": replay,
                }
            )
        return results, replay, {"total_ns": 1}

    return runner


def coordinator(
    tmp_path: Path,
    runner: Callable[..., tuple],
    published: list[tuple[str, bytes]] | None = None,
    run_finished: Callable[[str], None] | None = None,
) -> tuple[RunCoordinator, RunRegistry, ArtifactStore]:
    registry = RunRegistry()
    artifacts = ArtifactStore(tmp_path / "runs")
    output = published if published is not None else []
    return (
        RunCoordinator(
            registry,
            artifacts,
            publisher=lambda run_id, frame: output.append((run_id, frame)),
            run_finished=run_finished,
            episode_runner=runner,
        ),
        registry,
        artifacts,
    )


def wait_for_worker(registry: RunRegistry, run_id: str) -> None:
    worker = registry.worker(run_id)
    assert worker is not None
    worker.join(3)
    assert not worker.is_alive()


def start_duo(run_coordinator: RunCoordinator, *, seed: str = "17") -> dict[str, object]:
    return run_coordinator.start(
        StudioVariantCatalog.load(),
        ruleset=STARTER,
        variant_id="duo-ladder",
        mode="ranked-preview",
        seed=seed,
    )


def test_sampled_live_run_matches_incremental_materializer_at_sampled_ticks() -> None:
    document = fixture_document()
    header = fixture_header()
    emitted: list[dict] = []
    progress: list[int] = []
    live = SampledLiveRun(
        "a" * 32,
        timesteps=480,
        publisher=lambda _run_id, payload: emitted.append(json.loads(payload)),
        progress=lambda tick, _scores: progress.append(tick),
        cancelled=lambda: False,
    )

    live.header_sink(header)
    for frame in document["frames"]:
        live.frame_sink(frame)
    assert [frame["timestep"] for frame in emitted] == [0, 2]
    assert all(frame["final"] is False for frame in emitted)
    live.finalize({"scores": [0.5, 0.75]})

    batch = convert_document(document)["frames"]
    expected = deepcopy([batch[0], batch[2], batch[3]])
    expected[0]["coworld"]["finalScores"] = []
    expected[1]["coworld"]["finalScores"] = []
    assert emitted == expected
    assert progress == [1, 2, 3]


def test_terminal_frame_reapplies_measurements_added_after_sink() -> None:
    document = fixture_document()
    terminal = document["frames"][-1]
    sampled = document["frames"][1]
    running = deepcopy(sampled["running"])
    measured = deepcopy(sampled["measured"])
    emitted: list[dict] = []
    live = SampledLiveRun(
        "b" * 32,
        timesteps=3,
        publisher=lambda _run_id, payload: emitted.append(json.loads(payload)),
        progress=lambda _tick, _scores: None,
        cancelled=lambda: False,
    )

    live.header_sink(fixture_header())
    for frame in document["frames"]:
        live.frame_sink(frame)
    terminal["running"] = running
    terminal["measured"] = measured
    live.finalize({"scores": [0.5, 0.75]})

    assert emitted[-1]["final"] is True
    assert emitted[-1]["coworld"]["finalScores"] == [0.5, 0.75]
    assert emitted[-1]["coworld"]["seats"][0]["sampleCount"] > 0


def test_terminal_commonwealth_details_come_from_engine_results() -> None:
    header = fixture_header()
    header["targets"] = [
        {
            "id": "wellness.max",
            "kind": "maximize",
            "variable": "wellness",
            "description": "Maximize survivor wellness.",
        }
    ]
    header["config"]["players"] = [{"name": "Commonwealth"}]
    emitted: list[dict] = []
    live = SampledLiveRun(
        "c" * 32,
        timesteps=3,
        publisher=lambda _run_id, payload: emitted.append(json.loads(payload)),
        progress=lambda _tick, _scores: None,
        cancelled=lambda: False,
    )
    live.header_sink(header)
    live.finalize(
        {
            "scores": [3.25],
            "details": [
                {
                    "seat": 0,
                    "target_kind": "maximize",
                    "score_method": "wellness-sum/1",
                    "survivor_count": 4,
                    "mean_wellness": 0.8125,
                    "component_means": {"health": 1.0, "wealth": 0.5},
                }
            ],
        }
    )

    seat = emitted[-1]["coworld"]["seats"][0]
    assert emitted[-1]["coworld"]["finalScores"] == [3.25]
    assert seat["targetKind"] == "maximize"
    assert seat["scoreMethod"] == "wellness-sum/1"
    assert seat["survivorCount"] == 4
    assert seat["componentMeans"]["health"] == 1.0


def test_duo_run_builds_baseline_from_resolved_target_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, object] = {}
    chosen_targets: list[dict[str, object]] = []

    def choose(target: dict[str, object]) -> dict[str, object]:
        chosen_targets.append(target)
        return {"version": 1, "movement": [{"score": 1}]}

    monkeypatch.setattr("coworld.studio_runs.choose_ruleset", choose)
    run_coordinator, registry, artifacts = coordinator(
        tmp_path, successful_fixture_runner(capture)
    )

    started = start_duo(run_coordinator, seed="9007199254740993")
    wait_for_worker(registry, started["run_id"])

    assert started["seats"] == 2
    assert started["seed"] == "9007199254740993"
    assert len(capture["rulesets"]) == 2
    assert capture["submitted"] == (True, False)
    selected = capture["config"]["scenario_pool"][
        int(capture["config"]["seed"]) % len(capture["config"]["scenario_pool"])
    ]
    assert chosen_targets[0]["id"] == selected["targets"][1]
    assert isinstance(chosen_targets[0], dict)
    sidecar = json.loads(
        artifacts.read_artifact(started["run_id"], "studio.json")
    )
    assert sidecar["seed"] == "9007199254740993"
    assert sidecar["opponents"][0]["policy"] == "baseline"


def test_singleton_commonwealth_target_builds_every_resolved_opponent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    local.update(
        {
            "tokens": ["platform-would-force-one"],
            "seats": 2,
            "startingAgents": 8,
            "agentReplacements": 0,
            "targets": ["wellness.max"],
        }
    )
    catalog = StudioVariantCatalog(
        [StudioVariant("solo-ladder", "Qualifier", "", "fixed", local, ())]
    )
    chosen: list[dict[str, object]] = []
    monkeypatch.setattr(
        "coworld.studio_runs.choose_ruleset",
        lambda target: chosen.append(target) or deepcopy(STARTER),
    )
    capture: dict[str, object] = {}
    run_coordinator, registry, _artifacts = coordinator(
        tmp_path, successful_fixture_runner(capture)
    )

    started = run_coordinator.start(
        catalog,
        ruleset=STARTER,
        variant_id="solo-ladder",
        mode="fixed",
        seed="17",
    )
    wait_for_worker(registry, started["run_id"])

    assert started["seats"] == 2
    assert len(capture["rulesets"]) == 2
    assert capture["submitted"] == (True, False)
    assert [target["id"] for target in chosen] == ["wellness.max"]


def test_real_engine_artifacts_are_published_byte_for_byte(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def capturing_runner(*args: object, **kwargs: object) -> tuple:
        result = run_episode(*args, **kwargs)
        captured["results"], captured["replay"], _ = result
        return result

    published: list[tuple[str, bytes]] = []
    run_coordinator, registry, artifacts = coordinator(
        tmp_path, capturing_runner, published
    )
    started = run_coordinator.start(
        StudioVariantCatalog.load(),
        ruleset=STARTER,
        variant_id="local-default",
        mode="fixed",
        seed="31",
        timesteps=5,
    )
    wait_for_worker(registry, started["run_id"])

    replay = artifacts.read_artifact(started["run_id"], "replay.bin")
    results_bytes = artifacts.read_artifact(started["run_id"], "results.json")
    assert replay == captured["replay"]
    assert json.loads(results_bytes) == captured["results"]
    assert results_bytes == json.dumps(
        captured["results"],
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert decode_replay(replay)["header"]["scores"] == captured["results"]["scores"]
    assert json.loads(published[-1][1])["final"] is True
    assert captured["results"]["rulesets_identical"] is True


def test_run_accepts_the_blockly_compilers_decoded_null_value(tmp_path: Path) -> None:
    capture: dict[str, object] = {}
    run_coordinator, registry, _artifacts = coordinator(
        tmp_path, successful_fixture_runner(capture)
    )

    started = run_coordinator.start(
        StudioVariantCatalog.load(),
        ruleset=None,
        variant_id="local-default",
        mode="fixed",
        seed="31",
        timesteps=2,
    )
    wait_for_worker(registry, started["run_id"])

    assert capture["rulesets"] == (None,)
    assert run_coordinator.status(started["run_id"])["state"] == "done"


def test_baseline_opponent_ruleset_agreement_is_not_a_run_failure(tmp_path: Path) -> None:
    run_coordinator, registry, _artifacts = coordinator(
        tmp_path, successful_fixture_runner()
    )

    started = start_duo(run_coordinator)
    wait_for_worker(registry, started["run_id"])
    status = run_coordinator.status(started["run_id"])

    assert status["state"] == "done"
    assert status["results"]["rulesets_identical"] is False


@pytest.mark.parametrize("cancel_point", ["before-first", "mid-run", "after-last"])
def test_cancellation_boundaries(
    tmp_path: Path,
    cancel_point: str,
) -> None:
    ready = Event()
    release = Event()
    emitted: list[tuple[str, bytes]] = []

    def runner(config: dict, _rulesets: tuple, **kwargs: object) -> tuple:
        document = fixture_document()
        header = fixture_header()
        header["config"]["timesteps"] = config["timesteps"]
        kwargs["header_sink"](header)
        frames = document["frames"]
        if cancel_point == "before-first":
            ready.set()
            release.wait(2)
            kwargs["frame_sink"](frames[0])
        elif cancel_point == "mid-run":
            kwargs["frame_sink"](frames[0])
            ready.set()
            release.wait(2)
            kwargs["frame_sink"](frames[1])
        else:
            kwargs["frame_sink"](frames[0])
            ready.set()
            release.wait(2)
        return fixture_results(), b"replay", {}

    run_coordinator, registry, artifacts = coordinator(tmp_path, runner, emitted)
    started = start_duo(run_coordinator)
    assert ready.wait(2)
    cancelling = run_coordinator.cancel(started["run_id"])
    assert cancelling["state"] == "cancelling"
    release.set()
    wait_for_worker(registry, started["run_id"])
    status = run_coordinator.status(started["run_id"])

    if cancel_point == "after-last":
        assert status["state"] == "done"
        assert artifacts.read_artifact(started["run_id"], "replay.bin") == b"replay"
        assert json.loads(emitted[-1][1])["final"] is True
    else:
        assert status["state"] == "cancelled"
        assert not (artifacts.root / started["run_id"]).exists()
        assert not any(json.loads(payload)["final"] for _, payload in emitted)


def test_failure_path_is_sanitized_and_next_post_reaps_slot(tmp_path: Path) -> None:
    attempts = 0

    def runner(*args: object, **kwargs: object) -> tuple:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("secret source /private/path")
        return successful_fixture_runner()(*args, **kwargs)

    run_coordinator, registry, _artifacts = coordinator(tmp_path, runner)
    first = start_duo(run_coordinator)
    wait_for_worker(registry, first["run_id"])
    first_status = run_coordinator.status(first["run_id"])
    second = start_duo(run_coordinator, seed="18")
    wait_for_worker(registry, second["run_id"])

    assert first_status["state"] == "error"
    assert first_status["error"] == "RuntimeError: run failed"
    assert "secret" not in json.dumps(first_status)
    assert run_coordinator.status(second["run_id"])["state"] == "done"


def test_live_transport_error_is_reported_without_failing_the_run(tmp_path: Path) -> None:
    ready = Event()
    release = Event()

    def runner(config: dict, _rulesets: tuple, **kwargs: object) -> tuple:
        header = fixture_header()
        header["config"]["timesteps"] = config["timesteps"]
        kwargs["header_sink"](header)
        ready.set()
        release.wait(2)
        kwargs["frame_sink"](fixture_document()["frames"][0])
        return fixture_results(), b"replay", {}

    run_coordinator, registry, _artifacts = coordinator(tmp_path, runner)
    started = start_duo(run_coordinator)
    assert ready.wait(2)

    run_coordinator.record_transport_error(started["run_id"], "live frame too large")
    running = run_coordinator.status(started["run_id"])
    release.set()
    wait_for_worker(registry, started["run_id"])
    finished = run_coordinator.status(started["run_id"])

    assert running["state"] == "running"
    assert running["transport_error"] == "live frame too large"
    assert finished["state"] == "done"
    assert finished["transport_error"] == "live frame too large"


@pytest.mark.parametrize("failure_stage", ["publisher", "artifact"])
def test_sink_and_artifact_failures_also_leave_a_reapable_slot(
    tmp_path: Path,
    failure_stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fail_next = True
    registry = RunRegistry()
    artifacts = ArtifactStore(tmp_path / "runs")

    def publisher(_run_id: str, _payload: bytes) -> None:
        nonlocal fail_next
        if failure_stage == "publisher" and fail_next:
            fail_next = False
            raise RuntimeError("serialization transport failed")

    if failure_stage == "artifact":
        real_publish = artifacts.publish

        def flaky_publish(*args: object, **kwargs: object) -> Path:
            nonlocal fail_next
            if fail_next:
                fail_next = False
                raise OSError("artifact write failed")
            return real_publish(*args, **kwargs)

        monkeypatch.setattr(artifacts, "publish", flaky_publish)

    run_coordinator = RunCoordinator(
        registry,
        artifacts,
        publisher=publisher,
        episode_runner=successful_fixture_runner(),
    )
    first = start_duo(run_coordinator)
    wait_for_worker(registry, first["run_id"])
    second = start_duo(run_coordinator, seed="18")
    wait_for_worker(registry, second["run_id"])

    assert run_coordinator.status(first["run_id"])["state"] == "error"
    assert run_coordinator.status(second["run_id"])["state"] == "done"


def test_thread_start_failure_leaves_a_reapable_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_start = Thread.start
    fail_next = True

    def flaky_start(thread: Thread) -> None:
        nonlocal fail_next
        if fail_next and thread.name.startswith("studio-run-"):
            fail_next = False
            raise RuntimeError("thread creation failed")
        real_start(thread)

    monkeypatch.setattr(Thread, "start", flaky_start)
    finished: list[str] = []
    run_coordinator, registry, _artifacts = coordinator(
        tmp_path,
        successful_fixture_runner(),
        run_finished=finished.append,
    )

    with pytest.raises(RuntimeError, match="thread creation failed"):
        start_duo(run_coordinator)
    assert len(finished) == 1
    second = start_duo(run_coordinator, seed="18")
    wait_for_worker(registry, second["run_id"])

    assert run_coordinator.status(second["run_id"])["state"] == "done"


def test_terminal_state_releases_slot_while_worker_drains_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pruning = Event()
    release = Event()
    run_coordinator, registry, artifacts = coordinator(
        tmp_path, successful_fixture_runner()
    )

    def blocking_prune(*, protected: set[str] | None = None) -> list[str]:
        pruning.set()
        release.wait(2)
        return []

    monkeypatch.setattr(artifacts, "prune", blocking_prune)
    first = start_duo(run_coordinator)
    assert pruning.wait(2)
    assert run_coordinator.status(first["run_id"])["state"] == "done"
    second = start_duo(run_coordinator, seed="18")
    release.set()
    wait_for_worker(registry, first["run_id"])
    wait_for_worker(registry, second["run_id"])


def test_registry_evicts_old_terminal_runs_but_keeps_displayed_tail(
    tmp_path: Path,
) -> None:
    registry = RunRegistry(max_runs=3)
    run_coordinator = RunCoordinator(
        registry,
        ArtifactStore(tmp_path / "runs"),
        publisher=lambda _run_id, _payload: None,
        episode_runner=successful_fixture_runner(),
    )
    run_ids: list[str] = []
    for index in range(5):
        started = start_duo(run_coordinator, seed=str(17 + index))
        run_id = str(started["run_id"])
        run_ids.append(run_id)
        if index == 0:
            run_coordinator.set_displayed(run_id)
        wait_for_worker(registry, run_id)

    assert run_coordinator.status(run_ids[0])["state"] == "done"
    with pytest.raises(StudioRunNotFound):
        run_coordinator.status(run_ids[1])
    assert [run_coordinator.status(run_id)["state"] for run_id in run_ids[-2:]] == [
        "done",
        "done",
    ]


def test_shutdown_timeout_never_resumes_accepting_runs(tmp_path: Path) -> None:
    ready = Event()
    release = Event()

    def runner(config: dict, _rulesets: tuple, **kwargs: object) -> tuple:
        header = fixture_header()
        header["config"]["timesteps"] = config["timesteps"]
        kwargs["header_sink"](header)
        ready.set()
        release.wait(2)
        kwargs["frame_sink"](fixture_document()["frames"][0])
        return fixture_results(), b"replay", {}

    run_coordinator, registry, _artifacts = coordinator(tmp_path, runner)
    started = start_duo(run_coordinator)
    assert ready.wait(2)
    worker = registry.worker(started["run_id"])
    assert worker is not None and worker.daemon is True

    assert run_coordinator.shutdown(0.01) is False
    with pytest.raises(RunServerStopping):
        start_duo(run_coordinator, seed="19")
    release.set()
    wait_for_worker(registry, started["run_id"])


@contextmanager
def studio_api(tmp_path: Path, run_coordinator: RunCoordinator) -> Iterator[str]:
    rulesets = tmp_path / "rulesets"
    rulesets.mkdir()
    paths = studio_server.StudioPaths(
        rulesets,
        ROOT / "config.json",
        ROOT / "src/sugarscape/config.json",
        ROOT / "coworld_manifest.json",
    )
    server = studio_server.create_server(
        "127.0.0.1",
        0,
        paths=paths,
        catalog=StudioVariantCatalog.load(),
        allowed_origin=ORIGIN,
        coordinator=run_coordinator,
    )
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: object | None = None,
) -> tuple[int, HTTPResponse, object | None]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Origin": ORIGIN}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    api_request = Request(base_url + path, data=body, headers=headers, method=method)
    try:
        response = urlopen(api_request)
    except HTTPError as error:
        response = error
    response_body = response.read()
    return response.status, response, json.loads(response_body) if response_body else None


def test_run_api_post_poll_cancel_and_displayed_pin(tmp_path: Path) -> None:
    ready = Event()
    release = Event()

    def runner(config: dict, _rulesets: tuple, **kwargs: object) -> tuple:
        header = fixture_header()
        header["config"]["timesteps"] = config["timesteps"]
        kwargs["header_sink"](header)
        ready.set()
        release.wait(2)
        kwargs["frame_sink"](fixture_document()["frames"][0])
        return fixture_results(), b"replay", {}

    run_coordinator, registry, _artifacts = coordinator(tmp_path, runner)
    run_body = {
        "ruleset": STARTER,
        "variant": "duo-ladder",
        "mode": "ranked-preview",
        "seed": "9007199254740993",
    }
    with studio_api(tmp_path, run_coordinator) as base_url:
        post_status, _, started = request(base_url, "/api/run", method="POST", payload=run_body)
        assert ready.wait(2)
        busy_status, _, busy = request(base_url, "/api/run", method="POST", payload=run_body)
        get_status, _, running = request(base_url, f"/api/run/{started['run_id']}")
        pin_status, _, pinned = request(
            base_url,
            "/api/displayed-run",
            method="PUT",
            payload={"run_id": started["run_id"]},
        )
        delete_status, _, cancelling = request(
            base_url, f"/api/run/{started['run_id']}", method="DELETE"
        )
        release.set()
        wait_for_worker(registry, started["run_id"])
        final_status, _, final = request(base_url, f"/api/run/{started['run_id']}")
        clear_status, _, cleared = request(
            base_url,
            "/api/displayed-run",
            method="PUT",
            payload={"run_id": None},
        )

    assert post_status == 202
    assert started["seed"] == "9007199254740993"
    assert (busy_status, busy["error"]) == (409, "a studio run is already in progress")
    assert get_status == pin_status == delete_status == clear_status == 200
    assert running["state"] == "running"
    assert pinned == {"displayed_run": started["run_id"]}
    assert cancelling["state"] == "cancelling"
    assert (final_status, final["state"]) == (200, "cancelled")
    assert cleared == {"displayed_run": None}


def test_run_api_returns_structured_compile_errors(tmp_path: Path) -> None:
    run_coordinator, _registry, _artifacts = coordinator(
        tmp_path, successful_fixture_runner()
    )
    with studio_api(tmp_path, run_coordinator) as base_url:
        status, _, body = request(
            base_url,
            "/api/run",
            method="POST",
            payload={
                "ruleset": {"version": 1, "movement": [{"score": ["bogus", 1]}]},
                "variant": "local-default",
                "mode": "fixed",
                "seed": "1",
            },
        )

    assert status == 400
    assert body["error"] == "compile failed"
    assert body["validation"]["errors"][0]["path"] == "$.movement[0].score[0]"
