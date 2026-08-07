> [!WARNING]
> **ARCHIVAL ONLY.** This document describes the frozen Sugarscape v1 implementation under `archived/v1/`. Do not use it as current implementation guidance.

# Sugarscape greedy player policy

This bundled certification policy controls one configured agent. For every
observation it chooses `candidates[0]`, the DTL-compatible greedy-best legal
destination supplied by the game.

The Coworld runner provides the authenticated socket through
`COWORLD_PLAYER_WS_URL`; `COGAMES_ENGINE_WS_URL` is accepted as a legacy alias.

`coplayer_manifest.json` retains a registry placeholder until a published image
URI exists. For local and Coworld builds, use `players/greedy/Dockerfile` and
the `{{PLAYER_IMAGE}}` substitution in the root `coworld_manifest.json`.
