#!/bin/sh
set -eu
prefix=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
sysroot=${MUSLLVM_SYSROOT:-$prefix/sysroot}
PKG_CONFIG_SYSROOT_DIR=$sysroot
PKG_CONFIG_LIBDIR="$sysroot/usr/lib/pkgconfig:$sysroot/usr/share/pkgconfig"
PKG_CONFIG_PATH=${MUSLLVM_PKG_CONFIG_PATH:-}
export PKG_CONFIG_SYSROOT_DIR PKG_CONFIG_LIBDIR PKG_CONFIG_PATH
exec pkg-config "$@"
