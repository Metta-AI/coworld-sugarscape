#!/usr/bin/env python3
"""Local dev server for the static replay viewer.

Serves the repository so `replay-viewer/` can load a recorded episode straight
off disk, and keeps the URLs people already have in tabs and notes working.

`/client/replay` was the v1 Nim server's viewer path. v3's viewer is a static
bundle at a different path, so that URL would otherwise 404 for anyone who had
it open or bookmarked — including the team screen. It redirects here instead.

    python -m tools.serve_replay_viewer [port] [replay-path]

Dev only. Nothing in the shipped bundle depends on this; `tools/build_replay_viewer.sh`
is still what produces the deployable viewer.
"""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 18402
DEFAULT_REPLAY = "/build/local/replay.bin"

# Every path that should land on the viewer. The v1 spellings are here so old
# links keep resolving rather than dead-ending on a stack of 404 text.
VIEWER_ALIASES = frozenset({
    "/",
    "/client",
    "/client/",
    "/client/replay",
    "/client/replay/",
    "/replay",
    "/replay/",
})


class ReplayViewerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, replay: str, **kwargs):
        self._replay = replay
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self.path.split("?", 1)[0] in VIEWER_ALIASES:
            self.send_response(302)
            self.send_header(
                "Location", f"/replay-viewer/index.html?replay={self._replay}"
            )
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, format: str, *args: object) -> None:
        # One line per request, without the stdlib's duplicated timestamp noise.
        sys.stderr.write(f"{self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    replay = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_REPLAY
    handler = partial(ReplayViewerHandler, replay=replay)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"replay viewer on http://127.0.0.1:{port}/client/replay (replay {replay})")
    server.serve_forever()


if __name__ == "__main__":
    main()
