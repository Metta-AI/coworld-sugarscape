# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
import std/[json, os, sequtils, strutils]

import sugarscape/[configuration, simulation]

if paramCount() != 2:
  quit("usage: dump_state CONFIG TIMESTEPS")

var sim = initSimulation(loadConfiguration(paramStr(1)))
let timesteps = parseInt(paramStr(2))
for timestep in 1 .. timesteps:
  sim.doTimestep()

var outputAgents = newJArray()
for id in sim.activeAgents:
  let agent = sim.agents[id]
  outputAgents.add(%*{
    "id": agent.id,
    "cell": agent.cell,
    "cellSugar":
      if agent.cell >= 0: sim.environment.cells[agent.cell].sugar
      else: 0,
    "cellSpice":
      if agent.cell >= 0: sim.environment.cells[agent.cell].spice
      else: 0,
    "sugar": agent.sugar,
    "spice": agent.spice,
    "happiness": agent.happiness,
    "conflictHappiness": agent.conflictHappiness,
    "familyHappiness": agent.familyHappiness,
    "healthHappiness": agent.healthHappiness,
    "socialHappiness": agent.socialHappiness,
    "wealthHappiness": agent.wealthHappiness,
    "lastSugar": agent.lastSugar,
    "lastSpice": agent.lastSpice,
    "age": agent.age,
    "friends": agent.friends.len,
    "maxFriends": agent.maxFriends,
    "movement": agent.movement,
    "vision": agent.vision,
    "sex": agent.sex,
    "depressed": agent.depressed,
    "movementNeighbors": agent.movementNeighborhood.len,
    "movementStatsNeighbors": agent.movementNeighborhood.len,
    "validMoves": agent.validMoves.len,
    "validMoveRecords": agent.validMoves,
    "movementNeighborhood": agent.movementNeighborhood,
    "race": agent.race,
    "racialTags": agent.racialTags,
    "tribe": agent.tribe,
    "tags": agent.tags,
    "diseases": agent.diseases.mapIt(it.disease),
    "mrs": agent.marginalRateOfSubstitution,
    "tradeVolume": agent.tradeVolume,
    "sugarPrice": agent.sugarPrice,
    "spicePrice": agent.spicePrice,
    "timeToLive": agent.timeToLive,
    "lastTimeToLive": agent.lastTimeToLive,
    "sugarMetabolism": agent.sugarMetabolism,
    "spiceMetabolism": agent.spiceMetabolism,
    "sugarMetabolismModifier": agent.sugarMetabolismModifier,
    "spiceMetabolismModifier": agent.spiceMetabolismModifier,
    "decisionModel": agent.decisionModel,
    "decisionModelFactor": agent.decisionModelFactor,
    "selfishnessFactor": agent.selfishnessFactor,
  })
echo $(%*{
  "order": sim.activeAgents,
  "agents": outputAgents,
  "pollution": sim.environment.cells.mapIt(it.pollution),
  "sugarProductionPollutionFactor":
    sim.environment.sugarProductionPollutionFactor,
})
