# Mechanics-Rich Scenario Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the scenario reachability gate entirely and regenerate the ladder pool as 80 scenarios: 12 hand-tuned base worlds × declarative mechanic packs.

**Architecture:** `tools/generate_scenario_pool.py` stays the single source of truth and the manifest pools stay generated output, but the literal 24-scenario list becomes a programmatic cross of `BASE_WORLDS × packs`. The probe tools, their tests, and their docs are deleted, not deprecated.

**Tech Stack:** Python 3 (project venv at `.venv/`), pytest, the pinned DTL simulation under `src/sugarscape/`.

**Spec:** `docs/designs/2026-08-18-mechanics-rich-scenario-pool.md` (read it first; it carries the rationale and the family/pack tables).

## Global Constraints

- Run everything from the repo root with `.venv/bin/python`; the suite is `.venv/bin/python -m pytest`.
- `PYTHONHASHSEED=0` is assumed for reproducibility (test runner handles it).
- The seven target ids are unchanged: `wealth.skewed-gini-0.5`, `wealth.egalitarian`, `population.carrying-capacity`, `age-at-death.survivorship`, `price.equilibrium`, `tribe.convergence`, `tribe.diversity`.
- The manifest (`coworld_manifest.json`) is edited ONLY via `generate_scenario_pool.py --write`; never hand-edit the pool arrays.
- `src/coworld/server.py` and its tests mention a "viewer probe" — that is the hosted certifier's WebSocket check, NOT reachability. Do not touch it.
- `tools/generate_targets.py` stays as is.
- Commit messages: short imperative sentences matching `git log` style (e.g. "Remove the scenario reachability probe"), no `feat:`/`fix:` prefixes. End every commit message with the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
- The working tree starts with pre-existing uncommitted work that Task 0 checkpoints verbatim. Do not include `tmp/` in any commit.

---

### Task 0: Checkpoint pre-existing in-flight work

The tree carries uncommitted scoring-v2 / replay-viewer / probe changes that must be preserved in history before probe files are deleted and pool files rewritten.

**Files:**
- Modify: nothing (commit-only task)

**Interfaces:**
- Produces: a clean-enough tree where every later `git add <specific files>` picks up only this plan's changes.

- [ ] **Step 1: Review what is uncommitted**

Run: `git status --short` and `git diff --stat`
Expected: ~24 modified files (scoring, replay viewer, probe tools, docs) plus untracked `docs/designs/2026-08-18-*.md` files and `tmp/`.

