import std/unittest

import sugarscape/[agents, configuration, environment, py_random]

suite "DTL initial-agent compatibility":
  test "endowments and placement match the pinned small-world oracle":
    let config = loadConfiguration("tests/fixtures/base_small.json")
    var
      world = initEnvironment(config)
      rng = initPyRandom(12345)
      agents = createInitialAgents(config, world, rng)

    let expected = [
      (x: 2, y: 4, sugar: 3.0, metabolism: 2.0, movement: 1, vision: 1),
      (x: 4, y: 4, sugar: 4.0, metabolism: 1.0, movement: 2, vision: 2),
      (x: 4, y: 1, sugar: 5.0, metabolism: 1.0, movement: 2, vision: 2),
      (x: 1, y: 0, sugar: 6.0, metabolism: 2.0, movement: 1, vision: 1),
    ]

    check agents.len == expected.len
    for id in 0 ..< agents.len:
      let
        agent = agents[id]
        target = expected[id]
      check world.cells[agent.cell].x == target.x
      check world.cells[agent.cell].y == target.y
      check agent.sugar == target.sugar
      check agent.sugarMetabolism == target.metabolism
      check agent.movement == target.movement
      check agent.vision == target.vision
      check agent.lookaheadFactor == 0.0
      check agent.maxAge == -1
      check world.cells[agent.cell].agent == id
