#!/bin/sh
set -eu

. "$(dirname "$0")/config.sh"

TOOLS='clang clang++ ld.lld llvm-ar llvm-ranlib llvm-nm llvm-objcopy llvm-objdump llvm-readelf llvm-strip llvm-size llvm-strings llvm-addr2line llvm-cxxfilt'

doctor()
{
	for program in make cmake ninja python3 perl tar xz curl sha256sum rsync patch; do
		need "$program"
	done
	need "$HOST_CC"
	need "$HOST_CXX"
	if [ "$LLVM_MODE" = system ]; then
		"$HOST_CC" --version | head -n 1 | awk '/clang/ { found=1 } END { exit !found }' ||
			die "LLVM_MODE=system requires Clang; set HOST_CC=clang"
		clang_major=$("$HOST_CC" -dumpversion)
		clang_major=${clang_major%%.*}
		[ "$clang_major" -ge 21 ] 2>/dev/null || die "LLVM_MODE=system requires Clang 21 or newer"
		for program in $TOOLS llvm-config; do need "$program"; done
		llvm_cmake=$(llvm-config --cmakedir)
		[ -f "$llvm_cmake/LLVMConfig.cmake" ] || die "LLVM CMake metadata missing; install the matching LLVM development package"
	fi
	printf 'Host dependencies OK (%s LLVM, %s target, %s jobs)\n' "$LLVM_MODE" "$TARGET" "$JOBS"
}

configure_llvm()
{
	cmake -S "$LLVM_SOURCE/llvm" -B "$BUILD_DIR/llvm" -G Ninja \
		-DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX/host" \
		-DCMAKE_C_COMPILER="$BOOTSTRAP_CC" -DCMAKE_CXX_COMPILER="$BOOTSTRAP_CXX" \
		-DCMAKE_C_FLAGS="$HOST_CFLAGS" -DCMAKE_CXX_FLAGS="$HOST_CXXFLAGS" \
		-DCMAKE_EXE_LINKER_FLAGS="$HOST_LDFLAGS" \
		-DLLVM_ENABLE_PROJECTS='clang;lld' -DLLVM_TARGETS_TO_BUILD='X86;AArch64' \
		-DLLVM_DISTRIBUTION_COMPONENTS='clang;clang-resource-headers;lld;llvm-ar;llvm-ranlib;llvm-nm;llvm-objcopy;llvm-objdump;llvm-readelf;llvm-strip;llvm-size;llvm-strings;llvm-addr2line;llvm-cxxfilt' \
		-DLLVM_PARALLEL_LINK_JOBS="$LINK_JOBS" -DLLVM_ENABLE_ASSERTIONS=OFF \
		-DLLVM_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF \
		-DLLVM_INCLUDE_EXAMPLES=OFF -DLLVM_ENABLE_BINDINGS=OFF \
		-DLLVM_ENABLE_ZLIB=OFF -DLLVM_ENABLE_ZSTD=OFF -DLLVM_ENABLE_LIBXML2=OFF \
		-DLLVM_ENABLE_LIBEDIT=OFF -DCLANG_ENABLE_ARCMT=OFF -DCLANG_ENABLE_STATIC_ANALYZER=OFF
}

done_stage()
{
	[ -f "$BUILD_DIR/stamps/$1" ]
}

mark_stage()
{
	touch "$BUILD_DIR/stamps/$1"
}

