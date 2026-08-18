# Ruleset Studio

Ruleset Studio is the local visual editor for SugarLang v1. It turns movement
rules into Blockly stacks, exposes the four optional trait overrides, validates
every edit with the repository's Python validator, and saves plain JSON under
`rulesets/`. The editor remains usable when no coding-agent bridge is attached.

## Launch

Prerequisites are the project virtual environment, Node.js, and the read-only
Metta checkout at `~/coding/metta` containing `agent-plugins/ux`. From the
repository root, run:

```sh
.venv/bin/python -m tools.ruleset_studio
```

The launcher enforces `PYTHONHASHSEED=0`, chooses free loopback ports, starts
the run-stage and API listeners before the link server, opens the browser, and
prints the exact `link-bridge.mjs watch` command for the current
ports. Run that printed command in the coding session that should answer chat.
After a reply, run the same command again to re-arm the one-reply watch. There
is no submit or completion lifecycle: Save is the only persistence operation.

Use `--no-open` to suppress browser opening, `--metta-root PATH` for another
read-only Metta checkout, or `--link-port`/`--api-port`/`--run-port` to prefer
other ports. `--runs-dir` changes the immutable artifact directory and
`--shutdown-timeout` bounds an active worker join. `--link-server` overrides
`COWORLD_STUDIO_LINK_SERVER`, which overrides the path under `--metta-root`.
Ctrl-C or SIGTERM cancels an active run before stopping listeners. Closing the
studio tab lets an active run finish and publish before shutdown. If a worker
does not stop within the timeout, the launcher reports that its daemon thread
was abandoned rather than allowing interpreter shutdown to hang.

## How it fits together

- `src/` is the complete static app. It includes the pinned, offline Blockly
  browser build at `src/vendor/blockly/` and loads the ux.surface
  `/link-client.js` from the local link server.
- `server.py` is the stdlib-only loopback API. It preserves the raw-body
  phase-1 routes and adds JSON-envelope run routes through an injected
  coordinator.
- `src/coworld/studio.py` composes run configurations. `studio_runs.py` owns
  the single worker and artifacts; `coworld.server.StudioRunStageServer` owns
  the isolated asyncio/WebSocket edge.
- `tools/ruleset_studio.py` runs both Python listeners in one process and
  supervises Metta's read-only ux.surface child. The page query contains exact
  `api` and `run` origins.

The context selector mirrors hosted resolution: the "Local config.json"
context merges the pinned DTL runtime defaults with root `config.json`, while
variant and scenario contexts merge the defaults with the variant config and
scenario overrides only (the local `config.json` never leaks into them).
Disabled traits display the effective DTL factor range; enabled values are
clamped to the selected context's `trait_ranges`, and a degenerate range shows
as a locked dial with the reason. Switching contexts never rewrites the
document's trait values.

Agent replies may propose `{set: {ruleset: ..., note: ...}}`. The UI validates
the full replacement with the Python API before offering it, then applies it as
one custom Blockly event so a single Undo restores the prior ruleset. A missing
bridge affects chat only.

## Play

Play is the IDE-style compile-and-run action. It is enabled only after the
current Blockly generation completes authoritative validation with no local
lints. The cog selects a fixed variant or pooled ranked/exploration preview,
seed policy, scenario where applicable, and optional timesteps.

The main area becomes the existing replay viewer. It receives sampled live
frames beginning at tick 0, then naturally enters replay controls after the
authoritative final frame. The verdict comes from `results.json`. `◀ Editor` is
owned by the parent page; the score chip reopens the immutable v3 artifact via
its canonical `?replay=` URL. Runs live under `build/studio/runs/<run-id>/` as
`replay.bin`, `results.json`, and `studio.json`.

## Saving and validation

Save writes the exact pretty-printed JSON shown in Compiled ruleset. Valid
documents are replaced atomically. Invalid documents are not written unless the
user explicitly confirms Force save; forced files remain marked invalid in the
file list. Filenames must match `[A-Za-z0-9._-]+.json` and cannot escape
`rulesets/`.

## Tests

Run the complete offline suite and the direct Blockly round-trip suite:

```sh
PYTHONPATH=src .venv/bin/python -m pytest
PYTHON=.venv/bin/python node tools/test_ruleset_studio.mjs
node tools/test_viewer.mjs
node tools/test_ruleset_studio_browser.mjs
```

For a focused syntax check:

```sh
node --check ruleset-studio/src/blocks.js
node --check ruleset-studio/src/studio.js
node --check ruleset-studio/src/play.js
```

If launch fails, the launcher names the missing Node or Metta bridge path. If
the UI says API unavailable, stop stale launchers and restart; dynamic ports are
printed in the studio URL. If chat says Not connected, run the printed bridge
watch command without restarting the editor.

If live preview is unavailable but the run completes, use the score chip or
Open canonical replay; the v3 artifact is independent of live transport. A
pruned run shows a recoverable expired state and leaves the canvas unchanged.
