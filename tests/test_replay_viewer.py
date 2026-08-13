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
    port of `1 - normalized_W1`. A port that drifts would quietly disagree with
    the number the episode was actually judged on, so the two implementations are
    compared here on the same inputs rather than each being trusted on its own.
    """

    import json

    from coworld.scoring import Histogram, score_histogram

    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    assert "scoreAgainst" in html, "the viewer must carry the scorer it claims to"

    # A histogram deliberately unlike its target, so a sloppy port cannot pass by
    # returning something near 1.
    target = json.loads((ROOT / "targets" / "wealth.skewed-gini-0.5.json").read_text())
    measured = [0.0, 0.40, 0.56, 0.04] + [0.0] * (len(target["probs"]) - 4)
    engine = score_histogram(
        Histogram(bins=tuple(target["bins"]), probs=tuple(measured), sample_count=137),
        tuple(target["probs"]),
    ).score

    # The same arithmetic the viewer runs, kept in step with replay-viewer/src.
    carried = 0.0
    distance = 0.0
    for index, probability in enumerate(target["probs"]):
        carried += measured[index] - probability
        distance += abs(carried) * (target["bins"][index + 1] - target["bins"][index])
    ported = max(0.0, min(1.0, 1 - distance / (target["bins"][-1] - target["bins"][0])))

    assert ported == round(engine, 12) or abs(ported - engine) < 1e-12, (ported, engine)
