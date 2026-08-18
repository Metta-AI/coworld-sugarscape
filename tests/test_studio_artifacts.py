from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Event, Thread

import pytest

from coworld.studio_runs import ArtifactStore


def run_id(index: int) -> str:
    return f"{index:032x}"


def publish(store: ArtifactStore, index: int) -> Path:
    return store.publish(
        run_id(index),
        replay=f"replay-{index}".encode(),
        results={"scores": [index / 10]},
        studio={"seed": str(9_007_199_254_740_993 + index)},
    )


def test_publish_renames_complete_same_filesystem_directory_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "runs")
    observed: dict[str, object] = {}
    real_rename = os.rename

    def capture_rename(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        observed.update(
            {
                "same_parent": source_path.parent == destination_path.parent,
                "destination_absent": not destination_path.exists(),
                "files": sorted(path.name for path in source_path.iterdir()),
            }
        )
        real_rename(source, destination)

    monkeypatch.setattr(os, "rename", capture_rename)
    destination = publish(store, 1)

    assert observed == {
        "same_parent": True,
        "destination_absent": True,
        "files": ["replay.bin", "results.json", "studio.json"],
    }
    assert destination.is_dir()
    assert destination.joinpath("replay.bin").read_bytes() == b"replay-1"
    assert json.loads(destination.joinpath("studio.json").read_bytes())["seed"] == (
        "9007199254740994"
    )
    with pytest.raises(FileExistsError):
        publish(store, 1)


def test_failed_publish_leaves_no_partial_or_temporary_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "runs")
    real_write = store._write
    writes = 0

    def fail_second_write(path: Path, payload: bytes) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("disk full")
        real_write(path, payload)

    monkeypatch.setattr(store, "_write", fail_second_write)

    with pytest.raises(OSError, match="disk full"):
        publish(store, 1)
    assert list(store.root.iterdir()) == []


def test_prune_to_limit_spares_active_and_displayed_runs(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "runs", max_runs=20)
    for index in range(22):
        destination = publish(store, index)
        os.utime(destination, ns=(index + 1, index + 1))

    removed = store.prune(protected={run_id(0), run_id(1)})
    remaining = {path.name for path in store.root.iterdir() if path.is_dir()}

    assert removed == [run_id(2), run_id(3)]
    assert len(remaining) == 20
    assert {run_id(0), run_id(1)} <= remaining


def test_fetch_racing_prune_reads_complete_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ArtifactStore(tmp_path / "runs", max_runs=1)
    publish(store, 0)
    publish(store, 1)
    reading = Event()
    release = Event()
    original_read_bytes = Path.read_bytes

    def blocking_read(path: Path) -> bytes:
        if path == store.root / run_id(0) / "replay.bin":
            reading.set()
            release.wait(2)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", blocking_read)
    fetched: list[bytes] = []
    reader = Thread(
        target=lambda: fetched.append(store.read_artifact(run_id(0), "replay.bin"))
    )
    pruner = Thread(target=store.prune)
    reader.start()
    assert reading.wait(2)
    pruner.start()
    pruner.join(0.02)
    assert pruner.is_alive()
    release.set()
    reader.join(2)
    pruner.join(2)

    assert fetched == [b"replay-0"]
    assert not (store.root / run_id(0)).exists()
    assert (store.root / run_id(1)).exists()


def test_artifact_paths_reject_untrusted_names(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "runs")

    with pytest.raises(ValueError):
        store.read_artifact("../outside", "replay.bin")
    with pytest.raises(FileNotFoundError):
        store.read_artifact(run_id(1), "../config.json")

    outside = tmp_path / "outside"
    outside.mkdir()
    linked_root = tmp_path / "linked-runs"
    linked_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        ArtifactStore(linked_root)
