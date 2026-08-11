# Sugarscape v3 target catalog

Targets are normalized histograms describing outcomes that a player's SugarLang
ruleset should grow. The shipped catalog lives in `targets/`, one JSON object per
file. All nine v3 targets are currently **provisional parametric approximations**,
not digitized literature data or empirical datasets. Every file says so with
`"provisional": true`, identifies its parametric family and parameters, and
describes how its probabilities were generated.

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

## Shipped provisional targets

- `wealth.skewed-gini-0.5`
- `wealth.egalitarian`
- `population.carrying-capacity`
- `age-at-death.survivorship`
- `tribe.convergence`
- `tribe.diversity`
- `disease.endemic`
- `disease.eradicated`
- `price.equilibrium`

Replacing a provisional histogram with digitized or empirical data requires
preserving that variable's canonical support and bins, updating the provenance,
and setting `provisional` accurately.
