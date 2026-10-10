#!/bin/sh
set -eu
prefix=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
exec "$prefix/libexec/ld.lld" --sysroot="${MUSLLVM_SYSROOT:-$prefix/sysroot}" "$@"
