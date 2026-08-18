from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "ruleset-studio" / "src"


class ResourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.resources: list[str] = []
        self.inline_scripts = 0
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            self._in_script = True
            if values.get("src"):
                self.resources.append(values["src"] or "")
        if tag in {"link", "img", "iframe"}:
            resource = values.get("href") or values.get("src")
            if resource:
                self.resources.append(resource)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script and data.strip():
            self.inline_scripts += 1


def test_studio_static_surface_has_no_external_resources() -> None:
    parser = ResourceParser()
    parser.feed((STUDIO / "index.html").read_text(encoding="utf-8"))

    assert parser.inline_scripts == 0
    assert parser.resources == [
        "style.css",
        "vendor/blockly/blockly.min.js",
        "/link-client.js",
        "studio.js",
    ]
    assert (STUDIO / "play.js").is_file()
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in STUDIO.rglob("*")
        if path.is_file() and path.suffix in {".html", ".css", ".js"}
    )
    assert not re.search(r'(?:src|href)=["\']https?://', combined, re.IGNORECASE)
    assert "fonts.googleapis.com" not in combined
    assert "fonts.gstatic.com" not in combined


def test_play_markup_and_controller_pin_the_handoff_contract() -> None:
    html = (STUDIO / "index.html").read_text(encoding="utf-8")
    script = (STUDIO / "studio.js").read_text(encoding="utf-8")
    play = (STUDIO / "play.js").read_text(encoding="utf-8")
    style = (STUDIO / "style.css").read_text(encoding="utf-8")

    for control in (
        'id="play-button"',
        'aria-label="Run settings"',
        'id="editor-button"',
        'id="replay-frame"',
        'id="expired-run"',
    ):
        assert control in html
    assert 'id="blockly"' in html
    assert "compilation.value" in script
    assert "validatedGeneration === validationGeneration" in script
    assert "canonical = false" in play
    assert "canonical: true" in play
    assert "BigInt(this.state.fixedSeed)" in play
    assert "Number(this.state.fixedSeed)" not in play
    assert ".playing #inspector" in style
    assert not re.search(r"#[0]{3}(?:[0]{3})?\b|#[f]{3}(?:[f]{3})?\b", style, re.IGNORECASE)