toolchain()
{
	if [ "$LLVM_MODE" = source ]; then
		if ! done_stage llvm; then
			configure_llvm
			cmake --build "$BUILD_DIR/llvm" --parallel "$JOBS" --target distribution
			cmake --build "$BUILD_DIR/llvm" --target install-distribution
			mark_stage llvm
		fi
		HOST_CLANG="$PREFIX/host/bin/clang"
		HOST_CLANGXX="$PREFIX/host/bin/clang++"
		HOST_LLD="$PREFIX/host/bin/ld.lld"
		LLVM_CMAKE_DIR="$BUILD_DIR/llvm/lib/cmake/llvm"
	else
		HOST_CLANG=$BOOTSTRAP_CC
		HOST_CLANGXX=$BOOTSTRAP_CXX
		HOST_LLD=$(command -v ld.lld)
		LLVM_CMAKE_DIR=$(llvm-config --cmakedir)
	fi
	HOST_RESOURCE=$("$HOST_CLANG" -print-resource-dir)
	RESOURCE_VERSION=${HOST_RESOURCE##*/}
	case "$RESOURCE_VERSION" in
	*[!0-9.]*|'') die "unexpected Clang resource directory: $HOST_RESOURCE" ;;
	esac
	RESOURCE_DIR="$PREFIX/lib/clang/$RESOURCE_VERSION"
	mkdir -p "$PREFIX/libexec" "$RESOURCE_DIR/lib/linux" "$SYSROOT/usr/lib" "$BUILD_DIR/empty-gcc"
	for program in $TOOLS; do
		if [ "$LLVM_MODE" = source ]; then
			tool_path="../host/bin/$program"
		else
			case "$program" in
			clang) tool_path=$HOST_CLANG ;;
			clang++) tool_path=$HOST_CLANGXX ;;
			*) tool_path=$(command -v "$program") ;;
			esac
		fi
		ln -sf "$tool_path" "$PREFIX/libexec/$program"
	done
	if ! done_stage toolchain; then
		cp -R "$HOST_RESOURCE/include" "$RESOURCE_DIR/"
		mark_stage toolchain
	fi
}

configure_musl()
{
	mkdir -p "$BUILD_DIR/musl"
	cat > "$BUILD_DIR/musl-cc" <<EOF
#!/bin/sh
exec "$HOST_CLANG" --target="$TARGET" --sysroot="$SYSROOT" \\
	--gcc-toolchain="$BUILD_DIR/empty-gcc" -resource-dir="$RESOURCE_DIR" \\
	--ld-path="$HOST_LLD" --rtlib=compiler-rt --unwindlib=none "\$@"
EOF
	chmod 755 "$BUILD_DIR/musl-cc"
	(
		cd "$BUILD_DIR/musl"
		CC="$BUILD_DIR/musl-cc" \
		AR="$PREFIX/libexec/llvm-ar" RANLIB="$PREFIX/libexec/llvm-ranlib" \
		CFLAGS="$TARGET_CFLAGS" LIBCC="$RESOURCE_DIR/lib/linux/libclang_rt.builtins-$ARCH.a" \
		"$MUSL_SOURCE/configure" --target="$TARGET" --prefix=/usr --syslibdir=/lib \
			--disable-wrapper
	)
}

headers()
{
	if ! done_stage headers; then
		mkdir -p "$SYSROOT/usr/include" "$BUILD_DIR/linux"
		make -C "$LINUX_SOURCE" O="$BUILD_DIR/linux" ARCH="$KERNEL_ARCH" \
			HOSTCC="$BOOTSTRAP_CC" INSTALL_HDR_PATH="$SYSROOT/usr" headers_install
		configure_musl
		make -C "$BUILD_DIR/musl" -j "$JOBS" DESTDIR="$SYSROOT" install-headers
		mark_stage headers
	fi
}

target_cmake()
{
	cmake -G Ninja -DCMAKE_BUILD_TYPE=Release \
		-DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR="$ARCH" \
		-DCMAKE_C_COMPILER="$HOST_CLANG" -DCMAKE_CXX_COMPILER="$HOST_CLANGXX" \
		-DCMAKE_ASM_COMPILER="$HOST_CLANG" -DCMAKE_C_COMPILER_TARGET="$TARGET" \
		-DCMAKE_CXX_COMPILER_TARGET="$TARGET" -DCMAKE_ASM_COMPILER_TARGET="$TARGET" \
		-DCMAKE_SYSROOT="$SYSROOT" -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY \
		-DCMAKE_C_FLAGS="$TARGET_CFLAGS --gcc-toolchain='$BUILD_DIR/empty-gcc' -resource-dir='$RESOURCE_DIR'" \
		-DCMAKE_CXX_FLAGS="$TARGET_CFLAGS --gcc-toolchain='$BUILD_DIR/empty-gcc' -resource-dir='$RESOURCE_DIR'" \
		-DCMAKE_ASM_FLAGS="--gcc-toolchain='$BUILD_DIR/empty-gcc' -resource-dir='$RESOURCE_DIR'" \
		-DCMAKE_EXE_LINKER_FLAGS="--ld-path='$HOST_LLD' --rtlib=compiler-rt --unwindlib=none -resource-dir='$RESOURCE_DIR'" \
		-DCMAKE_SHARED_LINKER_FLAGS="--ld-path='$HOST_LLD' --rtlib=compiler-rt --unwindlib=none -resource-dir='$RESOURCE_DIR'" \
		-DCMAKE_MODULE_LINKER_FLAGS="--ld-path='$HOST_LLD' --rtlib=compiler-rt --unwindlib=none -resource-dir='$RESOURCE_DIR'" \
		-DCMAKE_AR="$PREFIX/libexec/llvm-ar" -DCMAKE_RANLIB="$PREFIX/libexec/llvm-ranlib" \
		-DCMAKE_NM="$PREFIX/libexec/llvm-nm" -DLLVM_ENABLE_PER_TARGET_RUNTIME_DIR=OFF "$@"
}

