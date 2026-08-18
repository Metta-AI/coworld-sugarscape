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

The launcher chooses free loopback ports, starts both local servers, opens the
browser, and prints the exact `link-bridge.mjs watch` command for the current
ports. Run that printed command in the coding session that should answer chat.
After a reply, run the same command again to re-arm the one-reply watch. There
is no submit or completion lifecycle: Save is the only persistence operation.

Use `--no-open` to suppress browser opening, `--metta-root PATH` for another
read-only Metta checkout, or `--link-port`/`--api-port` to prefer other ports.
Ctrl-C, SIGTERM, or closing the studio tab stops both child servers.

## How it fits together

- `src/` is the complete static app. It includes the pinned, offline Blockly
  browser build at `src/vendor/blockly/` and loads the ux.surface
  `/link-client.js` from the local link server.
- `server.py` is a stdlib-only loopback API. It lists, loads, validates, and
  atomically saves `rulesets/*.json`; it imports `coworld.ruleset.parse_ruleset`
  rather than duplicating the SugarLang contract.
- `tools/ruleset_studio.py` supervises that API and Metta's read-only
  ux.surface link server. The browser receives the selected API port in its
  query string, and CORS accepts only the matching link-server origin.

The context selector merges the pinned DTL runtime defaults, root `config.json`,
variant config, then scenario overrides. Disabled traits display the effective
DTL factor range; enabled values are clamped to the selected context's
`trait_ranges`.

Agent replies may propose `{set: {ruleset: ..., note: ...}}`. The UI validates
the full replacement with the Python API before offering it, then applies it as
one custom Blockly event so a single Undo restores the prior ruleset. A missing
bridge affects chat only.

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
```

For a focused syntax check:

```sh
node --check ruleset-studio/src/blocks.js
node --check ruleset-studio/src/studio.js
```

If launch fails, the launcher names the missing Node or Metta bridge path. If
the UI says API unavailable, stop stale launchers and restart; dynamic ports are
printed in the studio URL. If chat says Not connected, run the printed bridge
watch command without restarting the editor.
