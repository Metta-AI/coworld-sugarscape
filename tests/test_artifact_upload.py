from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from coworld.server import atomic_write_uri


class _Sink(BaseHTTPRequestHandler):
    """Records PUT bodies; scripted per-path status sequences drive retries."""

    requests: list[tuple[str, bytes, str | None]] = []
    status_script: dict[str, list[int]] = {}

    def do_PUT(self) -> None:  # noqa: N802 - http.server naming
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).requests.append(
            (self.path, body, self.headers.get("Content-Type"))
        )
        script = type(self).status_script.get(self.path)
        status = script.pop(0) if script else 200
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: object) -> None:  # silence test output
        pass


@pytest.fixture()
def sink() -> HTTPServer:
    _Sink.requests = []
    _Sink.status_script = {}
    server = HTTPServer(("127.0.0.1", 0), _Sink)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=5)


def _uri(server: HTTPServer, path: str) -> str:
    return f"http://127.0.0.1:{server.server_port}{path}"


def test_http_upload_puts_bytes_with_content_type(sink: HTTPServer) -> None:
    atomic_write_uri(_uri(sink, "/results.json"), b'{"scores": [1.0]}')
    assert _Sink.requests == [
        ("/results.json", b'{"scores": [1.0]}', "application/octet-stream")
    ]


def test_http_upload_retries_transient_5xx_then_succeeds(sink: HTTPServer) -> None:
    _Sink.status_script["/replay.bin"] = [503, 502]
    atomic_write_uri(_uri(sink, "/replay.bin"), b"replay-bytes", retry_delay_seconds=0.01)
    assert [entry[0] for entry in _Sink.requests] == ["/replay.bin"] * 3
    assert _Sink.requests[-1][1] == b"replay-bytes"


def test_http_upload_fails_fast_on_4xx(sink: HTTPServer) -> None:
    _Sink.status_script["/gone"] = [404]
    with pytest.raises(RuntimeError, match="404"):
        atomic_write_uri(_uri(sink, "/gone"), b"x", retry_delay_seconds=0.01)
    assert len(_Sink.requests) == 1  # no retry on client errors


def test_http_upload_exhausts_retries_with_clear_error(sink: HTTPServer) -> None:
    _Sink.status_script["/down"] = [500, 500, 500, 500]
    with pytest.raises(RuntimeError, match="after 4 attempts"):
        atomic_write_uri(_uri(sink, "/down"), b"x", retry_delay_seconds=0.01)
    assert len(_Sink.requests) == 4