builtins()
{
	if ! done_stage builtins; then
		target_cmake -S "$LLVM_SOURCE/compiler-rt" -B "$BUILD_DIR/builtins" \
			-DLLVM_CMAKE_DIR="$LLVM_CMAKE_DIR" \
			-DCMAKE_C_STANDARD_INCLUDE_DIRECTORIES="$LLVM_SOURCE/libunwind/include" \
			-DCMAKE_INSTALL_PREFIX="$RESOURCE_DIR" -DCOMPILER_RT_INSTALL_PATH="$RESOURCE_DIR" \
			-DCOMPILER_RT_DEFAULT_TARGET_ONLY=ON \
			-DCOMPILER_RT_BUILD_BUILTINS=ON -DCOMPILER_RT_EXCLUDE_ATOMIC_BUILTIN=ON \
			-DCOMPILER_RT_BUILD_CRT=ON -DCOMPILER_RT_BUILD_SANITIZERS=OFF \
			-DCOMPILER_RT_BUILD_XRAY=OFF -DCOMPILER_RT_BUILD_LIBFUZZER=OFF \
			-DCOMPILER_RT_BUILD_PROFILE=OFF -DCOMPILER_RT_BUILD_MEMPROF=OFF \
			-DCOMPILER_RT_BUILD_CTX_PROFILE=OFF -DCOMPILER_RT_BUILD_ORC=OFF \
			-DCOMPILER_RT_BUILD_GWP_ASAN=OFF -DCOMPILER_RT_INCLUDE_TESTS=OFF
		cmake --build "$BUILD_DIR/builtins" --parallel "$JOBS"
		cmake --install "$BUILD_DIR/builtins"
		mark_stage builtins
	fi
}

musl()
{
	if ! done_stage musl; then
		builtins_archive=$("$HOST_CLANG" --target="$TARGET" -resource-dir="$RESOURCE_DIR" \
			--rtlib=compiler-rt -print-libgcc-file-name)
		[ -f "$builtins_archive" ] || die "compiler-rt archive not found: $builtins_archive"
		make -C "$BUILD_DIR/musl" -j "$JOBS" "LIBCC=$builtins_archive"
		make -C "$BUILD_DIR/musl" "LIBCC=$builtins_archive" DESTDIR="$SYSROOT" install
		ln -sf ../usr/lib/libc.so "$SYSROOT/lib/ld-musl-$ARCH.so.1"
		mark_stage musl
	fi
}

atomic()
{
	if ! done_stage atomic; then
		atomic_cflags=$TARGET_CFLAGS
		if [ "$ARCH" = aarch64 ]; then
			atomic_cflags="$atomic_cflags -mno-outline-atomics"
		fi
		mkdir -p "$BUILD_DIR/atomic"
		cp "$ATOMIC_SOURCE/atomic.c" "$ATOMIC_SOURCE/Makefile" "$BUILD_DIR/atomic/"
		make -C "$BUILD_DIR/atomic" -j "$JOBS" CC="$BUILD_DIR/musl-cc" \
			AR="$PREFIX/libexec/llvm-ar" CFLAGS="$atomic_cflags"
		make -C "$BUILD_DIR/atomic" CC="$BUILD_DIR/musl-cc" \
			AR="$PREFIX/libexec/llvm-ar" CFLAGS="$atomic_cflags" PREFIX=/usr DESTDIR="$SYSROOT" install
		mark_stage atomic
	fi
}

