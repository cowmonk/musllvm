#!/bin/sh
set -eu

source ./scripts/config.sh

ELF_TAR=$(ls ./sources/elftoolchain-*.tar.* 2>/dev/null | head -n 1 | xargs basename)
if [ -z "$ELF_TAR" ]; then
        echo "ERR: No Musl tarball found in sources directory"
        exit 1
fi
ELF_SOURCE="${ELF_TAR%%.tar.*}"

if command -v "clang" >/dev/null 2>&1 && command -v "lld" >/dev/null 2>&1; then
        export CC="clang"
else
        export CC="cc"
fi

if [ ! -d ./build/"$ELF_SOURCE" ]; then
        echo "Extracting Elftoolchain tarball to ./build/"
        tar -xpf ./sources/"$ELF_TAR" -C ./build
else
        echo "Elftoolchain source already extracted."
fi

echo "Buliding musl headers"
if [ -f "./build/$ELF_SOURCE" ]; then
        echo "ELFTOOLCHAIN  already built, skipping..."
        exit
fi

cd ./build/"$ELF_SOURCE"

echo "patching elftoolchain-cross..."

patch -Np1 < ../../patches/elftoolchain/*

echo "Installing elftoolchain-cross..."

bmake WITH_ADDITIONAL_DOCUMENTATION=no \
      WITH_TESTS=no \
      MANTARGET=man
