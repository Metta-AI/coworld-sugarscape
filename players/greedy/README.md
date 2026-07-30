# Sugarscape greedy population policy

This bundled certification policy controls one configured population. For every
observation it chooses `candidates[0]`, the DTL-compatible greedy-best legal
destination supplied by the game.

The Coworld runner provides the authenticated socket through
`COWORLD_PLAYER_WS_URL`; `COGAMES_ENGINE_WS_URL` is accepted as a legacy alias.

`coplayer_manifest.json` retains a registry placeholder until a published image
URI exists. For local and Coworld builds, use `players/greedy/Dockerfile` and
the `{{PLAYER_IMAGE}}` substitution in the root `coworld_manifest.json`.
