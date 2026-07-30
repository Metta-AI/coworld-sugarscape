import std/unittest

import sugarscape/[configuration, simulation]

suite "DTL base simulation compatibility":
  test "four asynchronous timesteps match the pinned Python oracle":
    let config = loadConfiguration("tests/fixtures/base_small.json")
    var sim = initSimulation(config)
    let expected = [
      @[
        (x: 2, y: 4, sugar: 3.0, age: 0),
        (x: 4, y: 4, sugar: 4.0, age: 0),
        (x: 4, y: 1, sugar: 5.0, age: 0),
        (x: 1, y: 0, sugar: 6.0, age: 0),
      ],
      @[
        (x: 3, y: 4, sugar: 5.0, age: 1),
        (x: 4, y: 3, sugar: 7.0, age: 1),
        (x: 4, y: 2, sugar: 8.0, age: 1),
        (x: 0, y: 0, sugar: 8.0, age: 1),
      ],
      @[
        (x: 4, y: 4, sugar: 7.0, age: 2),
        (x: 3, y: 3, sugar: 10.0, age: 2),
        (x: 5, y: 2, sugar: 11.0, age: 2),
        (x: 0, y: 1, sugar: 10.0, age: 2),
      ],
      @[
        (x: 5, y: 4, sugar: 9.0, age: 3),
        (x: 3, y: 2, sugar: 13.0, age: 3),
        (x: 5, y: 3, sugar: 14.0, age: 3),
        (x: 1, y: 1, sugar: 12.0, age: 3),
      ],
      @[
        (x: 0, y: 4, sugar: 10.0, age: 4),
        (x: 2, y: 2, sugar: 16.0, age: 4),
        (x: 0, y: 3, sugar: 17.0, age: 4),
        (x: 1, y: 2, sugar: 14.0, age: 4),
      ],
    ]
    let expectedOrder = [
      @[3, 1, 2, 0],
      @[1, 2, 0, 3],
      @[3, 0, 1, 2],
      @[0, 3, 1, 2],
      @[2, 0, 1, 3],
    ]

    for timestep in 0 .. 4:
      check sim.timestep == timestep
      check sim.activeAgents == expectedOrder[timestep]
      for id in 0 ..< sim.agents.len:
        let
          agent = sim.agents[id]
          target = expected[timestep][id]
          cell = sim.environment.cells[agent.cell]
        check cell.x == target.x
        check cell.y == target.y
        check agent.sugar == target.sugar
        check agent.age == target.age
      if timestep < 4:
        sim.doTimestep()
