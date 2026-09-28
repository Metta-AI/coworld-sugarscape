import std/[json, os, unittest]

import ../sugarscape_native

let fixture = parseFile(currentSourcePath.parentDir / "fixtures" / "python_random_1729.json")

proc fixtureRng(): PythonMt19937 =
  loadRng(fixture["rng"])

suite "Python MT19937 compatibility":
  test "getrandbits matches CPython":
    var rng = fixtureRng()
    for sample in fixture["getrandbits"]:
      check rng.getRandBits(sample["bits"].getInt()) == uint64(sample["value"].getBiggestInt())

  test "randbelow matches CPython":
    var rng = fixtureRng()
    for sample in fixture["randbelow"]:
      check rng.randBelow(uint64(sample["upper"].getInt())) == uint64(sample["value"].getInt())

  test "shuffle matches CPython":
    var rng = fixtureRng()
    var values = newSeq[int](fixture["shuffle"]["length"].getInt())
    for i in 0 ..< values.len:
      values[i] = i
    rng.pythonShuffle(values)
    check values == fixture["shuffle"]["values"].to(seq[int])
