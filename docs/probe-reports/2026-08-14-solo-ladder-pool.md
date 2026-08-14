# Probe report: solo-ladder pool, 2026-08-14

Reachability gate results for the 24-scenario pool shipped in coworld
version 3.1.0 (pool as of generator state at that release). Budget:
population 24, generations 12, episode seeds 11 and 42, probe RNG seed 1.
Gate: evolved ceiling >= 0.50. Role: `skill` when ceiling - null >= 0.05,
else `anchor` (kept deliberately as regression guards).

Two scenarios were revised during this run before passing:

- `survivorship.scarce` first probed at ceiling 0.4282 (starvation
  dominated age-at-death); metabolism [2,5]->[1,3] and peak cap 3->4
  brought it to 0.5223.
- `price.opposite-corners` probed at ceiling 0.0000 (51-cell resource
  separation: no trade ever occurred) and, after tightening to 34 cells,
  plateaued at 0.2938 with a null floor still at zero. Full spatial
  separation of sugar and spice cannot reproduce an equilibrium-price
  target; the slot was replaced by `price.scarce-markets` (co-located
  cap-3 markets), which probed at 0.9979.

| scenario | target | null floor | ceiling | gradient | role |
|---|---|---:|---:|---:|---|
| `wealth-skewed.twin-peaks` | `wealth.skewed-gini-0.5` | 0.9946 | 0.9988 | +0.0042 | anchor |
| `wealth-skewed.mega-peak` | `wealth.skewed-gini-0.5` | 0.9774 | 0.9786 | +0.0012 | anchor |
| `wealth-skewed.four-corners` | `wealth.skewed-gini-0.5` | 0.9795 | 0.9973 | +0.0178 | anchor |
| `wealth-skewed.scarce-lowland` | `wealth.skewed-gini-0.5` | 0.9602 | 0.9602 | +0.0000 | anchor |
| `wealth-egalitarian.offset-twins` | `wealth.egalitarian` | 0.9991 | 0.9995 | +0.0004 | anchor |
| `wealth-egalitarian.central-plateau` | `wealth.egalitarian` | 0.9876 | 0.9891 | +0.0015 | anchor |
| `wealth-egalitarian.four-basins` | `wealth.egalitarian` | 0.9849 | 0.9976 | +0.0127 | anchor |
| `wealth-egalitarian.scarce-income` | `wealth.egalitarian` | 0.9865 | 0.9865 | +0.0000 | anchor |
| `capacity.compact-regrow-1` | `population.carrying-capacity` | 0.9000 | 0.9500 | +0.0500 | anchor |
| `capacity.wide-regrow-1` | `population.carrying-capacity` | 0.9000 | 0.9500 | +0.0500 | anchor |
| `capacity.dense-regrow-2` | `population.carrying-capacity` | 1.0000 | 1.0000 | +0.0000 | anchor |
| `capacity.sparse-regrow-2` | `population.carrying-capacity` | 0.9000 | 0.9500 | +0.0500 | anchor |
| `survivorship.young-frontier` | `age-at-death.survivorship` | 0.6950 | 0.7687 | +0.0737 | skill |
| `survivorship.long-lived` | `age-at-death.survivorship` | 0.8038 | 0.8829 | +0.0791 | skill |
| `survivorship.scarce` | `age-at-death.survivorship` | 0.5056 | 0.5223 | +0.0167 | anchor |
| `survivorship.seasonal-migration` | `age-at-death.survivorship` | 0.5831 | 0.6316 | +0.0485 | anchor |
| `price.overlapping-peaks` | `price.equilibrium` | 0.9941 | 0.9951 | +0.0010 | anchor |
| `price.scarce-markets` | `price.equilibrium` | 0.9896 | 0.9979 | +0.0083 | anchor |
| `price.four-markets` | `price.equilibrium` | 0.5876 | 0.6999 | +0.1123 | skill |
| `price.split-centers` | `price.equilibrium` | 0.2938 | 0.7253 | +0.4315 | skill |
| `tribe-convergence.three-way-mixed` | `tribe.convergence` | 0.8590 | 0.9832 | +0.1242 | skill |
| `tribe-convergence.two-way-mixed` | `tribe.convergence` | 0.9607 | 0.9607 | +0.0000 | anchor |
| `tribe-diversity.opposite-quadrants` | `tribe.diversity` | 0.9167 | 0.9316 | +0.0149 | anchor |
| `tribe-diversity.three-quadrants` | `tribe.diversity` | 0.8682 | 0.9439 | +0.0757 | skill |
