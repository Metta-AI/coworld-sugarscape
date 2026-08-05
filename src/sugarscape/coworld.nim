import
  std/[json, locks, monotimes, os, strutils, tables, times],
  bitworld/runtime,
  mummy,
  ./agents,
  ./configuration,
  ./simulation

const
  FrameHistoryLimit = 300
  HealthPath = "/healthz"
  PlayerPath = "/player"
  GlobalPath = "/global"
  ReplayPath = "/replay"
  PlayerClientPaths = ["/client/player", "/clients/player"]
  GlobalClientPaths = ["/client/global", "/clients/global", "/client/replay",
    "/clients/replay"]
  ViewerHtml = staticRead("viewer.html")
  PlayerHtml = staticRead("player.html")

type
  PolicySlot = object
    name: string
    token: string
    agentIds: seq[int]
    decisionModels: seq[string]
    requests: int
    actions: int
    fallbacks: int

  CoworldConfig = object
    decisionTimeoutMs: int
    connectionWaitMs: int
    frameInterval: int
    onePlayerPerAgent: bool
    playerTribes: bool
    slots: seq[PolicySlot]

  PendingRequest = object
    slot: int
    websocket: WebSocket
    candidates: seq[int]

  AppState = object
    lock: Lock
    slots: seq[PolicySlot]
    playerSockets: Table[int, WebSocket]
    socketSlots: Table[WebSocket, int]
    globalSockets: seq[WebSocket]
    actions: Table[int, int]
    pendingRequests: Table[int, PendingRequest]
    frameHistory: seq[string]
    catchupFrames: Table[WebSocket, seq[string]]
    streamId: string
    nextRequestId: int

  ServerThreadArgs = object
    server: ptr Server
    host: string
    port: int

var appState: AppState

proc stringField(node: JsonNode, name, fallback: string): string =
  if node.kind == JObject and node.hasKey(name) and
      node[name].kind == JString:
    node[name].getStr()
  else:
    fallback

proc intField(node: JsonNode, name: string, fallback: int): int =
  if node.kind == JObject and node.hasKey(name) and
      node[name].kind == JInt:
    node[name].getInt()
  else:
    fallback

proc boolField(node: JsonNode, name: string, fallback: bool): bool =
  if node.kind == JObject and node.hasKey(name) and
      node[name].kind == JBool:
    node[name].getBool()
  else:
    fallback

proc readCoworldConfig(raw: JsonNode, normalized: JsonNode): CoworldConfig =
  result.decisionTimeoutMs = max(1, raw.intField("decisionTimeoutMs", 100))
  result.connectionWaitMs = max(0, raw.intField("connectionWaitMs", 5000))
  result.frameInterval = max(1, raw.intField("frameInterval", 1))
  result.onePlayerPerAgent = raw.boolField("onePlayerPerAgent", false)
  result.playerTribes = raw.boolField("playerTribes", false)

  let
    slotNodes =
      if raw.kind == JObject and raw.hasKey("slots") and
          raw["slots"].kind == JArray:
        raw["slots"]
      else:
        newJArray()
    playerNodes =
      if raw.kind == JObject and raw.hasKey("players") and
          raw["players"].kind == JArray:
        raw["players"]
      else:
        newJArray()
    tokenNodes =
      if raw.kind == JObject and raw.hasKey("tokens") and
          raw["tokens"].kind == JArray:
        raw["tokens"]
      else:
        newJArray()
    configuredModels = normalized["agentDecisionModels"]

  if result.onePlayerPerAgent:
    let startingAgents = normalized["startingAgents"].getInt()
    if playerNodes.len != startingAgents:
      raise newException(
        ValueError,
        "onePlayerPerAgent requires one player per starting agent",
      )
    for index in 0 ..< playerNodes.len:
      let node = playerNodes[index]
      var slot = PolicySlot(
        name: node.stringField("name", "Player " & $(index + 1)),
        agentIds: @[index],
      )
      if index < tokenNodes.len and tokenNodes[index].kind == JString:
        slot.token = tokenNodes[index].getStr()
      if slot.token.len == 0:
        raise newException(
          ValueError,
          "player slot " & $index & " requires a nonempty token",
        )
      result.slots.add(slot)
    return

  for index in 0 ..< slotNodes.len:
    let node = slotNodes[index]
    var slot: PolicySlot
    slot.name =
      if index < playerNodes.len:
        playerNodes[index].stringField("name", "population-" & $(index + 1))
      else:
        node.stringField("name", "population-" & $(index + 1))
    if index < tokenNodes.len and tokenNodes[index].kind == JString:
      slot.token = tokenNodes[index].getStr()
    else:
      slot.token = node.stringField("token", "")
    if slot.token.len == 0:
      raise newException(
        ValueError,
        "population slot " & $index & " requires a nonempty token",
      )
    if node.kind == JObject and node.hasKey("decisionModels") and
        node["decisionModels"].kind == JArray:
      for model in node["decisionModels"]:
        if model.kind == JString:
          slot.decisionModels.add(model.getStr())
    elif node.kind == JObject and node.hasKey("decisionModel") and
        node["decisionModel"].kind == JString:
      slot.decisionModels.add(node["decisionModel"].getStr())
    elif index < configuredModels.len:
      slot.decisionModels.add(configuredModels[index].getStr())
    result.slots.add(slot)

