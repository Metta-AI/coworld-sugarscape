#!/usr/bin/env python3
"""Estimate how closely any SugarLang ruleset can approach a variant's target.

A small evolutionary search over SugarLang rulesets: random population (seeded
with the null ruleset and the greedy-welfare ruleset so the result can never
fall below the baseline), fitness = mean episode match score over a fixed seed
set, tournament selection, subtree crossover, and point mutation. The best
score found is a LOWER BOUND on the variant/target pair's achievable ceiling —
this tool can demonstrate reachability, never disprove it. Pair the ceiling
with the null-ruleset floor to judge whether a pair has a real skill gradient
before putting it in ranked rotation.

Multi-seat variants are probed from seat 0 with every other seat playing the
null ruleset.

Usage:
    .venv/bin/python tools/probe_reachability.py --variant solo-wealth \
        [--target wealth.skewed-gini-0.5] [--population 24] [--generations 20] \
        [--seeds 11,42] [--jobs 8] [--rng-seed 1] [--out build/probe]

    .venv/bin/python tools/probe_reachability.py --config path/to/config.json ...

Run from the repository root. Writes <out>/report.json and <out>/best-ruleset.json.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from coworld.episode import run_episode  # noqa: E402
from coworld.ruleset import DEFAULT_LIMITS, FEATURE_NAMES, validate_ruleset  # noqa: E402

GREEDY_RULESET = {"version": 1, "movement": [{"score": ["get", "cell.welfare"]}]}

_NARY = ("+", "-", "*", "min", "max")
_COMPARE = ("<", "<=", ">", ">=")
# Kept intentionally smaller than the full operator set: division, pow, and
# logic ops add little to random search but bloat trees; mutation can still
# never introduce them, which keeps evolved winners easy to read.

_TRAIT_DEFAULTS = {
    "aggression": (0.0, 1.0),
    "trade": (0.0, 1.0),
    "lending": (0.0, 1.0),
    "fertility": (0.5, 1.5),
}


def random_constant(rng: random.Random) -> float:
    return round(rng.choice([rng.uniform(0, 3), rng.uniform(0, 30), float(rng.randint(0, 10))]), 2)


def random_expression(rng: random.Random, depth: int) -> object:
    """A random SugarLang score expression with bounded depth."""

    if depth <= 0 or rng.random() < 0.35:
        if rng.random() < 0.6:
            return ["get", rng.choice(FEATURE_NAMES)]
        return random_constant(rng)
    operator = rng.choice(_NARY)
    arity = rng.choice((2, 2, 3))
    return [operator, *(random_expression(rng, depth - 1) for _ in range(arity))]


def random_condition(rng: random.Random, depth: int) -> object:
    return [rng.choice(_COMPARE), random_expression(rng, depth), random_expression(rng, depth)]


def random_ruleset(rng: random.Random, trait_ranges: dict[str, tuple[float, float]]) -> dict:
    movement = []
    if rng.random() < 0.4:
        movement.append(
            {"if": random_condition(rng, 2), "score": random_expression(rng, 3)}
        )
    movement.append({"score": random_expression(rng, 3)})
    ruleset: dict = {"version": 1, "movement": movement}
    if trait_ranges and rng.random() < 0.7:
        ruleset["traits"] = {
            name: round(rng.uniform(low, high), 2)
            for name, (low, high) in trait_ranges.items()
            if rng.random() < 0.6
        } or None
        if ruleset["traits"] is None:
            del ruleset["traits"]
    return ruleset


def _expression_nodes(expression: object, path: tuple[int, ...] = ()) -> list[tuple[tuple[int, ...], object]]:
    nodes = [(path, expression)]
    if isinstance(expression, list) and expression and expression[0] != "get":
        for index, child in enumerate(expression[1:], start=1):
            nodes.extend(_expression_nodes(child, (*path, index)))
    return nodes


def _replace_at(expression: object, path: tuple[int, ...], replacement: object) -> object:
    if not path:
        return replacement
    updated = copy.deepcopy(expression)
    cursor = updated
    for index in path[:-1]:
        cursor = cursor[index]
    cursor[path[-1]] = replacement
    return updated


def mutate(rng: random.Random, ruleset: dict, trait_ranges: dict) -> dict:
    child = copy.deepcopy(ruleset)
    rules = child["movement"]
    choice = rng.random()
    if choice < 0.5:
        # Replace a random subtree of a random rule's score expression.
        rule = rng.choice(rules)
        nodes = _expression_nodes(rule["score"])
        path, node = rng.choice(nodes)
        if isinstance(node, (int, float)) and rng.random() < 0.5:
            replacement: object = round(node * rng.uniform(0.5, 1.8) + rng.uniform(-1, 1), 2)
        else:
            replacement = random_expression(rng, 2)
        rule["score"] = _replace_at(rule["score"], path, replacement)
    elif choice < 0.7 and trait_ranges:
        traits = child.setdefault("traits", {})
        name = rng.choice(sorted(trait_ranges))
        low, high = trait_ranges[name]
        traits[name] = round(rng.uniform(low, high), 2)
    elif choice < 0.85 and len(rules) == 1:
        # Grow a conditional rule in front of the unconditional tail.
        rules.insert(0, {"if": random_condition(rng, 2), "score": random_expression(rng, 3)})
    else:
        # Shrink back to the unconditional tail, or reroll it entirely.
        if len(rules) > 1 and rng.random() < 0.5:
            del rules[0]
        else:
            rules[-1] = {"score": random_expression(rng, 3)}
    return child


def crossover(rng: random.Random, left: dict, right: dict) -> dict:
    child = copy.deepcopy(left)
    donor_rule = rng.choice(right["movement"])
    donor_nodes = _expression_nodes(donor_rule["score"])
    _, donor_subtree = rng.choice(donor_nodes)
    target_rule = rng.choice(child["movement"])
    nodes = _expression_nodes(target_rule["score"])
    path, _ = rng.choice(nodes)
    target_rule["score"] = _replace_at(target_rule["score"], path, copy.deepcopy(donor_subtree))
    if "traits" in right and rng.random() < 0.5:
        child.setdefault("traits", {}).update(copy.deepcopy(right["traits"]))
    return child


def is_valid(ruleset: dict) -> bool:
    return not validate_ruleset(ruleset, DEFAULT_LIMITS).errors


def _evaluate_one(args: tuple) -> float:
    """Worker: one episode, probe genome in seat 0, nulls elsewhere."""

    config, genome, seed = args
    episode_config = dict(config)
    episode_config["seed"] = seed
    rulesets: list[object] = [genome] + [None] * (int(config["seats"]) - 1)
    results, _replay, _timings = run_episode(
        episode_config, rulesets, emit_timing_logs=False
    )
    return float(results["scores"][0])


def evaluate_population(
    pool: ProcessPoolExecutor,
    config: dict,
    population: list[dict | None],
    seeds: list[int],
) -> list[float]:
    jobs = [(config, genome, seed) for genome in population for seed in seeds]
    scores = list(pool.map(_evaluate_one, jobs))
    fitness = []
    for index in range(len(population)):
        chunk = scores[index * len(seeds) : (index + 1) * len(seeds)]
        fitness.append(sum(chunk) / len(chunk))
    return fitness


def tournament(rng: random.Random, population: list, fitness: list[float], size: int = 3):
    contenders = rng.sample(range(len(population)), min(size, len(population)))
    return population[max(contenders, key=lambda index: fitness[index])]


def load_config(args: argparse.Namespace) -> dict:
    if args.config:
        config = json.loads(Path(args.config).read_text())
    else:
        manifest = json.loads((REPO_ROOT / "coworld_manifest.json").read_text())
        for variant in manifest["variants"]:
            if variant.get("id") == args.variant:
                config = dict(variant["game_config"])
                break
        else:
            raise SystemExit(f"variant {args.variant!r} not found in coworld_manifest.json")
    seats = int(config.get("seats", 1))
    config.setdefault("tokens", [f"probe-{index}" for index in range(seats)])
    if args.target:
        config["targets"] = [args.target] + list(config.get("targets", []))[1:]
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--variant", help="variant id from coworld_manifest.json")
    source.add_argument("--config", help="path to a game config JSON")
    parser.add_argument("--target", help="override the probed seat's target id")
    parser.add_argument("--population", type=int, default=24)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--seeds", default="11,42", help="comma-separated episode seeds")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--rng-seed", type=int, default=1, help="probe's own RNG seed")
    parser.add_argument("--out", default="build/probe")
    args = parser.parse_args()

    config = load_config(args)
    seeds = [int(part) for part in args.seeds.split(",")]
    rng = random.Random(args.rng_seed)
    trait_ranges = {
        name: tuple(bounds)
        for name, bounds in (config.get("trait_ranges") or _TRAIT_DEFAULTS).items()
    }

    population: list[dict | None] = [None, GREEDY_RULESET]
    while len(population) < args.population:
        candidate = random_ruleset(rng, trait_ranges)
        if is_valid(candidate):
            population.append(candidate)

    history = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        fitness = evaluate_population(pool, config, population, seeds)
        baseline = fitness[0]  # the null ruleset's mean score on the same seeds
        best_genome, best_fitness = max(
            zip(population, fitness), key=lambda pair: pair[1]
        )
        for generation in range(1, args.generations + 1):
            next_population: list[dict | None] = [copy.deepcopy(best_genome)]  # elitism
            while len(next_population) < args.population:
                if rng.random() < 0.35:
                    left = tournament(rng, population, fitness)
                    right = tournament(rng, population, fitness)
                    child = crossover(rng, left or GREEDY_RULESET, right or GREEDY_RULESET)
                else:
                    parent = tournament(rng, population, fitness)
                    child = mutate(rng, parent or GREEDY_RULESET, trait_ranges)
                if is_valid(child):
                    next_population.append(child)
            population = next_population
            fitness = evaluate_population(pool, config, population, seeds)
            generation_best = max(fitness)
            if generation_best > best_fitness:
                best_fitness = generation_best
                best_genome = population[fitness.index(generation_best)]
            history.append(
                {
                    "generation": generation,
                    "best": round(generation_best, 4),
                    "mean": round(sum(fitness) / len(fitness), 4),
                }
            )
            print(
                f"gen {generation:>3}: best={generation_best:.4f} "
                f"mean={sum(fitness) / len(fitness):.4f} ceiling≥{best_fitness:.4f}",
                flush=True,
            )

    out_dir = REPO_ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "variant": args.variant or args.config,
        "target": config.get("targets", [None])[0],
        "seeds": seeds,
        "population": args.population,
        "generations": args.generations,
        "rng_seed": args.rng_seed,
        "baseline_null": round(baseline, 4),
        "ceiling_lower_bound": round(best_fitness, 4),
        "skill_spread": round(best_fitness - baseline, 4),
        "history": history,
        "note": (
            "ceiling_lower_bound is what an automated search achieved; the true "
            "ceiling may be higher. This tool can demonstrate reachability, "
            "never disprove it."
        ),
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out_dir / "best-ruleset.json").write_text(json.dumps(best_genome, indent=2) + "\n")
    print(
        f"\nfloor (null) {baseline:.4f} → ceiling ≥ {best_fitness:.4f} "
        f"(spread {best_fitness - baseline:+.4f})\n"
        f"report: {out_dir / 'report.json'}\nbest ruleset: {out_dir / 'best-ruleset.json'}"
    )


if __name__ == "__main__":
    main()
