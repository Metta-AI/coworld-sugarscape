# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
## CPython ``json.dumps`` formatting for the value surface emitted by
## Sugarscape. Object insertion order and default separators are byte-visible.

import std/[json, math, strutils]

const PythonIntegerPrefix = "\x00python-integer:"

proc pythonIntegerNode*(value: string): JsonNode =
  ## ``JsonNode`` only carries signed 64-bit integers, while CPython integers
  ## are unbounded. Keep the uncommon wider value lossless until serialization.
  newJString(PythonIntegerPrefix & value)

proc isPythonInteger(node: JsonNode): bool =
  node.kind == JString and node.getStr().startsWith(PythonIntegerPrefix)

proc pythonIntegerText(node: JsonNode): string =
  node.getStr()[PythonIntegerPrefix.len .. ^1]

proc exponentText(exponent: int): string =
  let magnitude = abs(exponent)
  result = if exponent < 0: "-" else: "+"
  if magnitude < 10:
    result.add("0")
  result.add($magnitude)

proc scientificFromFixed(text: string): string =
  var
    negative = false
    digits = text
  if digits.startsWith("-"):
    negative = true
    digits = digits[1 .. ^1]

  let decimalIndex = digits.find('.')
  var
    integerPart = if decimalIndex < 0: digits else: digits[0 ..< decimalIndex]
    fractionalPart =
      if decimalIndex < 0: ""
      else: digits[decimalIndex + 1 .. ^1]
    exponent: int
    significant: string

  if integerPart.strip(chars = {'0'}).len > 0:
    let first = integerPart.find(AllChars - {'0'})
    exponent = integerPart.len - first - 1
    significant = integerPart[first .. ^1] & fractionalPart
  else:
    let first = fractionalPart.find(AllChars - {'0'})
    exponent = -(first + 1)
    significant = fractionalPart[first .. ^1]

  while significant.len > 1 and significant.endsWith("0"):
    significant.setLen(significant.len - 1)

  if negative:
    result.add("-")
  result.add(significant[0])
  if significant.len > 1:
    result.add(".")
    result.add(significant[1 .. ^1])
  result.add("e")
  result.add(exponentText(exponent))

proc normalizeScientific(text: string): string =
  let exponentMarker = max(text.find('e'), text.find('E'))
  let mantissa = text[0 ..< exponentMarker]
  let exponent = parseInt(text[exponentMarker + 1 .. ^1])
  mantissa & "e" & exponentText(exponent)

proc pythonFloat*(value: float64): string =
  if value.isNaN:
    return "NaN"
  if value == Inf:
    return "Infinity"
  if value == -Inf:
    return "-Infinity"

  result = $value
  if 'e' in result or 'E' in result:
    return normalizeScientific(result)
  let magnitude = abs(value)
  if magnitude != 0 and (magnitude < 1e-4 or magnitude >= 1e16):
    return scientificFromFixed(result)

proc pythonJson*(node: JsonNode): string =
  if node.isPythonInteger:
    return node.pythonIntegerText
  case node.kind
  of JObject:
    result.add("{")
    var first = true
    for key, value in node:
      if not first:
        result.add(", ")
      first = false
      result.add($(newJString(key)))
      result.add(": ")
      result.add(pythonJson(value))
    result.add("}")
  of JArray:
    result.add("[")
    for index, value in node.elems:
      if index > 0:
        result.add(", ")
      result.add(pythonJson(value))
    result.add("]")
  of JFloat:
    result = pythonFloat(node.getFloat())
  else:
    result = $node

proc pythonString*(node: JsonNode): string =
  ## CPython ``str`` for scalar values written by the upstream CSV logger.
  if node.isPythonInteger:
    return node.pythonIntegerText
  case node.kind
  of JNull:
    "None"
  of JBool:
    if node.getBool(): "True" else: "False"
  of JFloat:
    pythonFloat(node.getFloat())
  of JString:
    node.getStr()
  else:
    $node
