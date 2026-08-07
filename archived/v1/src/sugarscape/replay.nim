# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
import std/[json, strutils]

import zippy

const
  ReplayFormatV1* = "sugarscape.replay.v1"
  ReplayFormatV2* = "sugarscape.replay.v2"
  FrameFormat* = "sugarscape.frame.v1"
  ReplayKeyframeInterval* = 100
  AgentFields* = [
    "id",
    "cell",
    "slot",
    "decisionModel",
    "age",
    "sugar",
    "spice",
    "depressed",
    "sick",
    "sugarMetabolism",
    "spiceMetabolism",
    "movement",
    "vision",
    "race",
    "sex",
    "tribe",
  ]

proc compactAgents(agents: JsonNode): JsonNode =
  result = newJArray()
  for agent in agents:
    var row = newJArray()
    for field in AgentFields:
      row.add(agent[field].copy())
    result.add(row)

proc statisticFields(frame: JsonNode): seq[string] =
  for name, _ in frame["stats"]:
    result.add(name)

proc compactStatistics(stats: JsonNode, fields: openArray[string]): JsonNode =
  result = newJArray()
  for field in fields:
    result.add(stats[field].copy())

proc compactCells(
    cells, previousCells: JsonNode,
    keyframe: bool,
): JsonNode =
  if keyframe:
    return cells.copy()

  result = newJArray()
  for index in 0 ..< cells.len:
    if cells[index] == previousCells[index]:
      continue
    var change = newJArray()
    change.add(newJInt(index))
    for value in cells[index]:
      change.add(value.copy())
    result.add(change)

proc replayDocument*(config, frames: JsonNode): JsonNode =
  if frames.kind != JArray or frames.len == 0:
    raise newException(ValueError, "replay requires at least one frame")

  let
    first = frames[0]
    statsFields = first.statisticFields()
  var
    fieldNodes = newJArray()
    statisticNodes = newJArray()
    compactFrames = newJArray()
    previousCells = first["cells"]

  for field in AgentFields:
    fieldNodes.add(newJString(field))
  for field in statsFields:
    statisticNodes.add(newJString(field))

  for index in 0 ..< frames.len:
    let frame = frames[index]
    let keyframe = index mod ReplayKeyframeInterval == 0
    var row = newJArray()
    row.add(frame["timestep"].copy())
    row.add(newJInt(if keyframe: 1 else: 0))
    row.add(compactCells(frame["cells"], previousCells, keyframe))
    row.add(compactAgents(frame["agents"]))
    row.add(frame["links"].copy())
    row.add(compactStatistics(frame["stats"], statsFields))
    compactFrames.add(row)
    previousCells = frame["cells"]

  %*{
    "format": ReplayFormatV2,
    "config": config.copy(),
    "width": first["width"].copy(),
    "height": first["height"].copy(),
    "slots": first["slots"].copy(),
    "agentFields": fieldNodes,
    "statFields": statisticNodes,
    "keyframeInterval": ReplayKeyframeInterval,
    "frames": compactFrames,
  }

proc encodeReplayArtifact*(config, frames: JsonNode): string =
  compress($replayDocument(config, frames), BestCompression, dfZlib)

proc decodeReplayArtifact*(data: string): JsonNode =
  var text = data
  if text.strip(leading = true, trailing = false).startsWith("{"):
    discard
  else:
    try:
      text = uncompress(data, dfDetect)
    except ZippyError as error:
      raise newException(ValueError, "invalid compressed replay: " & error.msg)

  try:
    result = parseJson(text)
  except JsonParsingError as error:
    raise newException(ValueError, "invalid replay JSON: " & error.msg)

  if result.kind != JObject or not result.hasKey("format") or
      result["format"].kind != JString or
      result["format"].getStr() notin [ReplayFormatV1, ReplayFormatV2]:
    raise newException(ValueError, "unsupported Sugarscape replay format")
  if not result.hasKey("frames") or result["frames"].kind != JArray:
    raise newException(ValueError, "replay requires a frames array")

proc stringFields(node: JsonNode, name: string): seq[string] =
  if not node.hasKey(name) or node[name].kind != JArray:
    raise newException(ValueError, "replay requires " & name)
  for value in node[name]:
    if value.kind != JString:
      raise newException(ValueError, name & " must contain strings")
    result.add(value.getStr())

proc expandedReplayFrames*(replay: JsonNode): JsonNode =
  if replay["format"].getStr() == ReplayFormatV1:
    return replay["frames"].copy()

  let
    agentFields = replay.stringFields("agentFields")
    statFields = replay.stringFields("statFields")
  var previousCells = newJArray()
  result = newJArray()

  for frameIndex in 0 ..< replay["frames"].len:
    let row = replay["frames"][frameIndex]
    if row.kind != JArray or row.len != 6:
      raise newException(ValueError, "invalid compact replay frame")
    let
      keyframe = row[1].getInt() == 1
      encodedCells = row[2]
    var cells: JsonNode
    if keyframe:
      cells = encodedCells.copy()
    else:
      if frameIndex == 0 or previousCells.len == 0:
        raise newException(ValueError, "compact replay must begin with a keyframe")
      cells = previousCells.copy()
      for change in encodedCells:
        if change.kind != JArray or change.len != 4:
          raise newException(ValueError, "invalid compact replay cell delta")
        let index = change[0].getInt()
        if index < 0 or index >= cells.len:
          raise newException(ValueError, "compact replay cell index is out of range")
        var cell = newJArray()
        for valueIndex in 1 .. 3:
          cell.add(change[valueIndex].copy())
        cells.elems[index] = cell

    var agents = newJArray()
    for encodedAgent in row[3]:
      if encodedAgent.kind != JArray or encodedAgent.len != agentFields.len:
        raise newException(ValueError, "invalid compact replay agent")
      var agent = newJObject()
      for index, field in agentFields:
        agent[field] = encodedAgent[index].copy()
      agents.add(agent)

    if row[5].kind != JArray or row[5].len != statFields.len:
      raise newException(ValueError, "invalid compact replay statistics")
    var stats = newJObject()
    for index, field in statFields:
      stats[field] = row[5][index].copy()

    result.add(%*{
      "format": FrameFormat,
      "timestep": row[0].copy(),
      "width": replay["width"].copy(),
      "height": replay["height"].copy(),
      "cells": cells,
      "agents": agents,
      "links": row[4].copy(),
      "slots": replay["slots"].copy(),
      "stats": stats,
    })
    previousCells = cells
