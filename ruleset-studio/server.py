#!/usr/bin/env python3
"""Local API for Ruleset Studio.

The ux.surface link server owns static files and agent chat. This loopback-only
server owns the mechanical operations that must use repository truth: SugarLang
validation, ruleset files, and effective scenario context.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
FILENAME = re.compile(r"[A-Za-z0-9._-]+\.json\Z")
MAX_REQUEST_BYTES = 1024 * 1024
TRAIT_FACTORS = {
    "aggression": "agentAggressionFactor",
    "trade": "agentTradeFactor",
    "lending": "agentLendingFactor",
    "fertility": "agentFertilityFactor",
}


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


@dataclass(frozen=True)
class StudioPaths:
    rulesets: Path
    config: Path
    dtl_config: Path
    manifest: Path

    @classmethod
    def repository(cls, root: Path = REPO_ROOT) -> StudioPaths:
        return cls(
            rulesets=root / "rulesets",
            config=root / "config.json",
            dtl_config=root / "src" / "sugarscape" / "config.json",
            manifest=root / "coworld_manifest.json",
        )


def _issues(result: Any) -> list[dict[str, str]]:
    return [{"path": issue.path, "message": issue.message} for issue in result.errors]


def _validation_payload(result: Any) -> dict[str, object]:
    return {
        "valid": result.valid,
        "normalized": result.normalized,
        "errors": _issues(result),
        "node_count": result.node_count,
        "byte_count": result.byte_count,
    }


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _effective_contexts(paths: StudioPaths) -> dict[str, object]:
    dtl_document = _read_json(paths.dtl_config)
    assert isinstance(dtl_document, dict)
    defaults = dtl_document["sugarscapeOptions"]
    root_config = _read_json(paths.config)
    manifest = _read_json(paths.manifest)
    assert isinstance(defaults, dict) and isinstance(root_config, dict) and isinstance(manifest, dict)

    contexts = [
        _context_record(
            "default",
            "Local config.json",
            {**defaults, **root_config},
            root_config.get("targets", []),
            "Default local configuration",
        )
    ]
    for variant in manifest.get("variants", []):
        if not isinstance(variant, dict):
            continue
        variant_id = str(variant.get("id", "variant"))
        label = str(variant.get("name", variant_id))
        game_config = variant.get("game_config", {})
        if not isinstance(game_config, dict):
            continue
        # Hosted episodes resolve variant configs over the pinned DTL
        # defaults only; the local config.json is the dev world and must not
        # leak its overrides (notably trait_ranges) into variant contexts.
        variant_config = {**defaults, **game_config}
        pool = game_config.get("scenario_pool")
        if isinstance(pool, list):
            for scenario in pool:
                if not isinstance(scenario, dict):
                    continue
                scenario_id = str(scenario.get("id", "scenario"))
                overrides = scenario.get("config_overrides", {})
                if not isinstance(overrides, dict):
                    overrides = {}
                contexts.append(
                    _context_record(
                        f"{variant_id}:{scenario_id}",
                        f"{label} · {scenario_id}",
                        {**variant_config, **overrides},
                        scenario.get("targets", variant_config.get("targets", [])),
                        str(scenario.get("description", "")),
                    )
                )
        else:
            contexts.append(
                _context_record(
                    variant_id,
                    label,
                    variant_config,
                    variant_config.get("targets", []),
                    str(variant.get("description", "")),
                )
            )
    return {"default": "default", "contexts": contexts}


def _context_record(
    context_id: str,
    label: str,
    config: dict[str, object],
    targets: object,
    description: str,
) -> dict[str, object]:
    trait_ranges = config.get("trait_ranges")
    if not isinstance(trait_ranges, dict):
        trait_ranges = {name: [0.0, 1.0] for name in TRAIT_FACTORS}
    return {
        "id": context_id,
        "label": label,
        "description": description,
        "targets": targets if isinstance(targets, list) else [],
        "trait_ranges": {name: trait_ranges[name] for name in TRAIT_FACTORS},
        "dtl_factor_ranges": {name: config[setting] for name, setting in TRAIT_FACTORS.items()},
    }


class RulesetStudioHandler(BaseHTTPRequestHandler):
    server_version = "RulesetStudio/1"

    def __init__(
        self,
        *args: object,
        paths: StudioPaths,
        allowed_origin: str,
        catalog: object,
        coordinator: object | None,
        **kwargs: object,
    ):
        self.paths = paths
        self.allowed_origin = allowed_origin
        self.catalog = catalog
        self.coordinator = coordinator
        super().__init__(*args, **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.allowed_origin)
        self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._origin_allowed():
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._origin_allowed():
            return
        path, _query = self._request_target()
        if path == "/api/rulesets":
            return self._list_rulesets()
        if path == "/api/context":
            return self._json(HTTPStatus.OK, _effective_contexts(self.paths))
        if path == "/api/scenarios":
            return self._json(HTTPStatus.OK, self.catalog.public_dict())
        if path.startswith("/api/run/") and self.coordinator is not None:
            from coworld.studio_runs import StudioRunNotFound

            try:
                return self._json(
                    HTTPStatus.OK,
                    self.coordinator.status(path.removeprefix("/api/run/")),
                )
            except StudioRunNotFound:
                return self._error(HTTPStatus.NOT_FOUND, "run not found")
        name = self._ruleset_name(path)
        if name is not None:
            destination = self.paths.rulesets / name
            if not destination.is_file():
                return self._error(HTTPStatus.NOT_FOUND, "ruleset not found")
            data = destination.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._error(HTTPStatus.NOT_FOUND, "route not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._origin_allowed():
            return
        path, _query = self._request_target()
        if path == "/api/run" and self.coordinator is not None:
            return self._post_run()
        if path != "/api/validate":
            return self._error(HTTPStatus.NOT_FOUND, "route not found")
        payload = self._read_body()
        if payload is None:
            return
        from coworld.ruleset import parse_ruleset

        self._json(HTTPStatus.OK, _validation_payload(parse_ruleset(payload)))

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._origin_allowed():
            return
        path, query = self._request_target()
        if path == "/api/displayed-run" and self.coordinator is not None:
            return self._put_displayed_run()
        name = self._ruleset_name(path)
        if name is None:
            return self._error(HTTPStatus.BAD_REQUEST, "invalid ruleset filename")
        payload = self._read_body()
        if payload is None:
            return
        from coworld.ruleset import parse_ruleset

        result = parse_ruleset(payload)
        force = query == {"force": ["1"]}
        response = _validation_payload(result)
        if not result.valid and not force:
            response["written"] = False
            return self._json(HTTPStatus.UNPROCESSABLE_ENTITY, response)
        destination = self.paths.rulesets / name
        self.paths.rulesets.mkdir(parents=True, exist_ok=True)
        _atomic_write(destination, payload)
        response.update({"written": True, "forced": not result.valid})
        self._json(HTTPStatus.OK, response)

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._origin_allowed():
            return
        path, _query = self._request_target()
        if path.startswith("/api/run/") and self.coordinator is not None:
            from coworld.studio_runs import StudioRunNotFound

            try:
                status = self.coordinator.cancel(path.removeprefix("/api/run/"))
            except StudioRunNotFound:
                return self._error(HTTPStatus.NOT_FOUND, "run not found")
            return self._json(HTTPStatus.OK, status)
        self._error(HTTPStatus.NOT_FOUND, "route not found")

    def _post_run(self) -> None:
        body = self._read_json_body()
        if body is None:
            return
        allowed = {"ruleset", "variant", "mode", "scenario", "seed", "timesteps"}
        if set(body) - allowed or not {"ruleset", "variant", "mode"} <= set(body):
            return self._error(HTTPStatus.BAD_REQUEST, "invalid run request fields")
        if not all(isinstance(body[name], str) for name in ("variant", "mode")):
            return self._error(HTTPStatus.BAD_REQUEST, "variant and mode must be strings")
        scenario = body.get("scenario")
        seed = body.get("seed")
        timesteps = body.get("timesteps")
        if scenario is not None and not isinstance(scenario, str):
            return self._error(HTTPStatus.BAD_REQUEST, "scenario must be a string or null")
        if seed is not None and not isinstance(seed, str):
            return self._error(HTTPStatus.BAD_REQUEST, "seed must be a string or null")
        if timesteps is not None and (
            isinstance(timesteps, bool) or not isinstance(timesteps, int)
        ):
            return self._error(HTTPStatus.BAD_REQUEST, "timesteps must be an integer or null")

        from coworld.studio_runs import (
            RunBusy,
            RunServerStopping,
            StudioCompileError,
        )

        try:
            started = self.coordinator.start(
                self.catalog,
                ruleset=body["ruleset"],
                variant_id=body["variant"],
                mode=body["mode"],
                scenario_id=scenario,
                seed=seed,
                timesteps=timesteps,
            )
        except StudioCompileError as error:
            return self._json(
                HTTPStatus.BAD_REQUEST,
                {"error": "compile failed", "validation": error.validation},
            )
        except ValueError as error:
            return self._error(HTTPStatus.BAD_REQUEST, f"invalid run request: {error}")
        except RunBusy:
            return self._error(HTTPStatus.CONFLICT, "a studio run is already in progress")
        except RunServerStopping:
            return self._error(HTTPStatus.SERVICE_UNAVAILABLE, "studio run service is stopping")
        except Exception:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "run could not be started")
        self._json(HTTPStatus.ACCEPTED, started)

    def _put_displayed_run(self) -> None:
        body = self._read_json_body()
        if body is None:
            return
        if set(body) != {"run_id"} or (
            body["run_id"] is not None and not isinstance(body["run_id"], str)
        ):
            return self._error(HTTPStatus.BAD_REQUEST, "run_id must be a string or null")

        from coworld.studio_runs import StudioRunNotFound

        try:
            self.coordinator.set_displayed(body["run_id"])
        except StudioRunNotFound:
            return self._error(HTTPStatus.NOT_FOUND, "run not found")
        self._json(HTTPStatus.OK, {"displayed_run": body["run_id"]})

    def _read_json_body(self) -> dict[str, object] | None:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Content-Type must be application/json")
            return None
        payload = self._read_body()
        if payload is None:
            return None
        try:
            value = json.loads(
                payload,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._error(HTTPStatus.BAD_REQUEST, f"invalid JSON body: {error}")
            return None
        if not isinstance(value, dict):
            self._error(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
            return None
        return value

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None or origin == self.allowed_origin:
            return True
        self._error(HTTPStatus.FORBIDDEN, "origin not allowed")
        return False

    def _request_target(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urlsplit(self.path)
        return unquote(parsed.path), parse_qs(parsed.query, keep_blank_values=True)

    def _ruleset_name(self, path: str) -> str | None:
        prefix = "/api/rulesets/"
        if not path.startswith(prefix):
            return None
        name = path[len(prefix):]
        if not FILENAME.fullmatch(name):
            return None
        destination = (self.paths.rulesets / name).resolve()
        if destination.parent != self.paths.rulesets.resolve():
            return None
        return name

    def _read_body(self) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
            return None
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
            return None
        return self.rfile.read(length)

    def _list_rulesets(self) -> None:
        from coworld.ruleset import parse_ruleset

        self.paths.rulesets.mkdir(parents=True, exist_ok=True)
        entries = []
        for path in self.paths.rulesets.glob("*.json"):
            if not path.is_file() or not FILENAME.fullmatch(path.name):
                continue
            result = parse_ruleset(path.read_bytes())
            entries.append(
                {
                    "name": path.name,
                    "mtime": path.stat().st_mtime,
                    **_validation_payload(result),
                }
            )
        entries.sort(key=lambda entry: (-float(entry["mtime"]), str(entry["name"])))
        self._json(HTTPStatus.OK, {"rulesets": entries})

    def _json(self, status: HTTPStatus, value: object) -> None:
        body = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json(status, {"error": message})

    def log_message(self, format: str, *args: object) -> None:
        status = args[1] if len(args) > 1 else ""
        print(f"{self.command} {self.path} -> {status}")


def _atomic_write(destination: Path, payload: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as file:
            temporary = Path(file.name)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def create_server(
    host: str,
    port: int,
    *,
    paths: StudioPaths | None = None,
    allowed_origin: str = "http://localhost:4322",
    catalog: object | None = None,
    coordinator: object | None = None,
) -> ThreadingHTTPServer:
    if catalog is None:
        from coworld.studio import StudioVariantCatalog

        catalog = StudioVariantCatalog.load()
    handler = partial(
        RulesetStudioHandler,
        paths=paths or StudioPaths.repository(),
        allowed_origin=allowed_origin,
        catalog=catalog,
        coordinator=coordinator,
    )
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ruleset Studio mechanical API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4323)
    parser.add_argument("--origin", default="http://localhost:4322")
    parser.add_argument("--rulesets-dir", type=Path)
    arguments = parser.parse_args()
    paths = StudioPaths.repository()
    if arguments.rulesets_dir is not None:
        paths = StudioPaths(arguments.rulesets_dir.resolve(), paths.config, paths.dtl_config, paths.manifest)
    server = create_server(arguments.host, arguments.port, paths=paths, allowed_origin=arguments.origin)
    host, port = server.server_address
    print(f"Ruleset Studio API -> http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
