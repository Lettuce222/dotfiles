#!/bin/sh
# Compatibility for older checkout instructions. The installer lives in Rust.
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$root/setup" ]; then
    exec "$root/setup" "$@"
fi
printf '%s\n' 'Build the Rust installer first:' \
    '  cargo build --locked --release --manifest-path tools/installer/Cargo.toml' \
    '  cp tools/installer/target/release/setup ./setup' >&2
exit 1
