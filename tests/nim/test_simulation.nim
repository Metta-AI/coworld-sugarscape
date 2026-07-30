import std/[json, unittest]

import sugarscape/[agents, configuration, simulation]

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

  test "a population policy receives legal ranked moves sequentially":
    let config = loadConfiguration("tests/fixtures/base_small.json")
    var
      sim = initSimulation(config)
      decisions = 0
    let policy: PopulationPolicy = proc(
        snapshot: Simulation,
        agentId: int,
        candidates: openArray[MoveCandidate],
        greedyCell: int,
    ): int =
      check snapshot.timestep == 1
      check snapshot.agents[agentId].alive
      check candidates.len > 0
      check candidates[0].cell == greedyCell
      inc decisions
      candidates[^1].cell
    sim.doTimestep(policy)
    check decisions == 4

  test "seed -1 is replaced with a replayable nonnegative seed":
    var config = loadConfiguration("tests/fixtures/base_small.json")
    config["seed"] = newJInt(-1)
    let first = initSimulation(config)
    check first.config["seed"].getBiggestInt() >= 0
    let replay = initSimulation(first.config)
    check replay.activeAgents == first.activeAgents
    for id in first.activeAgents:
      check replay.agents[id].cell == first.agents[id].cell
      check replay.agents[id].sugar == first.agents[id].sugar
      check replay.agents[id].spice == first.agents[id].spice

  test "spectator links retain one-sided relationships and deduplicate pairs":
    let config = loadConfiguration("tests/fixtures/base_small.json")
    var sim = initSimulation(config)
    sim.agents[0].friends = @[]
    sim.agents[3].friends = @[FriendEntry(agent: 0)]
    sim.agents[0].mates = @[]
    sim.agents[3].mates = @[0]

    let oneSided = sim.socialLinksJson()
    check oneSided.len == 2
    check oneSided[0] == %*{
      "source": 0,
      "target": 3,
      "type": "friend",
    }
    check oneSided[1] == %*{
      "source": 0,
      "target": 3,
      "type": "mate",
    }

    sim.agents[0].friends = @[FriendEntry(agent: 3)]
    sim.agents[0].mates = @[3]
    check sim.socialLinksJson().len == 2
