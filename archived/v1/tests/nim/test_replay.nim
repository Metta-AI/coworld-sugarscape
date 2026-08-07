# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
import std/[json, unittest]

import sugarscape/replay

proc frame(timestep, firstSugar, secondSugar: int): JsonNode =
  %*{
    "format": FrameFormat,
    "timestep": timestep,
    "width": 2,
    "height": 1,
    "cells": [[firstSugar, 0, 0], [secondSugar, 1, 0]],
    "agents": [
      {
        "id": 0,
        "cell": timestep mod 2,
        "slot": 0,
        "decisionModel": "none",
        "age": timestep,
        "sugar": 10 - timestep,
        "spice": 4,
        "depressed": false,
        "sick": false,
        "sugarMetabolism": 1,
        "spiceMetabolism": 1,
        "movement": 2,
        "vision": 2,
        "race": -1,
        "sex": "female",
        "tribe": 0,
      },
    ],
    "links": [],
    "slots": [
      {"name": "Player 1", "agentIds": [0], "decisionModels": []},
    ],
    "stats": {"population": 1, "meanWealth": 14 - timestep},
  }

suite "Sugarscape replay artifacts":
  test "v2 is deterministic, compressed, and expands to presentation frames":
    let
      config = %*{"seed": 12345, "timesteps": 2}
      frames = %*[frame(0, 4, 3), frame(1, 3, 3), frame(2, 3, 2)]
      first = encodeReplayArtifact(config, frames)
      second = encodeReplayArtifact(config, frames)
      replay = decodeReplayArtifact(first)

    check first == second
    check first.len < ($(%*{
      "format": ReplayFormatV1,
      "config": config,
      "frames": frames,
    })).len
    check replay["format"].getStr() == ReplayFormatV2
    check replay["frames"].len == 3
    check replay["frames"][0][1].getInt() == 1
    check replay["frames"][1][1].getInt() == 0
    check replay["frames"][1][2] == %*[[0, 3, 0, 0]]
    check expandedReplayFrames(replay) == frames

  test "historical uncompressed v1 artifacts remain readable":
    let
      frames = %*[frame(0, 4, 3)]
      legacy = $ %*{
        "format": ReplayFormatV1,
        "config": {"seed": 12345},
        "frames": frames,
      }
      replay = decodeReplayArtifact(legacy)

    check expandedReplayFrames(replay) == frames

  test "malformed compressed data fails visibly":
    expect ValueError:
      discard decodeReplayArtifact("not a replay")
