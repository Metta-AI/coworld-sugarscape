from __future__ import annotations

from contextlib import contextmanager
from http.client import HTTPConnection
import json
from pathlib import Path
import threading
from typing import Iterator
from urllib.parse import quote

from ruleset_studio_import import load_studio_server
from tools import ruleset_studio as launcher


ROOT = Path(__file__).resolve().parents[1]
studio_server = load_studio_server(ROOT / "ruleset-studio" / "server.py")
StudioPaths = studio_server.StudioPaths


@contextmanager
def running_server(tmp_path: Path) -> Iterator[tuple[str, int, Path]]:
    rulesets = tmp_path / "rulesets"
    rulesets.mkdir()
    paths = StudioPaths(
        rulesets,
        ROOT / "config.json",
        ROOT / "src/sugarscape/config.json",
        ROOT / "coworld_manifest.json",
    )
    server = studio_server.create_server("127.0.0.1", 0, paths=paths, allowed_origin="http://localhost:9876")
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server.server_address[0], server.server_address[1], rulesets
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(
    address: tuple[str, int],
    method: str,
    path: str,
    body: bytes | None = None,
    *,
    origin: str | None = "http://localhost:9876",
) -> tuple[int, dict[str, str], bytes]:
    connection = HTTPConnection(*address, timeout=2)
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    if body is not None:
        headers["Content-Length"] = str(len(body))
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def decoded(response: tuple[int, dict[str, str], bytes]) -> object:
    return json.loads(response[2])


def test_ruleset_routes_preserve_exact_valid_bytes_and_list_newest_first(tmp_path: Path) -> None:
    with running_server(tmp_path) as (host, port, rulesets):
        address = host, port
        first = b'{"version":1,"movement":[{"score":["get","cell.welfare"]}]}\n'
        status, headers, body = request(address, "PUT", "/api/rulesets/first.json", first)
        assert status == 200, body
        assert headers["Access-Control-Allow-Origin"] == "http://localhost:9876"
        assert (rulesets / "first.json").read_bytes() == first

        second = b"null\n"
        assert request(address, "PUT", "/api/rulesets/second.json", second)[0] == 200
        (rulesets / "second.json").touch()

        status, _headers, body = request(address, "GET", "/api/rulesets")
        assert status == 200
        entries = json.loads(body)["rulesets"]
        assert [entry["name"] for entry in entries] == ["second.json", "first.json"]
        assert all(entry["valid"] for entry in entries)

        loaded = request(address, "GET", "/api/rulesets/first.json")
        assert loaded[0] == 200
        assert loaded[2] == first


def test_invalid_save_requires_force_and_never_clobbers_silently(tmp_path: Path) -> None:
    with running_server(tmp_path) as (host, port, rulesets):
        address = host, port
        destination = rulesets / "candidate.json"
        destination.write_bytes(b"null\n")
        invalid = b'{"version":1,"movement":[{"score":["bogus",1]}]}\n'

        refused = request(address, "PUT", "/api/rulesets/candidate.json", invalid)
        assert refused[0] == 422
        payload = decoded(refused)
        assert payload["written"] is False
        assert payload["errors"][0]["path"] == "$.movement[0].score[0]"
        assert destination.read_bytes() == b"null\n"

        forced = request(address, "PUT", "/api/rulesets/candidate.json?force=1", invalid)
        assert forced[0] == 200
        payload = decoded(forced)
        assert payload["forced"] is True
        assert payload["valid"] is False
        assert destination.read_bytes() == invalid
        assert not list(rulesets.glob(".candidate.json.*"))


def test_validation_returns_authoritative_paths_and_raw_byte_count(tmp_path: Path) -> None:
    with running_server(tmp_path) as (host, port, _rulesets):
        candidate = b'{"version":1, "movement":[{"if":["get","nope"]}]}   '
        response = request((host, port), "POST", "/api/validate", candidate)
        assert response[0] == 200
        payload = decoded(response)
        assert payload["byte_count"] == len(candidate)
        paths = {error["path"] for error in payload["errors"]}
        assert "$.movement[0].score" in paths
        assert "$.movement[0].if[1]" in paths
        assert "$.movement[-1]" in paths


def test_filename_allowlist_rejects_traversal_and_extra_segments(tmp_path: Path) -> None:
    attacks = [
        "/api/rulesets/../escape.json",
        f"/api/rulesets/{quote('../escape.json', safe='')}",
        "/api/rulesets/%2Ftmp%2Fescape.json",
        "/api/rulesets/back%5Cslash.json",
        "/api/rulesets/not-json.txt",
        "/api/rulesets/good.json/extra",
    ]
    with running_server(tmp_path) as (host, port, rulesets):
        for attack in attacks:
            status = request((host, port), "PUT", attack, b"null\n")[0]
            assert status in {400, 404}, (attack, status)
        assert list(rulesets.iterdir()) == []


