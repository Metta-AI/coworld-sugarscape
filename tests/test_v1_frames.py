from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import zlib

from coworld.v1_frames import V1FrameMaterializer, convert_document


ROOT = Path(__file__).resolve().parents[1]
V3_FIXTURE = ROOT / "tests" / "fixtures" / "replay-viewer-v3-golden.json"
V1_FIXTURE = ROOT / "tests" / "fixtures" / "replay-viewer-v1-golden.json"


def _documents() -> tuple[dict, dict]:
    source = json.loads(V3_FIXTURE.read_text(encoding="utf-8"))["document"]
    expected = json.loads(V1_FIXTURE.read_text(encoding="utf-8"))
    return source, expected


def _incremental_frames(document: dict) -> list[dict[str, object]]:
    materializer = V1FrameMaterializer(
        document["header"], max_timestep=len(document["frames"])
    )
    frames = [materializer.initial_frame()]
    for index, frame in enumerate(document["frames"]):
        materializer.apply_frame(frame)
        frames.append(
            materializer.materialize(final=index == len(document["frames"]) - 1)
        )
    return frames


def test_batch_and_incremental_match_pre_refactor_golden_bytes() -> None:
    document, expected = _documents()

    batch = convert_document(document)
    incremental = {
        "format": "sugarscape.replay.v1",
        "config": document["header"]["config"],
        "frames": _incremental_frames(document),
    }

    assert batch == incremental == expected
    assert json.dumps(batch).encode("utf-8") == V1_FIXTURE.read_bytes().removesuffix(b"\n")


def test_sparse_materialization_matches_batch_at_sampled_ticks() -> None:
    document, expected = _documents()
    materializer = V1FrameMaterializer(document["header"])
    sparse = [materializer.initial_frame()]

    for index, frame in enumerate(document["frames"]):
        materializer.apply_frame(frame)
        if index in {1, len(document["frames"]) - 1}:
            sparse.append(
                materializer.materialize(final=index == len(document["frames"]) - 1)
            )

    assert sparse == [expected["frames"][0], expected["frames"][2], expected["frames"][3]]


def test_running_measurements_carry_forward_between_samples() -> None:
    document, _expected = _documents()
    materializer = V1FrameMaterializer(document["header"])
    materializer.apply_frame(document["frames"][0])
    materializer.apply_frame(document["frames"][1])
    sampled = materializer.coworld_block()

    materializer.apply_frame(document["frames"][2])
    carried = materializer.coworld_block()

    assert sampled["seats"] == carried["seats"]
    assert carried["seats"][1]["score"] == 0.25
    assert carried["seats"][1]["sampleCount"] == 1
    assert next(
        choice for choice in carried["choices"] if choice["id"] == "wealth.egalitarian"
    )["sampleCount"] == 3


def test_terminal_materialization_injects_scores_missing_from_bootstrap() -> None:
    document, _expected = _documents()
    header = deepcopy(document["header"])
    final_scores = header.pop("scores")
    header.pop("seat_details", None)
    materializer = V1FrameMaterializer(header)

    assert materializer.initial_frame()["coworld"]["finalScores"] == []
    for frame in document["frames"]:
        materializer.apply_frame(frame)

    before_finish = materializer.materialize()
    terminal = materializer.materialize(final=True, final_scores=final_scores)

    assert before_finish["coworld"]["finalScores"] == []
    assert terminal["final"] is True
    assert terminal["coworld"]["finalScores"] == final_scores
    assert terminal["coworld"]["seats"][1]["score"] == 0.25


def test_commonwealth_scalar_readings_survive_incremental_materialization() -> None:
    document, _expected = _documents()
    document = deepcopy(document)
    document["header"]["score_method"] = "wellness-sum/1"
    document["header"]["targets"] = [
        {
            "id": f"wellness.max.{seat}",
            "kind": "maximize",
            "variable": "wellness",
            "description": "Maximize survivor wellness.",
        }
        for seat in range(2)
    ]
    document["header"]["scores"] = [4.5, 6.75]
    for index, frame in enumerate(document["frames"]):
        frame["running"] = [
            {
                "seat": seat,
                "kind": "maximize",
                "variable": "wellness",
                "score_method": "wellness-sum/1",
                "score": 0.5 + seat + index,
                "histogram": {
                    "bins": [0, 0.5, 1],
                    "probs": [0.5, 0.5],
                    "sample_count": 2,
                },
                "survivor_count": 2 + seat,
                "mean_wellness": 0.5 + seat * 0.1,
                "component_means": {
                    "health": 1,
                    "conflict": 0,
                    "social": -0.25,
                    "family": 0.5,
                    "wealth": 0.1,
                },
            }
            for seat in range(2)
        ]

    batch = convert_document(document)
    incremental = _incremental_frames(document)
    terminal = batch["frames"][-1]

    assert batch["frames"] == incremental
    assert terminal["coworld"]["finalScores"] == [4.5, 6.75]
    assert [seat["targetKind"] for seat in terminal["coworld"]["seats"]] == [
        "maximize",
        "maximize",
    ]
    assert [seat["scoreMethod"] for seat in terminal["coworld"]["seats"]] == [
        "wellness-sum/1",
        "wellness-sum/1",
    ]
    assert [seat["survivorCount"] for seat in terminal["coworld"]["seats"]] == [
        2,
        3,
    ]
    assert terminal["coworld"]["seats"][1]["componentMeans"]["family"] == 0.5
    assert all(choice.get("targetKind") is None for choice in terminal["coworld"]["choices"])


def test_cli_output_is_byte_identical_to_pre_refactor_converter(
    tmp_path: Path,
) -> None:
    document, _expected = _documents()
    source = tmp_path / "replay.bin"
    destination = tmp_path / "replay.v1.json"
    source.write_bytes(zlib.compress(json.dumps(document).encode("utf-8")))

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "v3_to_v1_replay.py"),
            str(source),
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert destination.read_bytes() == V1_FIXTURE.read_bytes().removesuffix(b"\n")
    assert f"{source} -> {destination}" in completed.stdout
    assert "4 frames, t0..t3, 2x2, 2 seat(s), maxSugar 4 maxSpice 0" in completed.stdout
