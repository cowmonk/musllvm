#!/bin/sh
set -eu

. $PWD/scripts/config.sh

MUSL_TAR=$(ls "$PROOT"/sources/musl-*.tar.* 2>/dev/null | head -n 1 | xargs basename)
if [ -z "$MUSL_TAR" ]; then
        echo "ERR: No Musl tarball found in sources directory"
        exit 1
fi
MUSL_SOURCE="${MUSL_TAR%%.tar.*}"

if command -v "clang" >/dev/null 2>&1 && command -v "lld" >/dev/null 2>&1; then
        export CC="clang"
else
        export CC="cc"
fi

if [ ! -d $PROOT/build/"MUSL_SOURCE" ]; then
        echo "Extracting Musl tarball to ./build/"
        tar -xpf ./sources/"$MUSL_TAR" -C ./build
else
        echo "Musl source already extracted."
fi

echo "Buliding musl headers"
if [ -f "$PROOT/build/$MUSL_SOURCE" ]; then
        echo "Musl headers already built, skipping..."
        exit
fi

cd $PROOT/build/"$MUSL_SOURCE"

echo "Installing musl headers..."
./configure \
	--prefix=/

DESTDIR=$CROSS make ARCH=$(uname -m) install-headers
