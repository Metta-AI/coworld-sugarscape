# ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
import std/[json, unittest]

import sugarscape/py_json

suite "CPython json.dumps compatibility":
  test "default separators and insertion order match":
    var value = newJObject()
    value["integer"] = newJInt(7)
    value["floating"] = newJFloat(7.0)
    value["nothing"] = newJNull()
    value["items"] = %* [1, 2]

    check pythonJson(value) ==
      """{"integer": 7, "floating": 7.0, "nothing": null, "items": [1, 2]}"""

  test "Python scientific notation thresholds and exponent padding match":
    check pythonJson(%1e-7) == "1e-07"
    check pythonJson(%1e-4) == "0.0001"
    check pythonJson(%1e15) == "1000000000000000.0"
    check pythonJson(%1e16) == "1e+16"

  test "Python integers wider than int64 remain unquoted":
    let value = pythonIntegerNode("100000000000000000000")

    check pythonJson(value) == "100000000000000000000"
    check pythonString(value) == "100000000000000000000"
