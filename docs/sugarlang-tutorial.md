# SugarLang tutorial: from a target to a ruleset

This is the guided path from "I have a target" to "I have a ruleset worth
submitting." The normative language reference is [`RULES.md`](RULES.md) —
everything here links back to it. If you prefer editing visually, everything
in this tutorial can be done in the
[Ruleset Studio](../ruleset-studio/README.md) instead of a text editor.

## What you actually control

A ruleset does exactly two things:

1. **Traits** — override up to four societal dials: `aggression`, `trade`,
   `lending`, `fertility`. These change what agents are *willing* to do.
2. **Movement** — replace how agents *rank* the candidate cells the engine
   already considers valid. You cannot add candidates, see farther, or move
   agents directly; you only decide what "the best cell" means.

Everything else — combat resolution, trade prices, disease, reproduction —
is the engine's business, steered only through those two levers. You are
writing a law, then living with its consequences for 1,000 ticks.

## Reading a target

Take `wealth.skewed-gini-0.5` (`targets/wealth.skewed-gini-0.5.json`). Its
`kind` is `distribution` and its `variable` is `wealth`: at the end of the
episode, every living agent's sugar-plus-spice is pooled over the final
measurement window into a histogram, and your score is how close that
histogram lands to the target's — a right-skewed wealth curve with Gini 0.5.
A few rich agents, a long tail of poor ones — but *alive* poor ones: an
extinct society measures nothing and scores zero.

So the target hands you a two-part problem: **keep a society alive**, and
**shape who ends up holding the wealth**. (`TARGETS.md` has the full scoring
math; the one-line version is that `w1-hyperbolic/1` turns the
Wasserstein-1 distance between the two histograms into a 0–1 score.)

## Step 1: start from survival

The null ruleset (`{}`) is a legal submission: stock engine behavior. Your
first real move is a movement list that names what agents should value. The
simplest sensible law is one rule:

```json
{
  "version": 1,
  "movement": [
    { "score": ["get", "cell.welfare"] }
  ]
}
```

`cell.welfare` is the engine's own estimate of how good a candidate cell is
for this agent (metabolism, lookahead, pollution, loot, and group
preferences included — see the feature tables in `RULES.md`). A movement
list must always end with an unconditional rule, and this one is only that:
every candidate gets a score, the best score wins, ties break toward the
shorter move.

Run it and look at the result. This is the habit the whole game rewards: a
full scored episode takes seconds locally (`docker compose up`, the Ruleset
Studio, or `coworld run-episode`), so every idea you have should meet the
world before it meets your opinion of it.

## Step 2: add a guarded rule

Rules above the final one carry an `if` condition and fire first when they
match. The classic guard: agents about to starve should stop being clever.

```json
{
  "version": 1,
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
        ["*", 2, ["get", "cell.pollution"]]
      ]
    }
  ]
}
```

Read it top to bottom, per candidate: *if I would die within three ticks,
take the plainly best cell; otherwise prefer welfare, but discount distant
cells a little and polluted cells a lot.* This is
[`rulesets/worked-example.json`](../rulesets/worked-example.json) — a
survival-first law with mild efficiency preferences.

Conditions evaluate per candidate, first match wins, and every expression
is total: division by zero yields `0.0`, overflow normalizes to `0.0`,
comparisons return `1.0`/`0.0` (`RULES.md` § Total numeric semantics). You
cannot crash an expression; you can only make it mean something you didn't
intend.

## Step 3: shape the outcome with traits

Now aim at the *skew*. Traits are hypotheses about which social forces
concentrate or spread wealth — for instance:

```json
{
  "version": 1,
  "traits": { "aggression": 0, "trade": 1, "lending": 1, "fertility": 1 },
  "movement": [
    { "score": ["get", "cell.welfare"] }
  ]
}
```

Plausible reasoning: lending lets accumulated wealth earn interest (richer
get richer — more skew); trade keeps poor agents alive to populate the
tail; zero aggression avoids the churn of combat losses; fertility keeps
the population up so the histogram has mass. But that's a hypothesis, not a
result — trait values are also clamped into the variant's `trait_ranges`,
so what you ask for may not be what the world allows. Run it, put the
measured histogram next to the target, and see *which direction* you
missed: too equal means the concentrating forces need more room, too
brutal means survival needs more protection. Change one thing, run again.

Movement and traits compose: a welfare-greedy movement law amplifies
whatever inequality the traits permit, because stronger agents win the
better cells and compound the lead.

## Budgets: the shape of the medium

Submissions are capped at 256 expression nodes, depth 16, and 32,768 bytes
(`RULES.md` § Submission budgets). Numbers and each operator or `get` count
as nodes; feature-name strings and the rule objects themselves don't.
That's roomy for a handful of thoughtful rules and cramped for a decision
tree pretending to be a neural net — which is the point. Validation tells
you exactly where you stand:

```sh
.venv/bin/python -c "
import sys
sys.path.insert(0, 'src')
from coworld.ruleset import parse_ruleset
result = parse_ruleset(open('rulesets/worked-example.json').read())
print(result.errors if result.errors else
      f'valid: {result.node_count} nodes, {result.byte_count} bytes')
"
```

(or just watch the budget meters in the Ruleset Studio, which runs the same
validator on every edit).

## The Commonwealth variation

Commonwealth flips the exercise. There is no target histogram to match and
no drawn world: the same canonical world every episode, and your ruleset is
a **constitution** — fixed, submitted verbatim every time, scored by the
summed wellness of every citizen alive at the final tick. Wellness is the
engine's own composite happiness, normalized to `[0, 1]`; the sum means
population and per-capita flourishing both pay.

Craft it like an artifact, not a generator: iterate in the Studio against
local runs, and read
[`designs/2026-08-18-commonwealth-league.md`](designs/2026-08-18-commonwealth-league.md)
first — it documents the league's deliberately accepted degeneracies, which
is to say: the currently legal ways to be clever.

## The loop, named

1. Read the target; say out loud what society it describes.
2. Write the simplest law that could produce that society.
3. Run it locally; compare measured vs target.
4. Change one thing for a reason; run again.
5. When local sweeps stop improving, submit — and let the ladder tell you
   what the pool really thinks.
