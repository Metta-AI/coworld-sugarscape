#!/usr/bin/env python3
"""Regenerate engine-grounded target histograms from GAS-referenced DTL runs.

Family A targets (see docs/TARGETS.md and the 2026-08-11 sourcing research)
have no published tabulated data anywhere — Epstein & Axtell 1996 and every
replication shipped figures only. The honest primary source is therefore the
vendored DTL engine itself: run the literature-referenced example config for
many seeds under stock DTL semantics (the "none" greedy decision model from
DTL's own __main__ defaults — NOT the bentham data-collection profile in the
shipped config.json), pool the target variable over the final measurement
window, and bin into the target's existing canonical support/bins.

Each regenerated targets/<id>.json keeps its id/variable/scope/support/bins/
window and gets: new probs, provisional: false, and full provenance in
source/generation (engine commit, config file, seeds, ticks, validation stats).

Usage:
    .venv/bin/python tools/generate_targets.py [--seeds 30] [--jobs 8] \
        [--only wealth.skewed-gini-0.5,...] [--dry-run]

Run from the repository root. Writes targets/*.json in place (--dry-run to
only print the summary table).
"""

from __future__ import annotations

import argparse
import ast
import json
import random
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

ENGINE_COMMIT = "a46ec6ff909e2bc73a4c9e9f36b2aed160eccad8"
WINDOW_TICKS = 100


@dataclass(frozen=True)
class GenerationSpec:
    """One target's generation recipe: which GAS config, what to sample."""

    target_id: str
    example_config: str  # under src/sugarscape/examples/
    variable: str  # sampler key, and must match the target file's variable
    gas_reference: str
    overrides: dict  # applied on top of the example config
    # Optional acceptance check on pooled run stats: (name, fn(stats) -> bool).
    validation: tuple[str, str] | None = None  # (description, python expr)


SPECS = [
    GenerationSpec(
        target_id="wealth.skewed-gini-0.5",
        example_config="agent_replacement.json",
        variable="wealth",
        gas_reference="GAS ch. II, Animation II-4 region: {G1},{M},{R[60,100]}",
        overrides={},
        validation=(
            "final-tick Gini within [0.40, 0.60] (GAS reports ~0.5)",
            "0.40 <= stats['mean_final_gini'] <= 0.60",
        ),
    ),
    GenerationSpec(
        target_id="population.carrying-capacity",
        example_config="constant_growback.json",
        variable="population",
        gas_reference="GAS ch. II: {G1},{M} carrying capacity (Animation II-2 region)",
        # GAS's carrying-capacity result uses immortal agents; the example
        # config's finite lifespans (with no reproduction or replacement)
        # otherwise empty the world by tick ~100 through aging alone.
        overrides={"agentMaxAge": [-1, -1]},
    ),
    GenerationSpec(
        target_id="price.equilibrium",
        example_config="trade_basic.json",
        variable="mean_trade_price",
        gas_reference="GAS ch. IV, Figures IV-3/IV-4: {G1},{M},{T} price convergence",
        overrides={},
        validation=(
            "pooled mean trade price within [0.8, 1.25] (GAS equilibrium ~1)",
            "0.8 <= stats['pooled_mean'] <= 1.25",
        ),
    ),
    GenerationSpec(
        target_id="tribe.convergence",
        example_config="cultural_tagging.json",
        variable="majority_tribe_share",
        gas_reference="GAS ch. III, rule K: cultural convergence",
        overrides={},
    ),
    # The disease targets were shelved on 2026-08-11: no DTL configuration we
    # found sustains a stable endemic equilibrium (immune systems eradicate in
    # ~10 ticks, or penalties/transmission collapse the population — see
    # docs/TARGETS.md). Revisit with a reintroduction mechanism if disease
    # variants return.
    GenerationSpec(
        target_id="wealth.egalitarian",
        example_config="agent_replacement.json",
        variable="wealth",
        gas_reference=(
            "Counterfactual (no GAS or empirical anchor): equalized endowments "
            "and per-tick universal income compress the wealth distribution"
        ),
        overrides={
            "agentVision": [3, 3],
            "agentMovement": [2, 2],
            "agentSugarMetabolism": [3, 3],
            "agentMaxAge": [30, 45],
            "agentStartingSugar": [20, 25],
            "agentUniversalSugar": [1, 1],
            "environmentUniversalSugarIncomeInterval": 1,
            # DTL quirk: the universal-income endowment machinery assigns
            # universalSpice to half the agents even under [0, 0]; a nonzero
            # spice interval avoids findTimeToLive's division by zero and is
            # otherwise inert (spice metabolism is 0 in this config).
            "environmentUniversalSpiceIncomeInterval": 1,
        },
        # Targets need not be perfectly reachable to be targets (decided
        # 2026-08-11) — the point is a compressed counterfactual to aim at.
        # The gate only rejects runs that fail to compress at all (default
        # dynamics give ~0.47).
        validation=(
            "final-tick Gini <= 0.35 (meaningfully compressed vs the ~0.47 default)",
            "stats['mean_final_gini'] <= 0.35",
        ),
    ),
    GenerationSpec(
        target_id="tribe.diversity",
        example_config="cultural_tagging.json",
        variable="majority_tribe_share",
        gas_reference=(
            "Counterfactual (GAS rule K converges): quadrant-separated tribes "
            "with slowed mixing hold a stable multi-tribe split"
        ),
        overrides={
            "environmentMaxTribes": 2,
            "environmentTribePerQuadrant": True,
            # Two opposite starting corners: with tribe-per-quadrant, DTL sets
            # tribe = starting-quadrant index, so quadrant count must equal
            # environmentMaxTribes.
            "environmentStartingQuadrants": [1, 3],
        },
        validation=(
            "pooled mean majority share <= 0.65 (diversity must persist)",
            "stats['pooled_mean'] <= 0.65",
        ),
    ),
]