proc initAppState(slots: seq[PolicySlot]) =
  initLock(appState.lock)
  appState.slots = slots
  appState.playerSockets = initTable[int, WebSocket]()
  appState.socketSlots = initTable[WebSocket, int]()
  appState.globalSockets = @[]
  appState.actions = initTable[int, int]()
  appState.pendingRequests = initTable[int, PendingRequest]()
  appState.frameHistory = @[]
  appState.catchupFrames = initTable[WebSocket, seq[string]]()
  appState.streamId = $epochTime()
  appState.nextRequestId = 1

proc isWebSocketUpgrade(request: Request): bool =
  request.headers["Sec-WebSocket-Key"].len > 0

proc respondHtml(request: Request, body: string) =
  var headers: HttpHeaders
  headers["Content-Type"] = "text/html; charset=utf-8"
  headers["Cache-Control"] = "no-cache"
  request.respond(200, headers, body)

proc requestedSlot(request: Request): int =
  let text = request.queryParams.getOrDefault("slot", "").strip()
  try:
    result = text.parseInt()
  except ValueError:
    result = -1

proc registerPlayer(request: Request): WebSocket =
  let
    slot = request.requestedSlot()
    token = request.queryParams.getOrDefault("token", "").strip()
  var replacedSocket: WebSocket
  var replaced = false
  {.gcsafe.}:
    withLock appState.lock:
      if slot < 0 or slot >= appState.slots.len or
          (appState.slots[slot].token.len > 0 and
            appState.slots[slot].token != token):
        var headers: HttpHeaders
        headers["Content-Type"] = "text/plain; charset=utf-8"
        request.respond(403, headers, "invalid population slot or token\n")
        return
      result = request.upgradeToWebSocket()
      if slot in appState.playerSockets:
        replacedSocket = appState.playerSockets[slot]
        replaced = true
        appState.socketSlots.del(replacedSocket)
      appState.playerSockets[slot] = result
      appState.socketSlots[result] = slot
  if replaced:
    replacedSocket.close()

proc httpHandler(request: Request) =
  if request.path == HealthPath and request.httpMethod == "GET":
    var headers: HttpHeaders
    headers["Content-Type"] = "text/plain; charset=utf-8"
    headers["Cache-Control"] = "no-cache"
    request.respond(200, headers, "healthy")
  elif request.path == PlayerPath and request.httpMethod == "GET" and
      request.isWebSocketUpgrade():
    discard request.registerPlayer()
  elif request.path in [GlobalPath, ReplayPath] and
      request.httpMethod == "GET" and request.isWebSocketUpgrade():
    let websocket = request.upgradeToWebSocket()
    var history: seq[string]
    {.gcsafe.}:
      withLock appState.lock:
        history = appState.frameHistory & @[]
        appState.catchupFrames[websocket] = @[]
    try:
      while true:
        for frame in history:
          websocket.send(frame, TextMessage)
        {.gcsafe.}:
          withLock appState.lock:
            history = appState.catchupFrames[websocket]
            if history.len == 0:
              appState.catchupFrames.del(websocket)
              appState.globalSockets.add(websocket)
            else:
              appState.catchupFrames[websocket] = @[]
        if history.len == 0:
          break
    except CatchableError:
      {.gcsafe.}:
        withLock appState.lock:
          appState.catchupFrames.del(websocket)
      try:
        websocket.close()
      except CatchableError:
        discard
      return
  elif request.path in PlayerClientPaths and request.httpMethod == "GET":
    request.respondHtml(PlayerHtml)
  elif request.path in GlobalClientPaths and request.httpMethod == "GET":
    request.respondHtml(ViewerHtml)
  else:
    var headers: HttpHeaders
    headers["Content-Type"] = "text/plain; charset=utf-8"
    request.respond(404, headers, "not found\n")