- [ ] **Step 2: Commit the WIP checkpoint (everything except tmp/ and this plan's new docs)**

```bash
git add -A -- ':!tmp' ':!docs/designs/2026-08-18-mechanics-rich-scenario-pool.md' ':!docs/superpowers'
git commit -m "Checkpoint in-flight scoring-v2, viewer, and probe work

Pre-existing uncommitted work committed verbatim before the scenario-pool
redesign rewrites and deletes some of these files.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 3: Commit the design doc and this plan**

```bash
git add docs/designs/2026-08-18-mechanics-rich-scenario-pool.md docs/superpowers/plans/2026-08-18-mechanics-rich-scenario-pool.md
git commit -m "Add mechanics-rich scenario pool design and plan

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Verify the tree is clean apart from tmp/**

Run: `git status --short`
Expected: only `?? tmp/` (leave it).

---

### Task 1: Remove the reachability probe machinery

**Files:**
- Delete: `tools/probe_pool.py`, `tools/probe_reachability.py`, `tests/test_probe.py`, `docs/probe-reports/` (whole directory)
- Modify: `tools/generate_scenario_pool.py` (remove `--emit-configs`), `tests/test_packaging.py` (only if it references deleted files)

**Interfaces:**
- Consumes: nothing.
- Produces: a generator whose CLI is exactly `--write` and `--check`.

- [ ] **Step 1: Delete the probe files**

```bash
git rm tools/probe_pool.py tools/probe_reachability.py tests/test_probe.py
git rm -r docs/probe-reports
```

- [ ] **Step 2: Remove `--emit-configs` from the generator**

In `tools/generate_scenario_pool.py`:
- Delete the `DEFAULT_CONFIG_DIR` constant (line ~21).
- Delete the whole `emit_configs()` function (line ~1174).
- In `main()`: delete the `--emit-configs` `add_argument` call, change the no-args guard to `if not args.write and not args.check: parser.error("choose --write or --check")`, and delete the `if args.emit_configs is not None:` block.
- Update the module docstring: drop "and probe configs" and the `--emit-configs` mention.

- [ ] **Step 3: Sweep for dangling references**

Run: `grep -rn "probe_pool\|probe_reachability\|emit-configs\|emit_configs\|probe-reports" --exclude-dir=archived --exclude-dir=.git --exclude-dir=build --exclude-dir=tmp .`
Expected leftovers to fix now: any hits in `tests/` or `tools/`. Hits in `docs/` are handled in Task 4 — leave them. Hits in `docs/designs/2026-08-18-w1-scoring-v2.md` and other dated design docs are historical — leave them.
Check `tests/test_packaging.py` specifically: if it asserts the packaged file list contains the deleted tools, remove those entries.

- [ ] **Step 4: Run the affected tests**

Run: `.venv/bin/python -m pytest tests/test_packaging.py tests/test_scenario_pool.py -x -q`
Expected: PASS (test_probe.py no longer exists to fail).

- [ ] **Step 5: Commit**

```bash
git add -A -- ':!tmp'
git commit -m "Remove the scenario reachability probe

Reachability is no longer a gate on pool changes; a badly unreachable
target in some scenario is a balance patch, not a proof obligation.
Deletes probe_pool, probe_reachability, their tests and reports, and the
generator's --emit-configs probe-support mode.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Rewrite the generator as base worlds × mechanic packs

This is the core task. TDD: update the pool-invariant tests first so they describe the new 80-scenario structure, watch them fail, then rewrite the generator and regenerate the manifest.

**Files:**
- Modify: `tools/generate_scenario_pool.py` (replace the `SCENARIOS` literal with `BASE_WORLDS` + pack machinery), `tests/test_scenario_pool.py`, `coworld_manifest.json` (via `--write` only)

**Interfaces:**
- Consumes: the existing generator helpers (`duo_scenarios`, `write_manifest`, `check_manifest`, `rendered_pool`, `scenario_pool_span`) — all keep their signatures and keep reading module-level `SCENARIOS`.
- Produces: `SCENARIOS: list[dict[str, object]]` (now computed by `build_scenarios()`), length 80, ordered family → base → pack. Scenario ids: `<base-id>` for the baseline pack, `<base-id>.<pack>` otherwise.

**Structure (fixed by the spec):**

| Family | Base ids (keep `config_overrides` VERBATIM from the current `SCENARIOS` list) | Packs |
|---|---|---|
| wealth-skewed | `wealth-skewed.twin-peaks`, `wealth-skewed.scarce-lowland` | baseline, spice, market, combat, reproduction, pollution, everything |
| wealth-egalitarian | `wealth-egalitarian.central-plateau`, `wealth-egalitarian.scarce-income` | baseline, spice, market, combat, disease, seasons, everything |
| capacity | `capacity.compact-regrow-1`, `capacity.sparse-regrow-2` | baseline, spice, market, combat, pollution, seasons, everything |
| survivorship | `survivorship.young-frontier`, `survivorship.long-lived` | baseline, spice, market, combat, disease, seasons, everything |
| price | `price.overlapping-peaks`, `price.four-markets` | baseline, combat, seasons, disease, everything (spice/market skipped: already on) |
| tribe | `tribe-convergence.three-way-mixed`, `tribe-diversity.opposite-quadrants` | baseline, spice, market, combat, disease, seasons, everything |

Counts: 4 families × 7 × 2 = 56, price 5 × 2 = 10, tribe 7 × 2 = 14 → 80. The other 12 current worlds (including `survivorship.seasonal-migration`) are dropped.

- [ ] **Step 1: Rewrite the pool tests to describe the new structure**

In `tests/test_scenario_pool.py` make these exact changes:

```python
FAMILY_REPRESENTATIVES = [0, 14, 28, 42, 56, 66]  # first scenario of each family
```

In `test_pool_invariants`, replace the size/uniqueness/family assertions:

```python
    assert len(pool) == 80
    assert len(set(scenario_ids)) == 80
    assert len(set(maps)) == 80
```

and replace `assert set(families.values()) == {4}` with:

```python
    assert families == {
        "wealth-skewed": 14,
        "wealth-egalitarian": 14,
        "capacity": 14,
        "survivorship": 14,
        "price": 10,
        "tribe": 14,
    }
```

Keep the capacity-family assertions (immortality, no replacements, fertility `[0, 0]`) — they must still hold because capacity gets no reproduction pack and `everything` excludes reproduction.

Add a new test:

```python
def test_pack_invariants() -> None:
    pool = solo_ladder_config()["scenario_pool"]
    by_id = {scenario["id"]: scenario["config_overrides"] for scenario in pool}

    packs: dict[str, list[str]] = {}
    for scenario_id in by_id:
        parts = scenario_id.split(".")
        pack = parts[2] if len(parts) == 3 else "baseline"
        packs.setdefault(pack, []).append(scenario_id)

    assert set(packs) == {
        "baseline", "spice", "market", "combat", "disease",
        "pollution", "seasons", "reproduction", "everything",
    }
    assert len(packs["baseline"]) == 12
    assert len(packs["everything"]) == 12

    for scenario_id, overrides in by_id.items():
        parts = scenario_id.split(".")
        pack = parts[2] if len(parts) == 3 else "baseline"
        if pack in ("spice", "market", "everything"):
            assert overrides["environmentMaxSpice"] > 0, scenario_id
            assert overrides["agentSpiceMetabolism"][1] > 0, scenario_id
            assert overrides["environmentSpicePeaks"], scenario_id
        if pack in ("market", "everything"):
            assert overrides["agentTradeFactor"] == [1, 1], scenario_id
        if pack in ("combat", "everything"):
            assert overrides["agentTagging"] is True, scenario_id
            assert overrides["agentAggressionFactor"] == [0, 2], scenario_id
        if pack in ("disease", "everything"):
            assert overrides["startingDiseases"] == 40, scenario_id
        if pack in ("pollution", "everything"):
            assert overrides["environmentSugarProductionPollutionFactor"] == 1, scenario_id
            assert overrides["environmentPollutionTimeframe"] == [-1, -1], scenario_id
        if pack in ("seasons", "everything"):
            assert overrides["environmentSeasonInterval"] == 50, scenario_id
        if pack == "reproduction":
            assert overrides["agentFertilityFactor"] == [1, 1], scenario_id
            assert overrides["agentReplacements"] == 0, scenario_id
        if pack == "baseline" and not scenario_id.startswith(("price.", "tribe-")):
            assert overrides["environmentMaxSpice"] == 0, scenario_id
            assert overrides["agentTagging"] is False, scenario_id

    # price never emits redundant spice/market packs
    assert not any(s.endswith((".spice", ".market")) for s in by_id if s.startswith("price."))
```

- [ ] **Step 2: Run the pool tests to verify they fail against the old pool**

Run: `.venv/bin/python -m pytest tests/test_scenario_pool.py -x -q`
Expected: FAIL on `assert len(pool) == 80` (pool is still 24).

- [ ] **Step 3: Rewrite the generator's scenario definitions**

In `tools/generate_scenario_pool.py`, replace the `SCENARIOS: list[dict[str, object]] = [...]` literal with the following. Keep the 12 base worlds' `config_overrides` dicts byte-for-byte identical to the current entries with the same ids (copy them from the existing list before deleting it); each `BASE_WORLDS` entry keeps the current `id`, `description`, and `targets` and gains a `family` key.

```python
FAMILY_ORDER = [
    "wealth-skewed",
    "wealth-egalitarian",
    "capacity",
    "survivorship",
    "price",
    "tribe",
]

# Two hand-tuned worlds per family, carried verbatim from the retired
# 24-scenario pool. config_overrides must not be edited here; packs layer
# deltas on top.
BASE_WORLDS: list[dict[str, object]] = [
    {
        "family": "wealth-skewed",
        "id": "wealth-skewed.twin-peaks",
        "description": "Replacement economy on the classic offset twin-peak sugar landscape.",
        "config_overrides": {},  # VERBATIM copy of the current entry
        "targets": ["wealth.skewed-gini-0.5"],
    },
    # ... 11 more, in the family/base order given by the table above ...
]

SITUATIONAL_PACKS: dict[str, list[str]] = {
    "wealth-skewed": ["reproduction", "pollution"],
    "wealth-egalitarian": ["disease", "seasons"],
    "capacity": ["pollution", "seasons"],
    "survivorship": ["disease", "seasons"],
    "price": ["seasons", "disease"],
    "tribe": ["disease", "seasons"],
}

PACK_DESCRIPTIONS = {
    "spice": "Adds a spice resource and spice metabolism.",
    "market": "Adds spice and bilateral sugar-spice trade.",
    "combat": "Adds cultural tags and inter-tribe combat.",
    "disease": "Adds transmissible diseases.",
    "pollution": "Adds production and consumption pollution with diffusion.",
    "seasons": "Adds alternating seasons with delayed growback.",
    "reproduction": "Replaces automatic replacement with agent reproduction.",
    "everything": "Adds spice, trade, tags, combat, disease, pollution, and seasons.",
}

# DTL treats negative timeframe bounds as "the whole episode".
EPISODE_TIMEFRAME = [-1, -1]


def _spice_delta(base: dict[str, object]) -> dict[str, object]:
    sugar_peaks = base["environmentSugarPeaks"]
    return {
        "agentSpiceMetabolism": [1, 4],
        "agentStartingSpice": [10, 30],
        "environmentMaxSpice": base["environmentMaxSugar"],
        "environmentSpicePeaks": [[y, x, height] for x, y, height in sugar_peaks],
        "environmentSpiceRegrowRate": 1,
    }


def _market_delta(base: dict[str, object]) -> dict[str, object]:
    delta = _spice_delta(base)
    delta["agentTradeFactor"] = [1, 1]
    delta["trait_ranges"] = {"trade": [0, 1]}
    return delta


def _combat_delta(base: dict[str, object]) -> dict[str, object]:
    delta: dict[str, object] = {
        "agentAggressionFactor": [0, 2],
        "environmentMaxCombatLoot": 2,
        "trait_ranges": {"aggression": [0, 2]},
    }
    if not base.get("agentTagging"):
        # DTL combat needs tribes: prey must belong to a different tribe.
        delta["agentTagging"] = True
        delta["agentTagStringLength"] = 11
        delta["environmentMaxTribes"] = 2
    return delta


def _disease_delta(has_spice: bool) -> dict[str, object]:
    return {
        "startingDiseases": 40,
        "startingDiseasesPerAgent": [0, 3],
        "agentImmuneSystemLength": 35,
        "diseaseSugarMetabolismPenalty": [1, 3],
        # A spice-metabolism penalty in a spiceless world is a death
        # sentence, not a hazard: it creates metabolism with no supply.
        "diseaseSpiceMetabolismPenalty": [1, 3] if has_spice else [0, 0],
        "diseaseTransmissionChance": [1.0, 1.0],
    }


def _pollution_delta(has_spice: bool) -> dict[str, object]:
    delta: dict[str, object] = {
        "environmentSugarProductionPollutionFactor": 1,
        "environmentSugarConsumptionPollutionFactor": 1,
        "environmentPollutionTimeframe": list(EPISODE_TIMEFRAME),
        "environmentPollutionDiffusionTimeframe": list(EPISODE_TIMEFRAME),
        "environmentPollutionDiffusionDelay": 10,
    }
    if has_spice:
        delta["environmentSpiceProductionPollutionFactor"] = 1
        delta["environmentSpiceConsumptionPollutionFactor"] = 1
    return delta


def _seasons_delta() -> dict[str, object]:
    return {
        "environmentSeasonInterval": 50,
        "environmentSeasonalGrowbackDelay": 8,
    }


def _reproduction_delta() -> dict[str, object]:
    return {
        "agentFertilityFactor": [1, 1],
        "agentReplacements": 0,
        "trait_ranges": {"fertility": [0, 1]},
    }


def _merge_delta(overrides: dict[str, object], delta: dict[str, object]) -> None:
    for key, value in delta.items():
        if key == "trait_ranges":
            merged = dict(overrides.get("trait_ranges", {}))
            merged.update(value)
            overrides["trait_ranges"] = merged
        else:
            overrides[key] = deepcopy(value)


def _pack_delta(pack: str, base: dict[str, object]) -> dict[str, object]:
    base_has_spice = base["environmentMaxSpice"] > 0
    if pack == "spice":
        return _spice_delta(base)
    if pack == "market":
        return _market_delta(base)
    if pack == "combat":
        return _combat_delta(base)
    if pack == "disease":
        return _disease_delta(base_has_spice)
    if pack == "pollution":
        return _pollution_delta(base_has_spice)
    if pack == "seasons":
        return _seasons_delta()
    if pack == "reproduction":
        return _reproduction_delta()
    if pack == "everything":
        overrides = deepcopy(base)
        for layer in ("market", "combat"):
            _merge_delta(overrides, _pack_delta(layer, overrides))
        delta: dict[str, object] = {
            key: overrides[key] for key in overrides if key not in base or overrides[key] != base[key]
        }
        _merge_delta(delta, _disease_delta(True))
        _merge_delta(delta, _pollution_delta(True))
        _merge_delta(delta, _seasons_delta())
        # trait_ranges in the delta must carry the full merged mapping.
        delta["trait_ranges"] = overrides["trait_ranges"]
        return delta
    raise ValueError(f"unknown pack: {pack}")


def _family_packs(family: str, base_overrides: dict[str, object]) -> list[str]:
    packs = ["baseline", "spice", "market", "combat"]
    if base_overrides["environmentMaxSpice"] > 0:
        packs = ["baseline", "combat"]  # spice and market are already on
    packs += SITUATIONAL_PACKS[family]
    packs.append("everything")
    return packs


def build_scenarios() -> list[dict[str, object]]:
    scenarios: list[dict[str, object]] = []
    for family in FAMILY_ORDER:
        for base in (world for world in BASE_WORLDS if world["family"] == family):
            base_overrides = base["config_overrides"]
            for pack in _family_packs(family, base_overrides):
                overrides = deepcopy(base_overrides)
                description = base["description"]
                scenario_id = base["id"]
                if pack != "baseline":
                    _merge_delta(overrides, _pack_delta(pack, base_overrides))
                    scenario_id = f"{base['id']}.{pack}"
                    description = f"{description} {PACK_DESCRIPTIONS[pack]}"
                scenarios.append(
                    {
                        "id": scenario_id,
                        "description": description,
                        "config_overrides": overrides,
                        "targets": deepcopy(base["targets"]),
                    }
                )
    return scenarios


SCENARIOS: list[dict[str, object]] = build_scenarios()
```

Everything downstream (`duo_scenarios`, `write_manifest`, `check_manifest`, `rendered_pool`) is unchanged and keeps consuming `SCENARIOS`.

Note the `everything` construction: it layers market and combat onto a working copy so the combat delta sees tagging already applied where relevant, then computes the changed-key delta and merges disease/pollution/seasons on top. If this proves awkward in practice, an equivalent simpler implementation is acceptable as long as: spice+trade+tagging+combat+disease+pollution+seasons are all on, `trait_ranges` ends up with trade `[0, 1]` and aggression `[0, 2]` merged over the base mapping, tribe bases keep `environmentMaxTribes: 3`, and reproduction stays off.

- [ ] **Step 4: Regenerate the manifest and run the pool tests**

```bash
.venv/bin/python tools/generate_scenario_pool.py --write
.venv/bin/python tools/generate_scenario_pool.py --check
.venv/bin/python -m pytest tests/test_scenario_pool.py -x -q
```

Expected: `--check` prints "scenario pool matches generator"; all pool tests PASS, including the new `test_pack_invariants` and the pre-existing `test_all_scenarios_resolve_and_validate` (which now sweeps all 80 configs through `resolve_episode_config` + `build_dtl_config` and will catch any key DTL rejects or rewrites).

- [ ] **Step 5: Run the broader suite for regressions**

Run: `.venv/bin/python -m pytest -x -q`
Expected: PASS. If a test outside `test_scenario_pool.py` hard-codes pool size 24 or a scenario id that no longer exists (check `tests/test_targets.py`, `tests/test_server.py`, `tests/test_episode.py`), update that literal to the new pool.

- [ ] **Step 6: Commit**

```bash
git add tools/generate_scenario_pool.py tests/test_scenario_pool.py coworld_manifest.json
git commit -m "Regenerate the ladder pool as base worlds crossed with mechanic packs

12 hand-tuned base worlds (2 per family) x declarative packs (spice,
market, combat, disease, pollution, seasons, reproduction, everything)
produce 80 scenarios per ladder. Packs layer deltas over verbatim base
overrides; no-op packs are skipped rather than duplicated.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

(Include any test files updated in Step 5.)

---

### Task 3: Full-pool runtime smoke test

Every one of the 80 merged configs must actually construct and step a world on the pinned interpreter — this catches DTL key typos and mechanics that crash at runtime (disease endowments, combat, pollution), which static resolve/validate cannot.

**Files:**
- Modify: `tests/test_scenario_pool.py`

**Interfaces:**
- Consumes: `solo_ladder_config()` helper and `run_episode` from Task 2's test module (already imported there).
- Produces: nothing further.

- [ ] **Step 1: Write the sweep test**

Add to `tests/test_scenario_pool.py`:

```python
def _pool_indices() -> range:
    return range(len(solo_ladder_config()["scenario_pool"]))


@pytest.mark.parametrize("scenario_index", _pool_indices())
def test_every_scenario_runs_a_short_episode(scenario_index: int) -> None:
    config = solo_ladder_config()
    config.update({"seed": scenario_index, "timesteps": 3, "measurement_window": 3})

    results, replay, _timings = run_episode(config, [None], emit_timing_logs=False)

    assert results["scenario_index"] == scenario_index
    assert results["result.timesteps_completed"] == 3
    assert replay
```

The existing `test_one_short_episode_per_family` becomes redundant with this sweep — delete it (keep the duo variant, which still exercises two-seat episodes at the updated `FAMILY_REPRESENTATIVES`).

- [ ] **Step 2: Run the sweep and time it**

Run: `time .venv/bin/python -m pytest tests/test_scenario_pool.py::test_every_scenario_runs_a_short_episode -q`
Expected: 80 passed. If total wall time exceeds ~4 minutes, reduce to `"timesteps": 2, "measurement_window": 2` (update the assertion to 2) — do not sample the pool; every scenario must run.

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_scenario_pool.py
git commit -m "Smoke-run every pool scenario for a short episode

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Documentation rewrite

**Files:**
- Modify: `docs/SCENARIOS.md` (major rewrite), `README.md`, `docs/TARGETS.md`, `docs/what-is-a-coworld.md`, `docs/PROTOCOL.md` (only if it references the pool probe), `docs/designs/2026-08-13-solo-ladder-scenario-pool.md` (superseded note only)

**Interfaces:**
- Consumes: the spec's family/pack tables (`docs/designs/2026-08-18-mechanics-rich-scenario-pool.md`).
- Produces: docs that describe the 80-scenario pool with no reachability references.

- [ ] **Step 1: Rewrite `docs/SCENARIOS.md`**

Keep the document's existing section order and tone. Required changes:
- Intro: "draws one of 24 curated world/target scenarios" → "draws one of 80 scenarios (12 hand-tuned base worlds × mechanic packs)". Same for the duo paragraph.
- Selection: `scenario_pool[seed % 24]` → `scenario_pool[seed % 80]`.
- "Duo target pairs" section: unchanged except delete the `capacity.wide-regrow-1` 275/276 sentence (that base is gone; note instead that all current bases have even starting populations and the generator still bumps odd duo copies by one).
- Replace the "Families" section with two tables: (a) the base-world table (family, two base ids, target, one-line regime) and (b) the pack table (pack name, what it enables, which families get it) — copy content from the spec's "Pool structure" and "Mechanic packs" sections, keeping the DTL key detail (spice mirroring rule, combat-needs-tagging note, the disease spice-penalty guard, `[-1, -1]` timeframe convention).
- Delete the "disable unwanted hazards" paragraph and the egalitarian income-interval caveat sentence about spice edge cases only if it no longer applies — it still applies to egalitarian baseline worlds, so keep that sentence.
- "Source of truth" section: drop the `--emit-configs` command and its explanatory sentence; the workflow is now edit generator → `--write` → update this catalog → run scenario-pool tests.
- Delete the entire "Reachability gate" section and anything after it that describes probe passes/roles.

- [ ] **Step 2: Update the other docs**

- `README.md`: replace the "deterministic pool of 24 curated scenarios spanning all seven targets and six mechanical families" sentence with the 80-scenario base-worlds × packs description; drop "per-scenario reachability gate" from the SCENARIOS.md pointer sentence.
- `docs/TARGETS.md`: remove sentences referencing the reachability probe/gate (keep everything else, including uncommitted scoring-v2 content already in the file).
- `docs/what-is-a-coworld.md`: remove the pool-probe reference found via grep.
- `docs/PROTOCOL.md`: check its probe hit — if it is the certifier viewer probe, leave it; if it references pool reachability, remove.
- `docs/designs/2026-08-13-solo-ladder-scenario-pool.md`: prepend directly under the title:

```markdown
> **Superseded (2026-08-18):** the 24-scenario structure and reachability
> gate described here were removed. See
> [2026-08-18-mechanics-rich-scenario-pool.md](2026-08-18-mechanics-rich-scenario-pool.md).
```

- [ ] **Step 3: Sweep for stale references**

Run: `grep -rn "24 \|reachability\|Reachability\|probe_pool\|probe-reports\|probe_reachability" docs README.md --exclude-dir=docs/designs --exclude-dir=docs/recon | grep -v archived`
Expected: no hits about the scenario pool remain outside dated design docs (dated design docs and recon notes are historical records — leave them).

- [ ] **Step 4: Run the doc-sensitive tests**

Run: `.venv/bin/python -m pytest tests/test_packaging.py -q`
Expected: PASS (packaging tests sometimes assert doc files exist).

- [ ] **Step 5: Commit**

```bash
git add docs README.md
git commit -m "Document the 80-scenario pool and drop reachability from the docs

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-review notes

- Spec coverage: removal scope → Tasks 1 and 4; pool structure/packs → Task 2; testing section → Tasks 2 and 3; docs → Task 4. The spec's "verify new keys survive the config merge and disclosure" risk is covered by the pre-existing `test_all_scenarios_resolve_and_validate` (asserts `build_dtl_config` preserves every override key on all 80 scenarios).
- The duo evenness invariant (`startingAgents % 2 == 0`) holds for all 12 bases (all even) and no pack changes `startingAgents`; the existing `duo_scenarios()` +1 rule stays as a safety net.
- Capacity keeps fertility `[0, 0]` everywhere because its situational packs are pollution/seasons and `everything` excludes reproduction — the pre-existing capacity assertions in `test_pool_invariants` stay valid.
