#!/usr/bin/env python3
"""Materialize a v3 replay as whole v1 broadcast frames.

    python tools/v3_to_v1_replay.py build/local/replay.bin build/local/replay.v1.json
"""

from __future__ import annotations

import json
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coworld.v1_frames import convert_document  # noqa: E402


def load_v3(path: Path) -> dict:
    document = json.loads(zlib.decompress(path.read_bytes()))
    if document.get("format") != "sugarscape.replay.v3":
        raise SystemExit(f"not a v3 replay: {document.get('format')!r}")
    return document


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    source, destination = Path(sys.argv[1]), Path(sys.argv[2])
    converted = convert_document(load_v3(source))
    destination.write_text(json.dumps(converted), encoding="utf-8")
    frames = converted["frames"]
    print(
        f"{source} -> {destination}\n"
        f"  {len(frames)} frames, t0..t{frames[-1]['timestep']}, "
        f"{frames[0]['width']}x{frames[0]['height']}, "
        f"{len(frames[0]['slots'])} seat(s), "
        f"maxSugar {frames[0]['environmentMaxSugar']} maxSpice {frames[0]['environmentMaxSpice']}"
    )


if __name__ == "__main__":
    main()