proc removeSocket(websocket: WebSocket) =
  appState.catchupFrames.del(websocket)
  if websocket in appState.socketSlots:
    let slot = appState.socketSlots[websocket]
    appState.socketSlots.del(websocket)
    if slot in appState.playerSockets and
        appState.playerSockets[slot] == websocket:
      appState.playerSockets.del(slot)
  for index in countdown(appState.globalSockets.high, 0):
    if appState.globalSockets[index] == websocket:
      appState.globalSockets.delete(index)

proc websocketHandler(
    websocket: WebSocket,
    event: WebSocketEvent,
    message: Message,
) =
  case event
  of OpenEvent:
    discard
  of MessageEvent:
    if message.kind == Ping:
      websocket.send(message.data, Pong)
    elif message.kind == TextMessage:
      try:
        let action = parseJson(message.data)
        if action.kind != JObject or
            action.stringField("type", "") != "action" or
            not action.hasKey("requestId") or
            action["requestId"].kind != JInt or
            not action.hasKey("cell") or action["cell"].kind != JInt:
          return
        let
          requestId = action["requestId"].getInt()
          cell = action["cell"].getInt()
        {.gcsafe.}:
          withLock appState.lock:
            if requestId in appState.pendingRequests:
              let pending = appState.pendingRequests[requestId]
              var legal = false
              for candidate in pending.candidates:
                if candidate == cell:
                  legal = true
                  break
              if legal and pending.websocket == websocket and
                  websocket in appState.socketSlots and
                  appState.socketSlots[websocket] == pending.slot:
                appState.actions[requestId] = cell
      except JsonParsingError:
        discard
  of ErrorEvent, CloseEvent:
    {.gcsafe.}:
      withLock appState.lock:
        removeSocket(websocket)

proc serverThread(args: ServerThreadArgs) {.thread.} =
  args.server[].serve(Port(args.port), args.host)

proc slotForAgent(slots: openArray[PolicySlot], agent: Agent): int =
  for index, slot in slots:
    if agent.id in slot.agentIds or
        agent.decisionModel in slot.decisionModels:
      return index
  -1

proc assignPlayerTribes(
    sim: var Simulation,
    slots: openArray[PolicySlot],
) =
  var tribePopulations = newSeq[int](slots.len)
  for agent in sim.agentTemplates.mitems:
    let slot = slots.slotForAgent(agent)
    if slot >= 0:
      agent.tribe = slot
  for id in sim.activeAgents:
    let slot = slots.slotForAgent(sim.agents[id])
    if slot >= 0:
      sim.agents[id].tribe = slot
      inc tribePopulations[slot]

  var
    largestTribe = 0
    largestTribeSize = 0
    remainingTribes = 0
  for tribe, population in tribePopulations:
    if population > 0:
      inc remainingTribes
    if population > largestTribeSize:
      largestTribe = tribe
      largestTribeSize = population
  sim.runtimeStats["largestTribe"] = %largestTribe
  sim.runtimeStats["largestTribeSize"] = %largestTribeSize
  sim.runtimeStats["remainingTribes"] = %remainingTribes

proc candidateJson(candidate: MoveCandidate): JsonNode =
  %*{
    "cell": candidate.cell,
    "welfare": candidate.welfare,
    "distance": candidate.distance,
  }

proc observationJson(
    sim: Simulation,
    agentId, slot, requestId: int,
    candidates: openArray[MoveCandidate],
): string =
  let agent = sim.agents[agentId]
  var candidateNodes = newJArray()
  for candidate in candidates:
    let cell = sim.environment.cells[candidate.cell]
    var node = candidate.candidateJson()
    node["sugar"] = %cell.sugar
    node["spice"] = %cell.spice
    node["pollution"] = %cell.pollution
    node["occupied"] = %(cell.agent >= 0 and cell.agent != agentId)
    candidateNodes.add(node)
  $(%*{
    "type": "observation",
    "requestId": requestId,
    "slot": slot,
    "timestep": sim.timestep,
    "world": {
      "width": sim.environment.width,
      "height": sim.environment.height,
    },
    "agent": {
      "id": agent.id,
      "cell": agent.cell,
      "age": agent.age,
      "sugar": agent.sugar,
      "spice": agent.spice,
      "sugarMetabolism": agent.sugarMetabolism +
        agent.sugarMetabolismModifier,
      "spiceMetabolism": agent.spiceMetabolism +
        agent.spiceMetabolismModifier,
      "decisionModel": agent.decisionModel,
      "tribe": agent.tribe,
      "race": agent.race,
      "sick": agent.diseases.len > 0,
    },
    "candidates": candidateNodes,
  })

