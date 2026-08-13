# Art attribution

`gnomes.aseprite` is a byte-for-byte copy of `data/gnomes.aseprite` from
[heartleaf](https://github.com/Metta-AI/heartleaf), vendored here so that
`tools/export_settler.nim` reproduces the settler atlas from a file inside this
repository rather than from a checkout somewhere else on the machine.

Only the front-facing pose of one character is used, and only as the source for
a 16x16 palette-indexed reduction; the shipped atlas is
`src/sugarscape/sprites/settler.json`.

The `.aseprite` is committed but is not read at build time and is not part of
the served document. Confirm with the owner that heartleaf's art may ship inside
this repository's public embed before merging.
