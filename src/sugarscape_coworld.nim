import
  bitworld/runtime,
  sugarscape/coworld

when isMainModule:
  try:
    runCoworld(readRuntimeConfig())
  except CatchableError as error:
    stderr.writeLine("Sugarscape Coworld failed: " & error.msg)
    quit(1)