proc populationPolicy(
    config: CoworldConfig,
): PopulationPolicy =
  result = proc(
      sim: Simulation,
      agentId: int,
      candidates: openArray[MoveCandidate],
      greedyCell: int,
  ): int =
    let slot = appState.slots.slotForAgent(sim.agents[agentId])
    if slot < 0:
      return greedyCell

    var
      websocket: WebSocket
      connected = false
      requestId: int
    {.gcsafe.}:
      withLock appState.lock:
        inc appState.slots[slot].requests
        if slot in appState.playerSockets:
          websocket = appState.playerSockets[slot]
          connected = true
        requestId = appState.nextRequestId
        inc appState.nextRequestId
    if not connected:
      {.gcsafe.}:
        withLock appState.lock:
          inc appState.slots[slot].fallbacks
      return greedyCell

    var legalCells = newSeqOfCap[int](candidates.len)
    for candidate in candidates:
      legalCells.add(candidate.cell)
    {.gcsafe.}:
      withLock appState.lock:
        appState.pendingRequests[requestId] = PendingRequest(
          slot: slot,
          websocket: websocket,
          candidates: legalCells,
        )

    try:
      websocket.send(
        sim.observationJson(agentId, slot, requestId, candidates),
        TextMessage,
      )
    except CatchableError:
      {.gcsafe.}:
        withLock appState.lock:
          appState.pendingRequests.del(requestId)
          inc appState.slots[slot].fallbacks
      return greedyCell

    let deadline = getMonoTime() + initDuration(
      milliseconds = config.decisionTimeoutMs,
    )
    while getMonoTime() < deadline:
      var received = false
      {.gcsafe.}:
        withLock appState.lock:
          if requestId in appState.actions:
            result = appState.actions[requestId]
            appState.actions.del(requestId)
            appState.pendingRequests.del(requestId)
            inc appState.slots[slot].actions
            received = true
      if received:
        return
      sleep(1)
    {.gcsafe.}:
      withLock appState.lock:
        appState.actions.del(requestId)
        appState.pendingRequests.del(requestId)
        inc appState.slots[slot].fallbacks
    result = greedyCell

proc frameJson(
    sim: Simulation,
    slots: openArray[PolicySlot],
): JsonNode =
  var
    cells = newJArray()
    agents = newJArray()
    slotNodes = newJArray()
  for cell in sim.environment.cells:
    cells.add(%*[cell.sugar, cell.spice, cell.pollution])
  for id in sim.activeAgents:
    let agent = sim.agents[id]
    agents.add(%*{
      "id": id,
      "cell": agent.cell,
      "slot": slots.slotForAgent(agent),
      "decisionModel": agent.decisionModel,
      "age": agent.age,
      "sugar": agent.sugar,
      "spice": agent.spice,
      "depressed": agent.depressed,
      "sick": agent.diseases.len > 0,
      "sugarMetabolism":
        max(0.0, agent.sugarMetabolism + agent.sugarMetabolismModifier),
      "spiceMetabolism":
        max(0.0, agent.spiceMetabolism + agent.spiceMetabolismModifier),
      "movement": max(0, agent.movement + int(agent.movementModifier)),
      "vision": max(0, agent.vision + int(agent.visionModifier)),
      "race": agent.race,
      "sex": agent.sex,
      "tribe": agent.tribe,
    })
  for slot in slots:
    slotNodes.add(%*{
      "name": slot.name,
      "agentIds": slot.agentIds,
      "decisionModels": slot.decisionModels,
    })
  %*{
    "format": "sugarscape.frame.v1",
    "timestep": sim.timestep,
    "width": sim.environment.width,
    "height": sim.environment.height,
    "cells": cells,
    "agents": agents,
    "links": sim.socialLinksJson(),
    "slots": slotNodes,
    "stats": sim.runtimeStats.copy(),
  }

proc publishFrame(frame: JsonNode) =
  let streamedFrame = frame.copy()
  streamedFrame["streamId"] = %appState.streamId
  let body = $streamedFrame
  var sockets: seq[WebSocket]
  {.gcsafe.}:
    withLock appState.lock:
      appState.frameHistory.add(body)
      if appState.frameHistory.len > FrameHistoryLimit:
        appState.frameHistory.delete(0)
      for frames in appState.catchupFrames.mvalues:
        frames.add(body)
      sockets = appState.globalSockets
  for websocket in sockets:
    try:
      websocket.send(body, TextMessage)
    except CatchableError:
      {.gcsafe.}:
        withLock appState.lock:
          removeSocket(websocket)

