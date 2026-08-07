# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
## Bit-for-bit implementation of the CPython 3.12 ``random.Random`` paths used
## by DTL Sugarscape. The generator is MT19937, but CPython's integer seeding,
## getrandbits truncation, and randbelow rejection behavior are also observable.

import checksums/md5

const
  StateSize = 624
  StatePeriod = 397
  MatrixA = 0x9908b0df'u32
  UpperMask = 0x80000000'u32
  LowerMask = 0x7fffffff'u32

type
  PyRandom* = object
    state: array[StateSize, uint32]
    index: int

proc initGenRand(rng: var PyRandom, seed: uint32) =
  rng.state[0] = seed
  for index in 1 ..< StateSize:
    let previous = rng.state[index - 1]
    rng.state[index] =
      1812433253'u32 * (previous xor (previous shr 30)) + uint32(index)
  rng.index = StateSize

proc seedWords*(rng: var PyRandom, words: openArray[uint32]) =
  ## Match CPython's ``init_by_array``. ``words`` are the absolute integer
  ## seed's 32-bit limbs in little-endian order.
  rng.initGenRand(19650218'u32)

  var
    stateIndex = 1
    wordIndex = 0
    remaining = max(StateSize, words.len)

  while remaining > 0:
    let previous = rng.state[stateIndex - 1]
    rng.state[stateIndex] =
      (rng.state[stateIndex] xor
        ((previous xor (previous shr 30)) * 1664525'u32)) +
      words[wordIndex] +
      uint32(wordIndex)
    inc stateIndex
    inc wordIndex
    if stateIndex >= StateSize:
      rng.state[0] = rng.state[StateSize - 1]
      stateIndex = 1
    if wordIndex >= words.len:
      wordIndex = 0
    dec remaining

  remaining = StateSize - 1
  while remaining > 0:
    let previous = rng.state[stateIndex - 1]
    rng.state[stateIndex] =
      (rng.state[stateIndex] xor
        ((previous xor (previous shr 30)) * 1566083941'u32)) -
      uint32(stateIndex)
    inc stateIndex
    if stateIndex >= StateSize:
      rng.state[0] = rng.state[StateSize - 1]
      stateIndex = 1
    dec remaining

  rng.state[0] = 0x80000000'u32
  rng.index = StateSize

proc seed*(rng: var PyRandom, value: uint64) =
  if value <= uint64(high(uint32)):
    rng.seedWords([uint32(value)])
  else:
    rng.seedWords([uint32(value), uint32(value shr 32)])

proc initPyRandom*(seed: uint64): PyRandom =
  result.seed(seed)

proc seedFromMd5*(rng: var PyRandom, value: string, addend = 0'u64) =
  ## DTL repeatedly uses ``int(md5(name).hexdigest(), 16) + timestep`` as a
  ## temporary seed. Convert that integer to the little-endian 32-bit limb
  ## sequence consumed by CPython.
  let digest = toMD5(value)
  var words: array[4, uint32]
  for wordIndex in 0 ..< words.len:
    let digestStart = 12 - wordIndex * 4
    words[wordIndex] =
      (uint32(digest[digestStart]) shl 24) or
      (uint32(digest[digestStart + 1]) shl 16) or
      (uint32(digest[digestStart + 2]) shl 8) or
      uint32(digest[digestStart + 3])

  var carry = addend
  for word in words.mitems:
    let sum = uint64(word) + (carry and 0xffffffff'u64)
    word = uint32(sum)
    carry = (carry shr 32) + (sum shr 32)
  rng.seedWords(words)

proc nextUint32*(rng: var PyRandom): uint32 =
  if rng.index >= StateSize:
    for index in 0 ..< StateSize - StatePeriod:
      let combined =
        (rng.state[index] and UpperMask) or
        (rng.state[index + 1] and LowerMask)
      rng.state[index] =
        rng.state[index + StatePeriod] xor
        (combined shr 1) xor
        (if (combined and 1) == 0: 0'u32 else: MatrixA)

    for index in StateSize - StatePeriod ..< StateSize - 1:
      let combined =
        (rng.state[index] and UpperMask) or
        (rng.state[index + 1] and LowerMask)
      rng.state[index] =
        rng.state[index + StatePeriod - StateSize] xor
        (combined shr 1) xor
        (if (combined and 1) == 0: 0'u32 else: MatrixA)

    let combined =
      (rng.state[StateSize - 1] and UpperMask) or
      (rng.state[0] and LowerMask)
    rng.state[StateSize - 1] =
      rng.state[StatePeriod - 1] xor
      (combined shr 1) xor
      (if (combined and 1) == 0: 0'u32 else: MatrixA)
    rng.index = 0

  result = rng.state[rng.index]
  inc rng.index
  result = result xor (result shr 11)
  result = result xor ((result shl 7) and 0x9d2c5680'u32)
  result = result xor ((result shl 15) and 0xefc60000'u32)
  result = result xor (result shr 18)

proc randomFloat*(rng: var PyRandom): float64 =
  let
    highBits = rng.nextUint32() shr 5
    lowBits = rng.nextUint32() shr 6
  (float64(highBits) * 67108864.0 + float64(lowBits)) *
    (1.0 / 9007199254740992.0)

proc bitLength(value: uint64): int =
  var remaining = value
  while remaining != 0:
    inc result
    remaining = remaining shr 1

proc getRandBits*(rng: var PyRandom, bitCount: range[0 .. 64]): uint64 =
  if bitCount == 0:
    return 0
  if bitCount <= 32:
    return uint64(rng.nextUint32() shr (32 - bitCount))

  result = uint64(rng.nextUint32())
  let highBitCount = bitCount - 32
  let highWord = rng.nextUint32() shr (32 - highBitCount)
  result = result or (uint64(highWord) shl 32)

proc randBelow*(rng: var PyRandom, upperBound: uint64): uint64 =
  assert upperBound > 0
  let bits = bitLength(upperBound)
  result = rng.getRandBits(bits)
  while result >= upperBound:
    result = rng.getRandBits(bits)

proc shuffle*[T](rng: var PyRandom, values: var seq[T]) =
  if values.len < 2:
    return
  for index in countdown(values.high, 1):
    let swapIndex = int(rng.randBelow(uint64(index + 1)))
    swap(values[index], values[swapIndex])
