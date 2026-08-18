# Duo ladder

## Goal

Add a second ranked Sugarscape league without changing the existing solo
ladder. Each duo episode seats two distinct policies in one shared world. Both
receive the same resolved public game configuration, receive different target
distributions, submit independent SugarLang rulesets, and receive independent
distribution-match scores.

## Game variant

`duo-ladder` is a two-seat variant derived from the `solo-ladder` worlds — 24
validated scenarios when this was written; since 2026-08-18 the shared pool is
80 scenarios (12 base worlds crossed with mechanic packs, see
`2026-08-18-mechanics-rich-scenario-pool.md`), and the derivation below is
unchanged. Each scenario keeps its solo target and adds a distinct existing catalog
target. The target order alternates across the ordered pool. All target scopes
remain global, so both policies influence the same measured macro outcome while
being scored against different objectives.

The generator remains the source of truth. It derives the duo pool rather than
maintaining a second handwritten set of world parameters. The only world-level
deviation is `capacity.wide-regrow-1`: its starting population changes from 275
to 276 because two-seat initialization requires equal integer populations.

## League configuration

The duo league is a new platform-owned league seed with `duo-ladder` as its
default variant. It does not replace or reconfigure the existing Sugarscape
league. It uses:

- one Competition division;
- mirrored pair seating so every policy pairing appears in both seat orders;
- the same absolute-score ranking as the solo ladder: mean round score feeding
  a three-hour EWMA, maximizing the result;
- `do_not_run` when fewer than two real champions are available; and
- the same five-minute round interval and fulfillment policy as the solo
  ladder.

## Validation

- The manifest contains both ladder variants and no embedded tokens.
- Every duo scenario resolves with two distinct targets and an even starting
  population.
- One short two-seat episode from each scenario family produces two target IDs,
  two details, two scores, and a replay.
- The generated solo pool remains unchanged and generator checks are
  byte-idempotent.
- After publication, one hosted episode must record two distinct policy
  participants, two different targets, and two independently attributed scores.