proc buildResults(sim: Simulation): string =
  var names, scores, populations, meanWealths, requests, actions, fallbacks =
    newJArray()
  var slots: seq[PolicySlot]
  {.gcsafe.}:
    withLock appState.lock:
      slots = appState.slots & @[]
  for slotIndex, slot in slots:
    var
      population = 0
      totalWealth = 0.0
    for id in sim.activeAgents:
      let agent = sim.agents[id]
      if slots.slotForAgent(agent) == slotIndex:
        inc population
        totalWealth += agent.sugar + agent.spice
    names.add(%slot.name)
    scores.add(%int(totalWealth))
    populations.add(%population)
    meanWealths.add(%(
      if population > 0: totalWealth / float64(population)
      else: 0.0
    ))
    requests.add(%slot.requests)
    actions.add(%slot.actions)
    fallbacks.add(%slot.fallbacks)
  $(%*{
    "names": names,
    "scores": scores,
    "population": populations,
    "mean_wealth": meanWealths,
    "decision_requests": requests,
    "actions_received": actions,
    "fallbacks": fallbacks,
    "score_semantics": "final population sugar plus spice, truncated to integer",
    "final_stats": sim.runtimeStats,
  }) & "\n"

proc waitForPlayers(config: CoworldConfig) =
  if config.slots.len == 0 or config.connectionWaitMs == 0:
    return
  let deadline = getMonoTime() +
    initDuration(milliseconds = config.connectionWaitMs)
  while getMonoTime() < deadline:
    var connected = 0
    {.gcsafe.}:
      withLock appState.lock:
        connected = appState.playerSockets.len
    if connected >= config.slots.len:
      return
    sleep(10)

proc runCoworld*(runtimeConfig: RuntimeConfig) =
  let
    input = if runtimeConfig.config.len > 0: runtimeConfig.config else: "{}"
    raw = parseJson(input)
    coworldRaw =
      if raw.kind == JObject and raw.hasKey("sugarscapeOptions"):
        raw["sugarscapeOptions"]
      else:
        raw
    normalized = parseConfiguration(input)
    coworldConfig = readCoworldConfig(coworldRaw, normalized)
  if coworldConfig.playerTribes and normalized["agentTagging"].getBool():
    raise newException(
      ValueError,
      "playerTribes cannot be combined with agentTagging",
    )
  normalized["playerTribes"] = %coworldConfig.playerTribes
  normalized["onePlayerPerAgent"] = %coworldConfig.onePlayerPerAgent
  initAppState(coworldConfig.slots)

  let httpServer = newServer(httpHandler, websocketHandler, workerThreads = 2)
  var
    thread: Thread[ServerThreadArgs]
    serverPointer = cast[ptr Server](unsafeAddr httpServer)
  createThread(
    thread,
    serverThread,
    ServerThreadArgs(
      server: serverPointer,
      host: runtimeConfig.host,
      port: runtimeConfig.port,
    ),
  )
  httpServer.waitUntilReady()
  echo "Sugarscape Coworld listening on ", runtimeConfig.host, ":",
    runtimeConfig.port

  if runtimeConfig.replayMode:
    let replay = parseJson(runtimeConfig.replay)
    if replay.kind != JObject or not replay.hasKey("frames") or
        replay["frames"].kind != JArray:
      raise newException(ValueError, "invalid sugarscape.replay.v1 artifact")
    for frame in replay["frames"]:
      frame.publishFrame()
      sleep(40)
    joinThread(thread)
    return
  else:
    var
      sim = initSimulation(normalized)
      frames = newJArray()
    if coworldConfig.playerTribes:
      sim.assignPlayerTribes(coworldConfig.slots)
    let initialFrame = sim.frameJson(coworldConfig.slots)
    frames.add(initialFrame)
    initialFrame.publishFrame()
    coworldConfig.waitForPlayers()
    let policy = coworldConfig.populationPolicy()
    while sim.timestep < sim.maxTimestep and
        (sim.activeAgents.len > 0 or
          sim.config["keepAlivePostExtinction"].getBool()):
      sim.doTimestep(policy)
      if coworldConfig.playerTribes:
        sim.assignPlayerTribes(coworldConfig.slots)
      if sim.timestep mod coworldConfig.frameInterval == 0 or
          sim.timestep == sim.maxTimestep:
        let frame = sim.frameJson(appState.slots)
        frames.add(frame)
        frame.publishFrame()
    runtimeConfig.writeResults(sim.buildResults())
    runtimeConfig.writeReplay($(%*{
      "format": "sugarscape.replay.v1",
      "config": sim.config,
      "frames": frames,
    }))

  httpServer.close()
  joinThread(thread)
