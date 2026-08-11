#!/usr/bin/env python3
"""Convert an HMD period life table into the age-at-death.survivorship target.

The Human Mortality Database's life-table `dx` column IS the age-at-death
distribution (deaths at age x per 100,000 synthetic births), so the empirical
data drops directly into the target's canonical bins with no modeling choices
beyond country/year selection. HMD constructed data are CC BY 4.0 (see
https://www.mortality.org/Data/UserAgreement) — redistribution of the derived
binned histogram with attribution is permitted.

Usage:
    .venv/bin/python tools/convert_hmd_survivorship.py ~/Downloads/bltper_1x1.txt \
        --year 2019 --population "USA, both sexes"

Input format: an HMD 1x1 period life table (e.g. bltper_1x1.txt), whitespace-
separated columns: Year Age mx qx ax lx dx Lx Tx ex, with a two-line header.
Ages run 0..109 plus the open interval "110+".

Run from the repository root; rewrites targets/age-at-death.survivorship.json
in place, preserving the canonical support and bins.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = REPO_ROOT / "targets" / "age-at-death.survivorship.json"


def parse_dx(path: Path, year: int) -> list[tuple[float, float]]:
    """Return (age, dx) pairs for the requested year."""
    rows: list[tuple[float, float]] = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) < 7 or not parts[0].isdigit():
            continue
        if int(parts[0]) != year:
            continue
        age = float(parts[1].rstrip("+"))
        dx = float(parts[6])
        rows.append((age, dx))
    if not rows:
        raise SystemExit(f"no rows found for year {year} in {path}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("life_table", type=Path, help="HMD 1x1 life table file")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--population",
        required=True,
        help='human-readable population label, e.g. "USA, both sexes"',
    )
    args = parser.parse_args()

    target = json.loads(TARGET_PATH.read_text())
    bins = target["bins"]
    lo, hi = target["support"]

    rows = parse_dx(args.life_table, args.year)
    counts = [0.0] * (len(bins) - 1)
    for age, dx in rows:
        age = min(max(age, lo), hi)
        for i in range(len(counts)):
            if age < bins[i + 1] or i == len(counts) - 1:
                counts[i] += dx
                break
    total = sum(counts)
    target["probs"] = [count / total for count in counts]
    target["provisional"] = False
    target["source"] = (
        f"Human Mortality Database (mortality.org), {args.population}, period "
        f"life table 1x1, year {args.year}, dx column (deaths at age x per "
        f"100,000 births) summed into the canonical bins. HMD constructed "
        f"data are CC BY 4.0; redistribution of this derived histogram with "
        f"attribution is permitted per the HMD User Agreement."
    )
    target["generation"] = {
        "description": (
            f"Empirical: HMD {args.population} {args.year} life-table dx "
            f"column binned into the canonical {len(counts)} bins."
        ),
        "method": "hmd-life-table",
        "input_file": args.life_table.name,
        "year": args.year,
        "population": args.population,
        "dx_total": total,
        "regenerate_with": "tools/convert_hmd_survivorship.py",
    }
    TARGET_PATH.write_text(json.dumps(target, indent=2) + "\n")
    print(f"wrote {TARGET_PATH.name}: probs={[round(p, 4) for p in target['probs']]}")


if __name__ == "__main__":
    main()
