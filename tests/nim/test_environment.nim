import std/[math, unittest]

import sugarscape/[configuration, environment]

suite "DTL environment compatibility":
  test "resource peaks match the pinned small-world oracle":
    let
      config = loadConfiguration("tests/fixtures/base_small.json")
      world = initEnvironment(config)
      expected = [
        [4'i64, 4, 4, 4, 3, 2],
        [4'i64, 4, 4, 4, 4, 3],
        [4'i64, 4, 4, 4, 4, 4],
        [4'i64, 4, 4, 4, 4, 4],
        [3'i64, 3, 3, 4, 4, 4],
      ]

    for y in 0 ..< world.height:
      for x in 0 ..< world.width:
        check world.cells[world.cellId(x, y)].maxSugar == expected[y][x]

  test "cardinal range insertion order and wraparound match Python dicts":
    let
      config = loadConfiguration("tests/fixtures/base_small.json")
      world = initEnvironment(config)
      origin = world.cellId(0, 0)

    check world.ranges[origin][1] == @[
      RangeEntry(cell: world.cellId(1, 0), distance: 1.0),
      RangeEntry(cell: world.cellId(0, 1), distance: 1.0),
      RangeEntry(cell: world.cellId(0, 4), distance: 1.0),
      RangeEntry(cell: world.cellId(5, 0), distance: 1.0),
    ]
    check world.ranges[origin][2] == @[
      RangeEntry(cell: world.cellId(2, 0), distance: 2.0),
      RangeEntry(cell: world.cellId(0, 2), distance: 2.0),
      RangeEntry(cell: world.cellId(0, 3), distance: 2.0),
      RangeEntry(cell: world.cellId(4, 0), distance: 2.0),
    ]

  test "radial ranges preserve Python insertion order and distances":
    let
      config = loadConfiguration("tests/fixtures/ecology_small.json")
      world = initEnvironment(config)
      origin = world.cellId(0, 0)

    check world.maxCellDistance == 2
    check world.ranges[origin][1] == @[
      RangeEntry(cell: world.cellId(0, 1), distance: 1.0),
      RangeEntry(cell: world.cellId(0, 4), distance: 1.0),
      RangeEntry(cell: world.cellId(1, 0), distance: 1.0),
      RangeEntry(cell: world.cellId(1, 1), distance: sqrt(2.0)),
      RangeEntry(cell: world.cellId(1, 4), distance: sqrt(2.0)),
      RangeEntry(cell: world.cellId(4, 0), distance: 1.0),
      RangeEntry(cell: world.cellId(4, 1), distance: sqrt(2.0)),
      RangeEntry(cell: world.cellId(4, 4), distance: sqrt(2.0)),
    ]

  test "seasons and pollution diffusion match the pinned oracle":
    let config = loadConfiguration("tests/fixtures/ecology_small.json")
    var world = initEnvironment(config)
    world.cells[world.cellId(0, 0)].pollution = 8
    world.cells[world.cellId(0, 1)].pollution = 4
    world.cells[world.cellId(0, 0)].sugar = 0
    world.cells[world.cellId(0, 3)].sugar = 0

    for timestep in 1 .. 4:
      world.doTimestep(timestep)

    check world.seasonalGrowbackCountdown == 2
    check world.pollutionDiffusionCountdown == 2
    check world.cells[world.cellId(0, 0)].season == wet
    check world.cells[world.cellId(0, 3)].season == dry
    check world.cells[world.cellId(0, 0)].sugar == 3
    check world.cells[world.cellId(0, 3)].sugar == 3
    check world.cells[world.cellId(0, 0)].pollution == 2.0
    check world.cells[world.cellId(0, 1)].pollution == 1.0
    check world.cells[world.cellId(0, 2)].pollution == 0.5
    check world.cells[world.cellId(0, 3)].pollution == 0.75
    check world.cells[world.cellId(0, 4)].pollution == 0.25
