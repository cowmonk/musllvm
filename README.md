musllvm
========

A simple make build system for a musl Clang/LLVM cross toolchain.
Targets x86_64 and aarch64 Linux.

The toolchain includes musl, compiler-rt, libc++, libc++abi,
LLVM libunwind and libatomic. Compiler tools run on the build host.


downloads
=========

[Releases](https://github.com/cowmonk/musllvm/releases) provide archives
for x86_64-linux-musl and aarch64-linux-musl. Both run on x86_64 Linux
hosts with glibc 2.39 or newer. The compiler tools are included.
Target programs use musl.

Download an archive and SHA256SUMS from the same release, then check
the archive you downloaded:

    sha256sum --ignore-missing -c SHA256SUMS
    tar -xJf musllvm-x86_64-linux-musl-host-x86_64-linux.tar.xz
    eval "$(musllvm-x86_64-linux-musl/bin/x86_64-linux-musl-env)"

Each archive includes its source pins, licenses and build information under
share/musllvm/. pkg-config is optional and uses the host installation.


dependencies
============

Build on a Linux host with:

    clang/llvm    Clang 19 or newer, clang++, LLD, LLVM utilities and
                  matching llvm-config and LLVM CMake metadata (system mode)
    make          GNU make
    cmake         3.20 or newer
    ninja
    python3
    perl
    curl
    tar           gzip and xz support
    sha256sum
    rsync

pkg-config is needed for the target pkg-config wrapper. qemu-aarch64 is
optional for running aarch64 checks on an x86_64 host.


building
========

    make doctor
    make

Defaults to x86_64 with two build jobs. For aarch64:

    make ARCH=aarch64

LLVM_MODE=system uses the installed host tools and builds the target
libraries from pinned sources. Keep the host LLVM installation available.

To also build Clang, LLD and the LLVM utilities from source:

    make LLVM_MODE=source ARCH=x86_64 JOBS=2 LINK_JOBS=1 \
        PREFIX="$PWD/build/x86_64-source" BUILD_DIR="$PWD/build/work/x86_64-source"

Source mode installs host tools under PREFIX/host. These tools use the
host libc. Both modes produce a cross toolchain.


configuration
=============

Edit [config.mk](config.mk) or override settings through make.

    ARCH             x86_64                 x86_64 or aarch64
    TARGET           $(ARCH)-linux-musl     target triple
    PREFIX           build/$(TARGET)        toolchain installation
    BUILD_DIR        build/work/$(TARGET)   build files and completed stages
    LLVM_MODE        system                 system or source
    JOBS             2                      compilation jobs
    LINK_JOBS        1                      parallel links when building LLVM
    TARGET_CFLAGS    -O2                    target library flags
    RUNNER                                  emulator executable (optional)

Each target has its own prefix and work directory. Downloaded and
extracted sources are shared. Build paths must have no whitespace or
shell metacharacters.


usage
=====

After building, load the toolchain into your current shell:

    eval "$(build/x86_64-linux-musl/bin/x86_64-linux-musl-env)"
    "$CC" hello.c -o hello
    "$CC" -static hello.c -o hello-static
    "$CXX" -std=c++20 hello.cpp -o hello-cxx

The environment command sets CC, CXX, LLVM binutils, LD, PKG_CONFIG,
TARGET, MUSLLVM_SYSROOT and CMAKE_TOOLCHAIN_FILE. Use the environment
command matching your target and installation path.

The compiler wrappers select the target, sysroot, LLD and target runtimes.
They remove host header and library environment paths. The pkg-config
wrapper searches the target sysroot.

For CMake:

    cmake -S . -B out -G Ninja \
        -DCMAKE_TOOLCHAIN_FILE="$CMAKE_TOOLCHAIN_FILE"
    cmake --build out

The sysroot is under PREFIX/sysroot, with headers in usr/include,
libraries in usr/lib and the musl loader in lib. Compiler-rt is in the
toolchain's Clang resource directory.

Set MUSLLVM_SYSROOT to use another copy of the sysroot. Set
MUSLLVM_PKG_CONFIG_PATH to add target pkg-config directories.


sources and resuming
====================

[sources.list](sources.list) pins archive names, URLs and SHA-256 digests.
Downloads enter the cache after checksum verification.

    make pull
    make verify-sources
    make show-config

Run the same command after a failed build to resume completed stages.
Changes to the target, source pins, compiler, paths, build recipes or
library flags require make clean with the same ARCH, PREFIX and BUILD_DIR.
Cleaning removes that toolchain and its work directory, but keeps the
downloaded and extracted sources. Changing JOBS does not require cleaning.

A running build holds a lock in BUILD_DIR/lock. After a forced termination,
check that the build process has stopped before removing a leftover lock
with rmdir.

The older Chimera patches in patches/ are kept as references. They are
not applied to the pinned LLVM release.


checks
======

    make check

Runs shell syntax checks and driver tests with mocked tools. This does
no compilation or downloads.

A completed build also runs make verify. This compiles static and dynamic
C and C++ programs, checks their ELF architecture and runtime dependencies,
and tests the CMake toolchain file. Programs run when the host architecture
matches the target or RUNNER names an emulator.

    make verify ARCH=aarch64 RUNNER=qemu-aarch64

[CI](.github/workflows/ci.yml) runs offline tests and both target builds.
A manual workflow run can also build LLVM from source.


publishing
==========

[The release workflow](.github/workflows/release.yml) runs on pushes to
main that change sources.list, config.mk, Makefile, scripts/, files/,
patches/ or the compiler smoke tests. This covers source version updates
and new core components added to the build. README edits do not publish
a release. The workflow can also be run manually from main.

Both targets build with LLVM_MODE=source. Each archive is unpacked into
a new location and tested before upload. The release is published after
both builds pass, with SHA256SUMS and sources.list attached.
Tags use musllvm-YYYY-MM-DD-COMMIT, with the first 12 commit characters.
Rerunning a published commit keeps its release assets.

To package a completed source build yourself:

    make package LLVM_MODE=source ARCH=x86_64

Archives go to build/releases/. Set DIST_DIR to change the output directory.
The first release still needs verification on GitHub Actions.


credits
========

* [Chimera Linux](https://chimera-linux.org) - original patches and libatomic
* [CMLFS](https://github.com/dslm4515/CMLFS) - build script references
* [Mussel](https://github.com/firasuke/mussel) - musl cross compiler references
* [musl.cc](https://musl.cc) - cross compiler resources
