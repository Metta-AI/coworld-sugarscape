# SugarLang v1 reference

This is the normative language reference; for a guided introduction see the
[SugarLang tutorial](sugarlang-tutorial.md).

SugarLang is the declarative rules language for Sugarscape v3. A player submits
one ruleset before the simulation starts. The ruleset may override four DTL
agent traits and may replace how the agent ranks the candidate cells that DTL
already considers valid. SugarLang cannot add candidates, run loops, mutate the
world, access files, or consume random numbers.

## Ruleset shape

```json
{
  "version": 1,
  "traits": {
    "aggression": 0.0,
    "trade": 1.0,
    "lending": 0.0,
    "fertility": 1.0
  },
  "movement": [
    {
      "if": ["<", ["get", "agent.ttl"], 3],
      "score": ["get", "cell.welfare"]
    },
    {
      "score": [
        "-",
        ["get", "cell.welfare"],
        ["*", 0.4, ["get", "cell.distance"]],
        ["*", 2.0, ["get", "cell.pollution"]]
      ]
    }
  ]
}
```

The top-level value is either JSON `null` or an object. Object fields are:

- `version`: the integer `1`. It is required when `traits` or `movement` is
  present. `{}` and `{"version":1}` are accepted null rulesets.
- `traits`: optional trait overrides.
- `movement`: optional ordered movement decision list.

Unknown fields are errors. A player may submit either block, both blocks, or
neither.

## Null ruleset

JSON `null`, `{}`, and `{"version":1}` all mean the null ruleset. It applies no
trait overrides and uses DTL's stock `findBestCell` ranking path. A traits-only
ruleset also uses stock movement ranking.

The strict stock-DTL parity test disables reproduction and replacements so it
isolates this integration seam. Reproduction-enabled v3 runs intentionally
diverge from stock DTL when a newborn consumes the one required seeded 50/50
draw to select either parent's seat. That draw is part of the v3 rules, not a
fallback or an interpreter side effect.

## Traits

| SugarLang trait | DTL agent factor | Effect |
|---|---|---|
| `aggression` | `aggressionFactor` | Combat eligibility and perceived combat reward |
| `trade` | `tradeFactor` | Bilateral trade intensity; zero disables trade |
| `lending` | `lendingFactor` | Lending eligibility and interest |
| `fertility` | `fertilityFactor` | Reproduction eligibility and resource cost |

Trait values must be finite JSON numbers. When an agent spawns, the game clamps
each submitted value into that variant's `trait_ranges`. A degenerate range
locks a trait. Null rulesets retain the DTL-generated factor values.

## Movement decision list

`movement` is a non-empty array of rule objects. Each rule has a required
`score` expression and an optional `if` expression. The final rule must omit
`if`, so every valid candidate receives a score.

For every candidate cell independently, conditions are evaluated from top to
bottom. Zero is false and any nonzero value is true. The first matching rule
supplies that candidate's score. Conditions and unselected `if`, `and`, and `or`
branches are short-circuited.

The agent chooses the candidate with the greatest score. Ties go to the smaller
DTL travel distance, then to DTL's existing shuffled candidate order. SugarLang
does not change DTL's vision, movement range, occupancy checks, prey validity,
or retaliation filtering. Moving onto a valid occupied candidate retains DTL's
normal combat consequence.

## Expressions

An expression is either a finite JSON number or an operator array:

```json
["operator", "argument", "..."]
```

`["get", "feature.name"]` reads one feature. Strings, booleans, objects, JSON
`null`, and bare arrays are not expression literals.

### Operators and arity

| Operators | Arity | Semantics |
|---|---:|---|
| `+`, `*`, `min`, `max` | 2 or more | Left-to-right arithmetic/reduction |
| `-`, `/` | 2 or more | Left-to-right, so `["-",10,3,2]` is `5` |
| `abs`, `neg` | 1 | Absolute value and arithmetic negation |
| `pow` | 2 | Clamped exponentiation described below |
| `<`, `<=`, `>`, `>=`, `==`, `!=` | 2 | Return `1.0` when true, otherwise `0.0` |
| `and`, `or` | 2 or more | Short-circuit; return `1.0` or `0.0` |
| `not` | 1 | Return `1.0` only when its operand is zero |
| `if` | 3 | Condition, true expression, false expression |
| `get` | 1 feature name | Read a feature |