runtimes()
{
	if ! done_stage runtimes; then
		# musl lacks __cxa_thread_atexit_impl
		# compile only probes cannot detect missing symbols
		# typeinfo comparison 2 also compares names, as libstdc++ does (chimera)
		target_cmake -S "$LLVM_SOURCE/runtimes" -B "$BUILD_DIR/runtimes" \
			-DCMAKE_INSTALL_PREFIX=/usr -DLLVM_ENABLE_RUNTIMES='libunwind;libcxxabi;libcxx' \
			-DLIBCXX_HAS_MUSL_LIBC=ON -DLIBCXX_USE_COMPILER_RT=ON \
			-DLIBCXX_TYPEINFO_COMPARISON_IMPLEMENTATION=2 \
			-DLIBCXX_HARDENING_MODE=fast \
			-DLIBCXX_CXX_ABI=libcxxabi -DLIBCXX_ENABLE_SHARED=ON -DLIBCXX_ENABLE_STATIC=ON \
			-DLIBCXX_STATICALLY_LINK_ABI_IN_STATIC_LIBRARY=ON \
			-DLIBCXX_STATICALLY_LINK_ABI_IN_SHARED_LIBRARY=OFF -DLIBCXX_ENABLE_ABI_LINKER_SCRIPT=ON \
			-DLIBCXX_INCLUDE_TESTS=OFF -DLIBCXX_INCLUDE_BENCHMARKS=OFF \
			-DLIBCXXABI_USE_COMPILER_RT=ON -DLIBCXXABI_USE_LLVM_UNWINDER=ON \
			-DLIBCXXABI_HAS_CXA_THREAD_ATEXIT_IMPL=OFF \
			-DLIBCXXABI_ENABLE_SHARED=ON -DLIBCXXABI_ENABLE_STATIC=ON \
			-DLIBCXXABI_INCLUDE_TESTS=OFF -DLIBUNWIND_USE_COMPILER_RT=ON \
			-DLIBUNWIND_ENABLE_SHARED=ON -DLIBUNWIND_ENABLE_STATIC=ON \
			-DLIBUNWIND_INCLUDE_TESTS=OFF
		cmake --build "$BUILD_DIR/runtimes" --parallel "$JOBS"
		DESTDIR="$SYSROOT" cmake --install "$BUILD_DIR/runtimes"
		mark_stage runtimes
	fi
}

wrappers()
{
	mkdir -p "$PREFIX/bin" "$PREFIX/share/musllvm/empty-gcc"
	for pair in cc:cc.sh c++:cc.sh ld:ld.sh pkg-config:pkg-config.sh env:env.sh; do
		wrapper="$PREFIX/bin/$TARGET-${pair%%:*}"
		sed -e "s/@TARGET@/$TARGET/g" -e "s/@RESOURCE_VERSION@/$RESOURCE_VERSION/g" \
			"$PROOT/files/toolchain/${pair#*:}" > "$wrapper"
		chmod 755 "$wrapper"
	done
	for alias in clang gcc; do ln -sf "$TARGET-cc" "$PREFIX/bin/$TARGET-$alias"; done
	for alias in clang++ g++; do ln -sf "$TARGET-c++" "$PREFIX/bin/$TARGET-$alias"; done
	for pair in ar:ar ranlib:ranlib nm:nm objcopy:objcopy objdump:objdump \
		readelf:readelf strip:strip size:size strings:strings addr2line:addr2line c++filt:cxxfilt; do
		ln -sf "../libexec/llvm-${pair#*:}" "$PREFIX/bin/$TARGET-${pair%%:*}"
	done
	sed -e "s/@TARGET@/$TARGET/g" -e "s/@ARCH@/$ARCH/g" \
		"$PROOT/files/toolchain/toolchain.cmake" > "$PREFIX/share/musllvm/toolchain.cmake"
	sed -e "s/@TARGET@/$TARGET/g" -e "s/@RESOURCE_VERSION@/$RESOURCE_VERSION/g" \
		"$PROOT/files/toolchain/clang.cfg" > "$PREFIX/share/musllvm/clang.cfg"
	printf '%s\n' "$RESOURCE_VERSION" > "$PREFIX/share/musllvm/resource-version"
	if [ -d "$PROOT/patches" ]; then
		cp -R "$PROOT/patches" "$PREFIX/share/musllvm/"
	fi
	printf 'Toolchain ready: %s\n' "$PREFIX"
}

stage=${1:-all}
case "$stage" in
config)
	printf 'ARCH=%s\nTARGET=%s\nLLVM_MODE=%s\nPREFIX=%s\nSYSROOT=%s\nBUILD_DIR=%s\nJOBS=%s\n' \
		"$ARCH" "$TARGET" "$LLVM_MODE" "$PREFIX" "$SYSROOT" "$BUILD_DIR" "$JOBS"
	exit ;;
