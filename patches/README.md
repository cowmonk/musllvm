patches
=======

These patches come from Chimera Linux's [cports tree](https://github.com/chimera-linux/cports/tree/8c138d9ee1cebf0f16d32b56193044c20a46a5f4/main)
at 8c138d9ee1cebf0f16d32b56193044c20a46a5f4, checked on 2026-10-19.
The build applies each component's .patch files in filename order.

llvm
====

For LLVM 23.1.3:

* 0001 gives LLVM worker threads an 8 MiB stack, including on musl hosts.
  Its context was updated for LLVM 23; the change matches Chimera's patch.
* 0002 removes musl's large file macros before LLVM declares matching names.
* 0011 builds the C exception personality with LLVM's unwind headers during
  the compiler-rt bootstrap. The builtins configuration adds libunwind's
  source include directory so unwind.h can find its nested headers.

The Clang configuration and CMake settings cover Chimera's hardening,
libatomic, library layout and typeinfo defaults. The build also uses
Chimera's fast libc++ hardening mode and disables outline atomics when
building libatomic for aarch64.

musl
====

For musl 1.2.6:

* 001 through 008 are upstream fixes carried by Chimera for DNS, strptime,
  regular expressions, GB18030 conversion, iswalnum and qsort.
* nxthdr.patch fixes signedness and alignment warnings in CMSG_NXTHDR.

The toolchain keeps musl's stock allocator. Chimera's allocator integration,
PowerPC changes and LLVM sanitizer patches do not apply to this build.
