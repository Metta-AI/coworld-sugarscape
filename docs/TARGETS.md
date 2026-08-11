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

The ranked score is `1 - normalized_W1`. Wasserstein-1 distance is computed from
the two cumulative histograms, weighted by bin width, and divided by the support
width. Results also report base-2 Jensen-Shannon divergence as a diagnostic. An
empty target measurement scores zero and sets `empty_measurement: true`.

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
