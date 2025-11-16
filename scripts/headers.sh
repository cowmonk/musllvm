#!/bin/sh
set -eu

. $PWD/scripts/config.sh

LINUX_TAR=$(ls "$PROOT"/sources/linux-*.tar.* 2>/dev/null | head -n 1 | xargs basename)
if [ -z "$LINUX_TAR" ]; then
        echo "ERR: No Linux tarball found in sources directory"
        exit 1
fi
LINUX_SOURCE="${LINUX_TAR%%.tar*}"

if command -v "clang" >/dev/null 2>&1 && command -v "lld" >/dev/null 2>&1; then
        export LLVM=1
        export LLVM_IAS=1
fi

if [ ! -d $PROOT/build/"$LINUX_SOURCE" ]; then
        echo "Extracting Linux tarball to ./build/"
        tar -xpf $PROOT/sources/"$LINUX_TAR" -C $PROOT/build
else
        echo "Linux source already extracted."
fi

echo "Creating target include directory"
mkdir -pv $PROOT/build/"$FROOT"/include

echo "Building Headers"
if [ -d $PROOT/build/"$FROOT"/include/linux ]; then
        echo "Headers already built, skipping..."
        exit
fi

cd ./build/"$LINUX_SOURCE"

make mrproper
make headers
find usr/include -type f ! -name '*.h' -delete
cp -rv usr/include/* $PROOT/build/"$FROOT"/include/

