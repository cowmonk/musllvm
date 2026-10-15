#!/bin/sh
set -eu

prefix=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
sysroot=${MUSLLVM_SYSROOT:-$prefix/sysroot}
unset CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH OBJC_INCLUDE_PATH LIBRARY_PATH
unset GCC_EXEC_PREFIX COMPILER_PATH
link=yes
for argument do
	case "$argument" in
	-c|-S|-E|-M|-MM|-fsyntax-only|-nostdlib|-nodefaultlibs|-r) link=no ;;
	esac
done
[ "$link" = no ] || set -- "$@" -latomic
case "${0##*/}" in
*++|*-c++)
	set -- --driver-mode=g++ -nostdinc++ -isystem "$sysroot/usr/include/c++/v1" "$@" ;;
esac
exec "$prefix/libexec/clang" --no-default-config --config="$prefix/share/musllvm/clang.cfg" \
	--sysroot="$sysroot" "$@"
