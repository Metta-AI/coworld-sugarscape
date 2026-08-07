# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
import std/unittest

import sugarscape/py_random

suite "CPython 3.12 random compatibility":
  test "seed 12345 produces identical 32-bit words":
    var rng = initPyRandom(12345'u64)
    let expected = [
      1789368711'u32,
      3146859322'u32,
      43676229'u32,
      3522623596'u32,
      3544234957'u32,
      3448207591'u32,
      1282648386'u32,
      3672791226'u32,
      1582316135'u32,
      4001984784'u32,
    ]

    for value in expected:
      check rng.nextUint32() == value

  test "random uses CPython's exact 53-bit float construction":
    var rng = initPyRandom(12345'u64)
    let expectedBits = [
      0x3fdaa9e665dc8a18'u64,
      0x3f84d392d1f6f840'u64,
      0x3fea68177b361de3'u64,
      0x3fd31cea56d752c4'u64,
      0x3fd7940e9f744b88'u64,
      0x3fc8c9e52452ec40'u64,
      0x3fe21cbd29beb2a9'u64,
      0x3fc4b22fc5f811c8'u64,
      0x3fbfcff45bf93c70'u64,
      0x3fdbb53a5216b65a'u64,
    ]

    for bits in expectedBits:
      check cast[uint64](rng.randomFloat()) == bits

  test "all limbs of DTL's 128-bit MD5-derived seeds are used":
    var rng: PyRandom
    rng.seedFromMd5("movement", 17)
    let expected = [
      2461049465'u32,
      757655362'u32,
      937136902'u32,
      1974697968'u32,
      3478385206'u32,
    ]

    for value in expected:
      check rng.nextUint32() == value

  test "randbelow consumes getrandbits exactly like CPython":
    var rng = initPyRandom(12345'u64)
    let bounds = [1'u64, 2, 3, 10, 255, 256, 257, 2147483647]
    let expected = [0'u64, 0, 1, 5, 238, 99, 138, 1215493282]

    for index in 0 ..< bounds.len:
      check rng.randBelow(bounds[index]) == expected[index]

  test "shuffle uses reverse Fisher-Yates with randbelow":
    var rng = initPyRandom(12345'u64)
    var values = @[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    rng.shuffle(values)

    check values == @[11, 10, 8, 1, 7, 9, 2, 3, 5, 4, 0, 6]