doctor) doctor; exit ;;
clean)
	[ ! -d "$BUILD_DIR/lock" ] || die "build is running: $BUILD_DIR/lock"
	[ -f "$PREFIX/.musllvm-config" ] || [ ! -e "$PREFIX" ] || die "refusing to remove an unmarked PREFIX: $PREFIX"
	[ -f "$BUILD_DIR/config" ] || [ ! -e "$BUILD_DIR" ] || die "refusing to remove an unmarked BUILD_DIR: $BUILD_DIR"
	rm -rf "$PREFIX" "$BUILD_DIR"
	exit ;;
all|headers|builtins|musl|atomic|runtimes|toolchain|configure-llvm) ;;
*) die "unknown build stage: $stage" ;;
esac

doctor
unset CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH OBJC_INCLUDE_PATH LIBRARY_PATH
unset GCC_EXEC_PREFIX COMPILER_PATH CFLAGS CXXFLAGS CPPFLAGS LDFLAGS
BOOTSTRAP_CC=$(absolute_path "$(command -v "$HOST_CC")")
BOOTSTRAP_CXX=$(absolute_path "$(command -v "$HOST_CXX")")
sh "$PROOT/scripts/check.sh" pull
extract_source llvm
LLVM_SOURCE=$source_path
extract_source musl
MUSL_SOURCE=$source_path
extract_source linux
LINUX_SOURCE=$source_path
extract_source atomic
ATOMIC_SOURCE=$source_path

config_digest=$({
	printf '%s\n' "$ARCH" "$TARGET" "$LLVM_MODE" "$PREFIX" "$BUILD_DIR" \
		"$BOOTSTRAP_CC" "$BOOTSTRAP_CXX" "$TARGET_CFLAGS" "$HOST_CFLAGS" "$HOST_CXXFLAGS" "$HOST_LDFLAGS"
	"$BOOTSTRAP_CC" --version
	"$BOOTSTRAP_CXX" --version
	cat "$SOURCES_FILE"
	cat "$PROOT/scripts/build.sh" "$PROOT/scripts/config.sh"
	for source_patch in "$PROOT"/patches/*/*.patch; do
		[ -f "$source_patch" ] || continue
		printf '%s\n' "${source_patch#"$PROOT/"}"
		cat "$source_patch"
	done
	if [ "$LLVM_MODE" = system ]; then
		for program in $TOOLS llvm-config; do command -v "$program"; done
		ld.lld --version
		llvm-ar --version
	fi
} | sha256sum)
config_digest=${config_digest%% *}
for config_file in "$PREFIX/.musllvm-config" "$BUILD_DIR/config"; do
	if [ -f "$config_file" ]; then
		[ "$(cat "$config_file")" = "$config_digest" ] ||
			die "configuration changed; run make clean with the same ARCH, PREFIX and BUILD_DIR before rebuilding"
	fi
done
for directory in "$PREFIX" "$BUILD_DIR"; do
	if [ -d "$directory" ] && [ ! -f "$directory/.musllvm-config" ] && [ ! -f "$directory/config" ]; then
		[ -z "$(ls -A "$directory")" ] || die "refusing to use an unmarked nonempty directory: $directory"
	fi
done
mkdir -p "$PREFIX" "$BUILD_DIR/stamps"
mkdir "$BUILD_DIR/lock" 2>/dev/null || die "build is running: $BUILD_DIR/lock"
trap 'rmdir "$BUILD_DIR/lock"' 0
trap 'exit 1' HUP INT TERM
printf '%s\n' "$config_digest" > "$PREFIX/.musllvm-config"
printf '%s\n' "$config_digest" > "$BUILD_DIR/config"
if [ "$stage" = configure-llvm ]; then configure_llvm; exit; fi
toolchain
if [ "$stage" = toolchain ]; then exit; fi
headers
if [ "$stage" = headers ]; then exit; fi
builtins
if [ "$stage" = builtins ]; then exit; fi
musl
if [ "$stage" = musl ]; then exit; fi
atomic
if [ "$stage" = atomic ]; then exit; fi
runtimes
wrappers
if [ "$stage" = all ]; then sh "$PROOT/scripts/verify.sh"; fi