### Total numeric semantics

SugarLang evaluation always produces a finite float:

- Division is evaluated left-to-right. Encountering an exact zero divisor
  makes the entire division expression `0.0`.
- `pow(base, exponent)` first clamps `base` to `max(base, 0)`, then clamps the
  exponent into `[-8, 8]`. Invalid, overflowing, or non-finite output is `0.0`.
- Any NaN or infinity entering through runtime features is normalized to `0.0`.
- Any arithmetic result that becomes NaN or infinity is normalized to `0.0`.
- JSON NaN and infinity literals are rejected at submission.

These rules apply identically to the reference evaluator and compiled
expressions.

## Feature vocabulary

### Agent features

Agent features are memoized once for that agent's movement decision.

| Feature | Meaning |
|---|---|
| `agent.sugar` | Current sugar |
| `agent.spice` | Current spice |
| `agent.wealth` | Sugar plus spice |
| `agent.sugarMetabolism` | Effective sugar metabolism |
| `agent.spiceMetabolism` | Effective spice metabolism |
| `agent.vision` | Effective vision |
| `agent.movement` | Effective movement range |
| `agent.age` | Current age |
| `agent.ttl` | DTL `findTimeToLive()` result |
| `agent.mrs` | DTL marginal rate of substitution |

### Cell features

Cell slots are overwritten for each candidate without allocating a feature map.

| Feature | Meaning |
|---|---|
| `cell.sugar` | Sugar currently at the candidate |
| `cell.spice` | Spice currently at the candidate |
| `cell.pollution` | Candidate pollution |
| `cell.distance` | DTL travel distance |
| `cell.occupied` | `1.0` when occupied, otherwise `0.0` |
| `cell.preyWealth` | Occupant sugar plus spice, or zero |
| `cell.welfare` | DTL's original candidate welfare before SugarLang scoring |

`cell.welfare` includes the stock effects of metabolism, lookahead, pollution,
eligible combat loot, aggression, and configured group preferences.

### World features and time semantics

World features are memoized once at the start of a tick. Every agent activated
during that tick sees the same world-feature snapshot.

| Feature | Time semantics |
|---|---|
| `world.timestep` | Current tick T |
| `world.population` | Population at the start of current tick T |
| `world.gini` | Completed DTL statistic from tick T-1 |
| `world.meanWealth` | Completed DTL statistic from tick T-1 |

At tick 1, Gini and mean wealth come from DTL's initialized tick-0 statistics.
The game does not recompute macro statistics during sequential agent activation.

## Submission budgets

- Maximum UTF-8 JSON payload size: 32,768 bytes. Whitespace and all other wire
  bytes count.
- Maximum expression nodes across all movement conditions and scores: 256.
- Maximum expression depth: 16, counting a literal or operator at the expression
  root as depth 1.
- A numeric literal, `get`, or other operator occurrence counts as one node.
  The feature-name string inside `get`, rule objects, trait values, and structural
  JSON fields do not count as expression nodes.

Validation reports all safely discoverable errors with JSON-style paths. Invalid
rulesets are never compiled or evaluated.

## Compilation and determinism

Expressions compile once at submission into nested Python closures. Feature
names resolve to fixed numeric slots at compile time. World slots are filled
once per tick, agent slots once per activation, and cell slots in place per
candidate. The compiled hot path allocates no lists, dictionaries, or tuples per
evaluation.

The simulation uses DTL's seeded global random stream. SugarLang evaluation is
pure and consumes no randomness. Scenario selection uses
`seed % len(scenario_pool)` and consumes no simulation random number. When DTL's
replacement target requires K agents, v3 pairs them with the first K agents that
died during that tick in DTL removal order.

Replaying a recorded non-negative seed with the same effective config and
rulesets reproduces the episode under the pinned interpreter and
`PYTHONHASHSEED=0`. The byte-determinism contract covers the canonical results
payload with `timings` removed; real wall-clock timings are validated
structurally rather than expected to repeat byte-for-byte.

