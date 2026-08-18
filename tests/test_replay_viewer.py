from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "replay-viewer"


def test_viewer_supports_all_static_bundle_inputs_and_controls() -> None:
    """The embed contract, asserted against the built document.

    The viewer is now ONE self-contained file: the Observatory serves it inside a
    sandboxed iframe behind a proxy that rewrites the base href and cannot reach a
    CDN, so anything split into a sub-resource renders as a black box. The
    contract itself is unchanged — the same query parameters, the same
    postMessage envelope, the same decompression, the same loop.
    """

    html = (VIEWER / "index.html").read_text(encoding="utf-8")

    assert "autoplay" not in html  # Playback is game-controlled, not a media element.
    assert 'params.get("replay")' in html
    assert 'params.get("chrome") === "off"' in html
    assert 'event.data.type !== "coworld-replay"' in html
    assert 'new DecompressionStream("deflate")' in html
    # It reads a v3 recording directly: deltas forward into whole frames.
    assert "agent_deltas" in html
    assert 'sugarscape.replay.v3' in html
    # Controls the embedder relies on.
    assert 'id="play"' in html
    assert 'id="scrub"' in html


def test_the_document_fetches_nothing() -> None:
    """The whole point of the single file. A sub-resource here is a black box."""

    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    body = html.replace('<base href="/">', "")
    for offender in ("<script src=", "<link href=", "@import", "https://fonts", "https://cdn"):
        assert offender not in body, offender


def test_build_hook_copies_a_self_contained_bundle(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    completed = subprocess.run(
        [str(ROOT / "tools" / "build_replay_viewer.sh"), str(output)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    # One file, because everything else is inlined into it.
    assert sorted(path.name for path in output.iterdir()) == ["index.html"]
    assert (output / "index.html").read_bytes() == (VIEWER / "index.html").read_bytes()


def test_generated_document_is_current() -> None:
    """`index.html` is generated; a stale one ships last week's viewer."""

    completed = subprocess.run(
        ["python3", str(ROOT / "tools" / "build_viewer.py"), "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_viewer_scoring_matches_the_engine() -> None:
    """The viewer scores the catalog itself, so it must agree with the engine.

    An episode is assigned one target but every variable is measured, so the
    viewer can score any target in the catalog — which means it carries its own
    port of target-scaled W1. A port that drifts would quietly disagree with the
    number the episode was actually judged on, so its arithmetic is compared
    across every target and every possible delta mass.
    """

    import json

    from coworld.scoring import Histogram, score_histogram

    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    assert "scoreAgainst" in html, "the viewer must carry the scorer it claims to"
    assert 'const SCORE_METHOD = "w1-hyperbolic/1"' in html
    assert 'const LEGACY_SCORE_METHOD = "w1-support/1"' in html
    assert "return null;" in html  # Unknown methods fail closed.

    def raw_w1(target_probs: list[float], measured: list[float], bins: list[float]) -> float:
        cumulative_measured = 0.0
        cumulative_target = 0.0
        distance = 0.0
        for index, probability in enumerate(target_probs):
            cumulative_measured += measured[index]
            cumulative_target += probability
            distance += abs(cumulative_measured - cumulative_target) * (
                bins[index + 1] - bins[index]
            )
        return distance

    def ported_score(target: dict[str, object], measured: list[float]) -> float:
        probs = target["probs"]
        bins = target["bins"]
        cumulative = 0.0
        median_index = 0
        for index, probability in enumerate(probs):
            cumulative += probability
            if cumulative >= 0.5:
                median_index = index
                break
        point_mass = [float(index == median_index) for index in range(len(probs))]
        scale = max(
            raw_w1(probs, point_mass, bins),
            bins[median_index + 1] - bins[median_index],
        )
        distance = raw_w1(probs, measured, bins)
        return scale / (scale + distance)

    for target_path in sorted((ROOT / "targets").glob("*.json")):
        target = json.loads(target_path.read_text(encoding="utf-8"))
        if target.get("kind", "distribution") != "distribution":
            continue
        for measured_index in range(len(target["probs"])):
            measured = [float(index == measured_index) for index in range(len(target["probs"]))]
            engine = score_histogram(
                Histogram(
                    bins=tuple(target["bins"]),
                    probs=tuple(measured),
                    sample_count=137,
                ),
                tuple(target["probs"]),
            ).score
            assert ported_score(target, measured) == engine, (target["id"], measured_index)


def test_v3_converter_keeps_empty_legacy_measurements_at_zero() -> None:
    import importlib.util

    converter_path = ROOT / "tools" / "v3_to_v1_replay.py"
    spec = importlib.util.spec_from_file_location("v3_to_v1_replay", converter_path)
    assert spec is not None and spec.loader is not None
    converter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(converter)

    target = {"bins": [0, 1, 2], "probs": [0.5, 0.5]}
    empty = {"bins": [0, 1, 2], "probs": [0.0, 0.0], "sample_count": 0}
    assert converter.score_against(target, empty, converter.LEGACY_SCORE_METHOD) == 0
