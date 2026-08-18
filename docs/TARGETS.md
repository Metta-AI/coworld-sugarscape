# Sugarscape v3 target catalog

Targets are normalized histograms describing outcomes that a player's SugarLang
ruleset should grow. The shipped catalog lives in `targets/`, one JSON object per
file. Four targets are **engine-generated** (2026-08-11): no tabulated data for
the classic Sugarscape results was ever published, so the honest primary source
is the vendored DTL engine itself — `tools/generate_targets.py` runs the
GAS-referenced example configs under DTL's internal defaults (greedy `"none"`
decision model) for 30 seeds, pools the variable over the final 100 ticks, and
bins canonically. Those files carry `"provisional": false` and full engine-run
provenance in `generation`. The remaining five are **provisional parametric
approximations** flagged `"provisional": true`, each identifying its parametric
family and generation recipe.

## Schema

A target contains:

- `id`: stable catalog identifier.
- `variable`: measured variable name.
- `scope`: `global` or `seat`. Omitted scope defaults to `global`; all shipped
  targets use global scope.
- `support`: inclusive lower and upper measurement bounds.
- `bins`: strictly increasing edges beginning and ending at the support bounds.
- `probs`: one normalized probability per bin interval.
- `window`: nominal number of final ticks to pool. The episode's effective
  `measurement_window` replaces this value when targets are assigned.
- `source`: honest provenance, including whether source data was digitized.
- `provisional`: whether the probabilities are placeholders.
- `generation`: parametric family, parameters, and a plain-language generation
  description.

All targets for one variable must use identical support and bin edges. Catalog
loading rejects inconsistencies. Samples outside the support clamp into the
first or last bin.

## Measured variables

| Variable | Recipe |
|---|---|
| `wealth` | Pool each living agent's sugar plus spice over the final window. |
| `age` | Pool each living agent's age over the final window, using the same canonical support and bins as `age_at_death`. This measurement-only variable has no shipped target yet. |
| `population` | One living-agent count per tick. |
| `age_at_death` | Pool death-event ages captured before DTL clears its death list. |
| `majority_tribe_share` | One largest-tribe population share per tick. |
| `sick_fraction` | One fraction of living agents with any disease per tick. |
| `mean_trade_price` | One mean active-trader price per tick; zero when agents live but no trade occurs. |

Every variable is measured globally and independently for each seat, regardless
of which variables the episode targets. Per-agent and death-event measurements
with no samples are marked empty. Population zero remains a real scalar sample.

## Scoring

The ranked method is `w1-hyperbolic/1`. First compute raw Wasserstein-1 distance
`D` from the two cumulative histograms, weighted by bin width. Its units are the
measured variable's units; it is not divided by the declared support.

The target supplies its own characteristic scale. Choose the leftmost median
bin `i*` (equivalently, the smallest-index point mass minimizing W1 to the
target), then compute:

```text
S = max(W1(point_mass_i*, target), width(i*))
score = S / (S + D)
```

The first term is the target's binned mean absolute deviation from its median.
The bin-width floor defines a positive resolution for a one-bin target. Thus an
exact match scores 1, one characteristic scale of transport scores 0.5, and
larger errors approach zero without losing their ordering to a clipped plateau.
With unequal bin widths, leftmost median tie-breaking is part of the scoring
contract because the chosen bin determines the floor.

Results report `raw_w1`, `w1_scale`, and base-2 Jensen-Shannon divergence as
diagnostics. Jensen-Shannon is not part of the ranked score because it does not
encode distance between bins. An empty target measurement scores zero, reports
`raw_w1: null`, and sets `empty_measurement: true`.

Replays recorded before this method identifier use legacy `w1-support/1` when
the viewer computes counterfactual target scores. Unknown identifiers fail
closed rather than being guessed. See the full decision record in
[`docs/designs/2026-08-18-w1-scoring-v2.md`](designs/2026-08-18-w1-scoring-v2.md).

## Shipped targets

Engine-generated (`tools/generate_targets.py`; validation stats in each file's
`generation.stats`):

- `wealth.skewed-gini-0.5` — `examples/agent_replacement.json` ({G1},{M},{R});
  measured Gini 0.472 vs GAS's ≈0.5
- `population.carrying-capacity` — `examples/constant_growback.json` with
  immortal agents (GAS's carrying-capacity setup); mean population 223 vs the
  book's ≈224
- `price.equilibrium` — `examples/trade_basic.json`; pooled mean price 1.11 vs
  GAS's equilibrium ≈1
- `tribe.convergence` — `examples/cultural_tagging.json`; mean majority share
  0.79

Engine-generated counterfactuals (no empirical or GAS anchor — deliberately
aspirational shapes; a target need not be perfectly reachable in a variant to
be a target, players simply get as close as their rulesets allow):

- `wealth.egalitarian` — equalized endowments + universal income + short
  lifespans compress wealth to Gini ≈ 0.30 (vs ~0.47 default); no real-world
  wealth distribution is this equal (empirical Ginis ≥ ~0.5)
- `tribe.diversity` — quadrant-separated tribes hold a stable split (mean
  majority share 0.64)

Still provisional:

- `age-at-death.survivorship` — empirical source: HMD life-table `dx` (CC BY
  4.0); convert with `tools/convert_hmd_survivorship.py` once the life table
  is downloaded (UN WPP abridged tables, CC BY 3.0 IGO, are the fallback)

Shelved (2026-08-11): `disease.endemic` and `disease.eradicated`. No DTL
configuration we found sustains a stable endemic equilibrium — immune systems
eradicate within ~10 ticks, or transmission/penalty pressure collapses the
population (an 81.8%-prevalence configuration existed but killed its hosts).
Revisit with a disease-reintroduction mechanism if disease variants return.
`sick_fraction` remains measured (measurement-only canonical bins in
`src/coworld/targets.py`) so results histograms stay complete.

Replacing a provisional histogram with generated or empirical data requires
preserving that variable's canonical support and bins, updating the provenance,
and setting `provisional` accurately.

## Probing a variant/target pair

`tools/probe_reachability.py` runs a small evolutionary search over SugarLang
rulesets against a variant (or config file) and reports the best match score
found — a **lower bound on the achievable ceiling** to pair with the
null-ruleset floor when judging a pair's skill spread. The initial population
includes the null and greedy rulesets, so the reported ceiling never falls
below the baseline. The tool can demonstrate reachability, never disprove it:
a search that finds nothing above the floor only predicts that players will
struggle too. Targets deliberately need not be reachable to ship (decided
2026-08-11); the probe is a calibration instrument, not a gate. Note the
evolved `best-ruleset.json` is a machine-discovered strategy — treat it as a
spoiler for whichever league the variant runs in.