def test_context_uses_effective_runtime_defaults_and_scenario_overrides(tmp_path: Path) -> None:
    with running_server(tmp_path) as (host, port, _rulesets):
        response = request((host, port), "GET", "/api/context")
        assert response[0] == 200
        payload = decoded(response)
        contexts = {context["id"]: context for context in payload["contexts"]}
        assert contexts["default"]["dtl_factor_ranges"] == {
            "aggression": [1, 1],
            "trade": [1, 1],
            "lending": [1, 1],
            "fertility": [1, 1],
        }
        twin_peaks = contexts["solo-ladder:wealth-skewed.twin-peaks"]
        assert twin_peaks["dtl_factor_ranges"]["trade"] == [0, 0]
        assert twin_peaks["trait_ranges"]["trade"] == [0, 0]
        trade = contexts["solo-ladder:price.overlapping-peaks"]
        assert trade["dtl_factor_ranges"]["trade"] == [1, 1]
        assert trade["trait_ranges"]["trade"] == [0, 1]


def test_scenarios_expose_play_choices_with_matching_context_ids(tmp_path: Path) -> None:
    with running_server(tmp_path) as (host, port, _rulesets):
        response = request((host, port), "GET", "/api/scenarios")

    assert response[0] == 200
    payload = decoded(response)
    variants = {variant["id"]: variant for variant in payload["variants"]}
    assert "duel-4seat" not in variants
    assert variants["commonwealth"]["kind"] == "fixed"
    assert variants["commonwealth"]["context_id"] == "commonwealth"
    assert all(
        scenario["context_id"] == f"solo-ladder:{scenario['id']}"
        for scenario in variants["solo-ladder"]["scenarios"]
    )
    assert '"tokens"' not in json.dumps(payload)


def test_cors_is_pinned_to_the_link_server_origin(tmp_path: Path) -> None:
    with running_server(tmp_path) as (host, port, _rulesets):
        denied = request((host, port), "GET", "/api/context", origin="http://evil.test")
        assert denied[0] == 403
        allowed = request((host, port), "OPTIONS", "/api/validate")
        assert allowed[0] == 204
        assert allowed[1]["Access-Control-Allow-Origin"] == "http://localhost:9876"
        assert allowed[1]["Access-Control-Allow-Methods"] == (
            "GET, POST, PUT, DELETE, OPTIONS"
        )


def test_vendored_blockly_and_starter_are_offline_and_pinned() -> None:
    vendor = ROOT / "ruleset-studio/src/vendor/blockly"
    version = (vendor / "VERSION").read_text(encoding="utf-8")
    license_text = (vendor / "LICENSE").read_text(encoding="utf-8")
    runtime = (vendor / "blockly.min.js").read_text(encoding="utf-8")
    assert "blockly 13.2.0" in version
    assert "Apache License" in license_text
    assert "13.2.0" in runtime
    assert "https://unpkg.com" not in runtime
    assert "https://cdn" not in runtime

    from coworld.ruleset import parse_ruleset

    starter = (ROOT / "rulesets/worked-example.json").read_bytes()
    assert parse_ruleset(starter).valid


def test_launcher_discovers_the_read_only_metta_bridge_and_prints_watch_command() -> None:
    node, link_server, link_bridge = launcher.discover(launcher.DEFAULT_METTA_ROOT)
    assert Path(node).is_file()
    assert link_server.name == "link-server.mjs"
    assert link_bridge.name == "link-bridge.mjs"
    command = launcher.bridge_command(node, link_bridge, 4567)
    assert command == f"LINK_PORT=4567 {node} {link_bridge} watch"


def test_launcher_missing_metta_error_names_both_expected_files(tmp_path: Path) -> None:
    try:
        launcher.discover(tmp_path)
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError("missing Metta bridge should fail discovery")
    assert str(tmp_path / launcher.LINK_APP / "link-server.mjs") in message
    assert str(tmp_path / launcher.LINK_APP / "link-bridge.mjs") in message


def test_launcher_stop_terminates_a_live_child() -> None:
    from subprocess import Popen
    import sys

    child = Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    launcher.stop(child)
    assert child.poll() is not None


def test_studio_docs_and_static_contract_match_the_implemented_phase() -> None:
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    studio_readme = (ROOT / "ruleset-studio/README.md").read_text(encoding="utf-8")
    design = (ROOT / "docs/designs/2026-08-18-ruleset-studio.md").read_text(encoding="utf-8")
    html = (ROOT / "ruleset-studio/src/index.html").read_text(encoding="utf-8")
    script = (ROOT / "ruleset-studio/src/studio.js").read_text(encoding="utf-8")

    assert "ruleset-studio/README.md" in root_readme
    assert ".venv/bin/python -m tools.ruleset_studio" in studio_readme
    assert "phase 1 implemented" in design
    assert "src/vendor/blockly/" in design
    assert ".claude/skills" not in design
    assert '<script src="/link-client.js"></script>' in html
    assert "window.linkApplyPatch" in script
    assert "link.submit" not in script


def test_csp_permits_blockly_runtime_style_injection() -> None:
    # Blockly injects its layout CSS as inline <style> elements at runtime.
    # A style-src without 'unsafe-inline' silently blocks them, which
    # collapses the SVG layout: the toolbox flyout renders as a huge inline
    # strip over the side panel and nothing in it is clickable.
    index = (ROOT / "ruleset-studio/src/index.html").read_text(encoding="utf-8")
    for line in index.splitlines():
        if "Content-Security-Policy" in line and "style-src" in line:
            directives = line.split("style-src", 1)[1].split(";", 1)[0]
            assert "'unsafe-inline'" in directives, (
                "CSP style-src must include 'unsafe-inline' for Blockly's "
                "runtime style injection"
            )
