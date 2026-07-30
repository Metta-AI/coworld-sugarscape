import std/[asyncdispatch, json, os]

import ws

proc run(endpoint: string) {.async.} =
  var connected = false
  while true:
    try:
      let socket = await newWebSocket(endpoint)
      connected = true
      while true:
        let message = parseJson(await socket.receiveStrPacket())
        if message.kind != JObject or
            not message.hasKey("type") or
            message["type"].getStr() != "observation" or
            not message.hasKey("requestId") or
            not message.hasKey("candidates") or
            message["candidates"].len == 0:
          continue
        await socket.send($(%*{
          "type": "action",
          "requestId": message["requestId"].getInt(),
          "cell": message["candidates"][0]["cell"].getInt(),
        }))
    except CatchableError as error:
      if connected:
        echo "episode ended: ", error.msg
        return
      echo "connection retry: ", error.msg
      await sleepAsync(250)

when isMainModule:
  let endpoint = getEnv(
    "COWORLD_PLAYER_WS_URL",
    getEnv("COGAMES_ENGINE_WS_URL"),
  )
  if endpoint.len == 0:
    raise newException(
      ValueError,
      "COWORLD_PLAYER_WS_URL is required",
    )
  waitFor run(endpoint)
