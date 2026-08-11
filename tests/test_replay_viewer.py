from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "replay-viewer"


def test_viewer_supports_all_static_bundle_inputs_and_controls() -> None:
    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    javascript = (VIEWER / "app.js").read_text(encoding="utf-8")

    assert "autoplay" not in html  # Playback is game-controlled, not a media element.
    assert 'params.get("replay")' in javascript
    assert 'params.get("chrome") === "off"' in javascript
    assert 'event.data.type !== "coworld-replay"' in javascript
    assert 'new DecompressionStream("deflate")' in javascript
    assert "frame.agent_deltas.upsert" in javascript
    assert "frameIndex >= replay.frames.length ? 0" in javascript
    assert 'id="play"' in html
    assert 'id="timeline"' in html
    assert 'id="histograms"' in html


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
    assert sorted(path.name for path in output.iterdir()) == ["app.js", "index.html", "styles.css"]
    assert (output / "index.html").read_bytes() == (VIEWER / "index.html").read_bytes()
