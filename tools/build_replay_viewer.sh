#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir=${1:-}

case "$output_dir" in
  "$repo_dir"/*) ;;
  *)
    echo "replay viewer output must be an absolute path inside $repo_dir" >&2
    exit 1
    ;;
esac

if [ "$output_dir" = "$repo_dir" ] || [ "$output_dir" = "$repo_dir/build" ]; then
  echo "unsafe replay viewer output: $output_dir" >&2
  exit 1
fi

rm -rf -- "$output_dir"
mkdir -p -- "$output_dir"

if [ ! -x "$repo_dir/node_modules/.bin/asc" ]; then
  echo "missing replay viewer dependencies; run npm ci" >&2
  exit 1
fi

"$repo_dir/node_modules/.bin/asc" \
  "$repo_dir/replay-viewer/timeline.ts" \
  --config "$repo_dir/asconfig.json" \
  --target release \
  --outFile "$output_dir/timeline.wasm"
cp "$repo_dir/src/sugarscape/viewer.html" "$output_dir/index.html"