def load_internal_defaults() -> dict:
    """Extract DTL's __main__ default configuration dict via AST.

    The GAS example configs are deltas over DTL's *internal* defaults
    (agentDecisionModels ["none"], aggression [0,0], ...), not over the
    shipped config.json data-collection profile (bentham, aggression [1,1]).
    The dict is a pure literal inside the __main__ block, so ast.literal_eval
    recovers it without executing the script.
    """
    source = (REPO_ROOT / "src" / "sugarscape" / "sugarscape.py").read_text()
    module = ast.parse(source)
    for node in ast.walk(module):
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(t, ast.Name) and t.id == "configuration" for t in node.targets
        ) and isinstance(node.value, ast.Dict):
            return ast.literal_eval(node.value)
    raise RuntimeError("could not locate the internal defaults dict in sugarscape.py")


def build_run_config(spec: GenerationSpec, seed: int) -> dict:
    defaults = load_internal_defaults()
    example = json.loads(
        (REPO_ROOT / "src" / "sugarscape" / "examples" / spec.example_config).read_text()
    )
    options = example.get("sugarscapeOptions", example)
    config = dict(defaults)
    config.update(options)
    config.update(spec.overrides)
    config.update(
        {
            "seed": seed,
            "headlessMode": True,
            "logfile": None,
            "agentLogfile": None,
            "screenshots": False,
            "profileMode": False,
            "debugMode": ["none"],
            "keepAliveAtEnd": False,
            "keepAlivePostExtinction": False,
        }
    )
    return config


def run_one_seed(args: tuple) -> dict:
    """Run one stock-DTL episode and return window samples + run stats.

    Executed in a worker process. Mirrors the stock runSimulation() loop
    (tick-zero updateRuntimeStats, then doTimestep until done) without GUI,
    logging, or the coworld edge — this is vanilla DTL, greedy "none" model.
    """
    spec_index, seed = args
    spec = SPECS[spec_index]
    from sugarscape import sugarscape as dtl

    config = build_run_config(spec, seed)
    random.seed(seed)
    sim = dtl.Sugarscape(config)
    sim.updateRuntimeStats()

    timesteps = int(config["timesteps"])
    window_start = timesteps - WINDOW_TICKS
    samples: list[float] = []
    final_gini = 0.0

    for tick in range(1, timesteps + 1):
        if not sim.agents:
            break
        sim.doTimestep()
        population = len(sim.agents)
        final_gini = sim.runtimeStats.get("giniCoefficient", 0.0)
        if tick <= window_start:
            continue
        if spec.variable == "wealth":
            samples.extend(agent.sugar + agent.spice for agent in sim.agents)
        elif spec.variable == "population":
            samples.append(float(population))
        elif spec.variable == "majority_tribe_share":
            if population:
                largest = Counter(agent.tribe for agent in sim.agents).most_common(1)
                samples.append(largest[0][1] / population)
        elif spec.variable == "sick_fraction":
            if population:
                sick = sum(1 for agent in sim.agents if agent.isSick())
                samples.append(sick / population)
        elif spec.variable == "mean_trade_price":
            price = sim.runtimeStats.get("meanTradePrice", 0.0)
            samples.append(float(price))
        else:
            raise ValueError(f"no sampler for variable {spec.variable!r}")

    return {
        "seed": seed,
        "samples": samples,
        "final_population": len(sim.agents),
        "final_gini": final_gini,
        "completed_ticks": min(timesteps, tick),
    }


