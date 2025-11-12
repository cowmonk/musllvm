#/bin/sh

ARCH=$(uname -m)
FROOT="${ARCH}-musllvm"
LINUX_TAR=$(printf '%s' "$url" | sed -E 's/[?#].*$//' | sed -E 's!.*/!!' | grep -i linux)
LINUX_SOURCE="${LINUX_TAR%%.tar*}"

if command -v "clang" >/dev/null 2>&1 && command -v "lld" >/dev/null 2>&1; then
        export LLVM=1
        export LLVM=IAS
fi

tar -xpf ./sources/${LINUX_TAR} ./build

mkdir -pv ./build/${FROOT}/include

echo "Building Headers"
pushd ./build/${LINUX_SOURCE}

make mrproper
make headers
find usr/include \( -name .install -o -name ..install.cmd \) -exec rm -vf {} \;
cp -rv usr/include/* ../${FROOT}/include/
rm -v ../${FROOT}/include/Makefile

popd

