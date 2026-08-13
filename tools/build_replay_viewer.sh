#!/bin/sh
set -eu

output_dir=${1:?usage: tools/build_replay_viewer.sh OUTPUT_DIR}
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../replay-viewer" && pwd)

mkdir -p "$output_dir"
cp "$source_dir/index.html" "$output_dir/index.html"