def bin_samples(samples: list[float], support: list[float], bins: list[float]) -> list[float]:
    """Histogram samples into the target's canonical bins, clamping to support."""
    lo, hi = support
    counts = [0] * (len(bins) - 1)
    for value in samples:
        value = min(max(value, lo), hi)
        # Right-inclusive last bin; linear scan is fine at this scale.
        for i in range(len(counts)):
            if value < bins[i + 1] or i == len(counts) - 1:
                counts[i] += 1
                break
    total = sum(counts)
    if total == 0:
        raise RuntimeError("no samples fell inside the support")
    return [count / total for count in counts]


def regenerate(spec: GenerationSpec, seeds: int, jobs: int, dry_run: bool) -> dict:
    target_path = REPO_ROOT / "targets" / f"{spec.target_id}.json"
    target = json.loads(target_path.read_text())
    assert target["variable"] == spec.variable.replace("-", "_") or target[
        "variable"
    ] == spec.variable, (
        f"{spec.target_id}: spec variable {spec.variable!r} does not match "
        f"target file variable {target['variable']!r}"
    )

    seed_list = list(range(1, seeds + 1))
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        runs = list(pool.map(run_one_seed, [(SPECS.index(spec), s) for s in seed_list]))

    pooled = [value for run in runs for value in run["samples"]]
    survived = [run for run in runs if run["final_population"] > 0]
    stats = {
        "seeds": seeds,
        "seeds_survived": len(survived),
        "pooled_samples": len(pooled),
        "pooled_mean": (sum(pooled) / len(pooled)) if pooled else 0.0,
        "mean_final_gini": (
            sum(r["final_gini"] for r in survived) / len(survived) if survived else 0.0
        ),
        "mean_final_population": (
            sum(r["final_population"] for r in runs) / len(runs) if runs else 0.0
        ),
    }

    accepted = stats["pooled_samples"] > 0
    validation_note = "pooled_samples > 0"
    if accepted and spec.validation is not None:
        validation_note, expression = spec.validation
        accepted = bool(eval(expression, {"stats": stats}))  # noqa: S307 - own literal

    result = {"target_id": spec.target_id, "stats": stats, "accepted": accepted,
              "validation": validation_note}
    if not accepted or dry_run:
        return result

    target["probs"] = bin_samples(pooled, target["support"], target["bins"])
    target["provisional"] = False
    target["source"] = (
        f"Generated from the vendored DTL Sugarscape engine (commit {ENGINE_COMMIT}, "
        f"Unlicense) running examples/{spec.example_config} under DTL internal "
        f"defaults (decision model 'none'). Literature anchor: {spec.gas_reference} "
        f"(Epstein & Axtell 1996). No tabulated data for this result was ever "
        f"published; the engine run is the primary source per the 2026-08-11 "
        f"sourcing research."
    )
    target["generation"] = {
        "description": (
            f"Engine run: examples/{spec.example_config} under DTL internal "
            f"defaults ('none' decision model), {seeds} seeds, variable pooled "
            f"over the final {WINDOW_TICKS} ticks and binned canonically."
        ),
        "method": "engine-run",
        "engine_commit": ENGINE_COMMIT,
        "example_config": spec.example_config,
        "decision_model": "none (DTL internal defaults)",
        "seeds": seeds,
        "window_ticks": WINDOW_TICKS,
        "validation": validation_note,
        "stats": {k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items()},
        "generated": "2026-08-11",
        "regenerate_with": "tools/generate_targets.py",
    }
    target_path.write_text(json.dumps(target, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--only", type=str, default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    wanted = set(filter(None, args.only.split(",")))
    results = []
    for spec in SPECS:
        if wanted and spec.target_id not in wanted:
            continue
        print(f"generating {spec.target_id} from {spec.example_config} "
              f"({args.seeds} seeds)...", flush=True)
        results.append(regenerate(spec, args.seeds, args.jobs, args.dry_run))
        r = results[-1]
        s = r["stats"]
        print(
            f"  {'ACCEPTED' if r['accepted'] else 'REJECTED'} | "
            f"samples={s['pooled_samples']} mean={s['pooled_mean']:.3f} "
            f"gini={s['mean_final_gini']:.3f} "
            f"survived={s['seeds_survived']}/{s['seeds']} "
            f"pop_final~{s['mean_final_population']:.0f}",
            flush=True,
        )
        if not r["accepted"]:
            print(f"  validation: {r['validation']}", flush=True)

    print("\n| target | accepted | samples | pooled mean | gini | survived |")
    print("|---|---|---|---|---|---|")
    for r in results:
        s = r["stats"]
        print(
            f"| `{r['target_id']}` | {r['accepted']} | {s['pooled_samples']} "
            f"| {s['pooled_mean']:.3f} | {s['mean_final_gini']:.3f} "
            f"| {s['seeds_survived']}/{s['seeds']} |"
        )


if __name__ == "__main__":
    main()
