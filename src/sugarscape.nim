import std/[json, os, strutils]

import sugarscape/configuration
import sugarscape/simulation

proc printHelp() =
  stdout.write(
    "Usage:\n\tsugarscape --conf config.json\n\n" &
    "Options:\n" &
    "\t-c,--conf\tUse specified config file for simulation settings.\n" &
    "\t-h,--help\tDisplay this message.\n"
  )

proc main() =
  var
    configPath = ""
    dumpConfig = false
    index = 0
  let arguments = commandLineParams()

  while index < arguments.len:
    let argument = arguments[index]
    if argument in ["-h", "--help"]:
      printHelp()
      return
    if argument in ["-c", "--conf"]:
      inc index
      if index >= arguments.len:
        raise newException(ValueError, "No config file provided.")
      configPath = arguments[index]
    elif argument.startsWith("--conf="):
      configPath = argument["--conf=".len .. ^1]
    elif argument == "--dump-config":
      dumpConfig = true
    else:
      raise newException(ValueError, "option " & argument & " not recognized")
    inc index

  let config =
    if configPath.len == 0: parseConfiguration("{}")
    else: loadConfiguration(configPath)

  if dumpConfig:
    stdout.write($config)
    stdout.write("\n")
    return

  var simulation = initSimulation(config)
  let logPath =
    if config["logfile"].kind == JNull: ""
    else: config["logfile"].getStr()
  simulation.runSimulation(logPath)

when isMainModule:
  main()
