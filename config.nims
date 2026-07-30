## CPython rounds each primitive floating-point operation. Prevent the C
## compiler from contracting multiply-add expressions in optimized builds.
switch("passC", "-ffp-contract=off")
