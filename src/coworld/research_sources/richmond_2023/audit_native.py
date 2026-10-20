"""Audit a sealed native benchmark prefix without granting full-grid completion."""

import argparse
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("evidence", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
root = args.evidence
assert (
    hashlib.sha256((root / "source-manifest.json").read_bytes()).hexdigest()
    == "571a8158fc9a2cac1d7fdfaca18ad4c3665faaa2da652ce3c1ba434520c92f99"
)
receipt = json.loads((root / "qualification.json").read_text())
code = int((root / "run/execution-exit-code.txt").read_text())
assert (
    code == receipt["execution_exit_code"] == int((root / "exit-code.txt").read_text())
)
assert code in [0, 124], code
for name, expected in receipt["files"].items():
    content = (root / "run" / name).read_bytes()
    assert len(content) == expected["bytes"]
    assert hashlib.sha256(content).hexdigest() == expected["sha256"], name
results = []
complete_conditions = 0
complete_prefix = True
raw_steps = 0
for experiment, widths, densities in [
    ("performance_scaling", range(256, 4097, 256), ["0.17"]),
    ("occupation", [512], ["0.02", "0.04", "0.08", "0.16", "0.32", "0.64"]),
]:
    expected_keys = [(r, w, d) for r in range(3) for w in widths for d in densities]
    aggregate_path = root / "run" / (experiment + ".csv")
    if not aggregate_path.exists():
        complete_prefix = False
        results.append(
            {"experiment": experiment, "completed_conditions": 0, "step_rows": 0}
        )
        continue
    assert complete_prefix, "Later experiment precedes a complete earlier experiment"
    with aggregate_path.open() as stream:
        aggregate = list(csv.DictReader(stream))
    with (root / "run" / (experiment + "perStep.csv")).open() as stream:
        steps = list(csv.DictReader(stream))
    assert len(steps) == receipt["csv_rows"][experiment + "perStep.csv"]
    assert len(aggregate) == receipt["csv_rows"][experiment + ".csv"]
    raw_steps += len(steps)
    groups = {}
    for row in steps:
        key = (int(row["repetition"]), int(row["grid_width"]), row["p_occupation"])
        groups.setdefault(key, []).append(row)
        assert int(row["pop_size"]) == key[1] ** 2
        assert 0 <= int(row["pop_count"]) <= key[1] ** 2
        assert Decimal(row["s_step"]).is_finite() and Decimal(row["s_step"]) > 0
    assert list(groups) == expected_keys[: len(groups)]
    for i, (key, rows) in enumerate(groups.items()):
        assert [int(r["step"]) for r in rows] == list(range(len(rows)))
        assert 0 < len(rows) <= 100
        assert len(rows) == 100 or i == len(groups) - 1
    keys = [
        (int(r["repetition"]), int(r["grid_width"]), r["p_occupation"])
        for r in aggregate
    ]
    assert keys == expected_keys[: len(aggregate)]
    assert len(aggregate) <= len(groups) <= len(aggregate) + 1
    measurements = []
    for key, row in zip(keys, aggregate):
        observations = groups[key]
        assert len(observations) == 100
        assert int(row["pop_size"]) == key[1] ** 2
        for field, target in [
            ("s_step", "s_step_mean"),
            ("pop_count", "pop_count_mean"),
        ]:
            values = [Decimal(r[field]) for r in observations]
            mean = sum(values) / 100
            recorded = Decimal(row[target])
            assert recorded.is_finite()
            bound = Decimal(10) ** recorded.as_tuple().exponent / 2
            if field == "s_step":
                bound += (
                    sum(Decimal(10) ** x.as_tuple().exponent / 2 for x in values) / 100
                )
            assert abs(mean - recorded) <= bound, (key, target, mean, recorded, bound)
            measurements.append(
                {
                    "key": key,
                    "metric": target,
                    "recomputed": str(mean),
                    "recorded": str(recorded),
                    "rounding_bound": str(bound),
                }
            )
    complete_conditions += len(aggregate)
    complete_prefix = len(aggregate) == len(expected_keys)
    results.append(
        {
            "experiment": experiment,
            "completed_conditions": len(aggregate),
            "required_conditions": len(expected_keys),
            "step_rows": len(steps),
            "measurements": measurements,
        }
    )
resolution_path = root / "run/resolution_steps.csv"
resolution_rows = []
if resolution_path.exists():
    assert complete_prefix
    with resolution_path.open() as stream:
        resolution_rows = list(csv.DictReader(stream))
    expected = [
        (r, d, n)
        for r in range(3)
        for d in ["0.02", "0.04", "0.08", "0.16", "0.32", "0.64"]
        for n in range(1, 10)
    ]
    keys = [
        (int(r["repetition"]), r["p_occupation"], int(r["resolution_iterations"]))
        for r in resolution_rows
    ]
    assert keys == expected[: len(keys)]
    for row in resolution_rows:
        assert int(row["grid_width"]) == 512 and int(row["pop_size"]) == 512**2
        assert (
            0
            <= Decimal(row["mean_unresolved_count"])
            <= Decimal(row["mean_pop_count"])
            <= 512**2
        )
    complete_conditions += len(resolution_rows) // 9
complete = complete_conditions == 84 and len(resolution_rows) == 162
assert code != 0 or complete
report = {
    "execution_exit_code": code,
    "completed_conditions": complete_conditions,
    "required_conditions": 84,
    "complete_grid": complete,
    "step_rows": raw_steps,
    "resolution_rows": len(resolution_rows),
    "experiments": results,
    "scope": "Native source, receipt, coverage and aggregate audit. No independent agent-state, historical-equivalence, or performance verdict.",
}
args.output.mkdir(parents=True, exist_ok=False)
(args.output / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "experiments"}))
