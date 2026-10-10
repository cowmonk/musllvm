#!/bin/sh
set -eu
prefix=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)

quote()
{
	printf "'"
	printf '%s' "$1" | sed "s/'/'\\\\''/g"
	printf "'"
}

emit()
{
	printf 'export %s=' "$1"
	quote "$2"
	printf '\n'
}

emit MUSLLVM_HOME "$prefix"
emit MUSLLVM_SYSROOT "$prefix/sysroot"
emit TARGET @TARGET@
emit PATH "$prefix/bin:$PATH"
for pair in CC:cc CXX:c++ AR:ar RANLIB:ranlib NM:nm STRIP:strip \
	OBJCOPY:objcopy OBJDUMP:objdump READELF:readelf LD:ld PKG_CONFIG:pkg-config; do
	emit "${pair%%:*}" "$prefix/bin/@TARGET@-${pair#*:}"
done
emit CMAKE_TOOLCHAIN_FILE "$prefix/share/musllvm/toolchain.cmake"
