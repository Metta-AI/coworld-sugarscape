> [!WARNING]
> **ARCHIVAL ONLY.** This document describes the frozen Sugarscape v1 implementation under `archived/v1/`. Do not use it as current implementation guidance.

# Differential oracle

This directory preserves the behavior of
[`nkremerh/sugarscape`](https://github.com/nkremerh/sugarscape) at:

```text
a46ec6ff909e2bc73a4c9e9f36b2aed160eccad8
```

The only repository-local changes to the pinned source are the archival header
comments required after Sugarscape v1 was retired. Executable behavior remains
the compatibility oracle for this archived port.

It is vendored under the upstream Unlicense solely as the executable behavioral
oracle and scenario corpus for Python-versus-Nim differential tests. Production
artifacts do not execute or include this Python implementation.
