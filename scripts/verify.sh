#!/bin/sh
set -eu

. "$(dirname "$0")/config.sh"
MUSLLVM_SYSROOT=$SYSROOT
export MUSLLVM_SYSROOT
cc="$PREFIX/bin/$TARGET-cc"
cxx="$PREFIX/bin/$TARGET-c++"
readelf="$PREFIX/bin/$TARGET-readelf"
work="$BUILD_DIR/verify"
loader="$SYSROOT/lib/ld-musl-$ARCH.so.1"
for program in "$cc" "$cxx" "$readelf"; do
	[ -x "$program" ] || die "toolchain is incomplete: $program"
done
mkdir -p "$work"
"$cc" -std=c99 -O2 -pthread "$PROOT/tests/hello.c" -o "$work/hello-c"
"$cc" -std=c99 -O2 -pthread -static "$PROOT/tests/hello.c" -o "$work/hello-c-static"
"$cxx" -std=c++20 -O2 -pthread "$PROOT/tests/hello.cpp" -o "$work/hello-cxx"
"$cxx" -std=c++20 -O2 -pthread -static "$PROOT/tests/hello.cpp" -o "$work/hello-cxx-static"

for program in hello-c hello-c-static hello-cxx hello-cxx-static; do
	"$readelf" -h "$work/$program" > "$work/$program.header"
	grep -F "$ELF_MACHINE" "$work/$program.header" >/dev/null || die "wrong ELF machine: $program"
	"$readelf" -l "$work/$program" > "$work/$program.segments"
	"$readelf" -d "$work/$program" > "$work/$program.dynamic"
	if grep -E 'libc\.so\.6|libstdc\+\+|libgcc_s|ld-linux' "$work/$program.dynamic" "$work/$program.segments"; then
		die "host runtime dependency in $program"
	fi
	case "$program" in
	*-static)
		if grep -E 'INTERP|NEEDED' "$work/$program.segments" "$work/$program.dynamic"; then
			die "static executable has dynamic dependencies: $program"
		fi ;;
	*)
		grep -F "/lib/ld-musl-$ARCH.so.1" "$work/$program.segments" >/dev/null ||
			die "wrong dynamic loader in $program" ;;
	esac
done

for language in c c++; do
	compiler=$cc
	[ "$language" = c ] || compiler=$cxx
	CPATH=/usr/include CPLUS_INCLUDE_PATH=/usr/include LIBRARY_PATH=/usr/lib \
		"$compiler" -E -v -x "$language" /dev/null > /dev/null 2> "$work/$language.includes"
	if grep -E '^ /usr/(local/)?include([ /]|$)|^ /usr/.*/c\+\+' "$work/$language.includes"; then
		die "host headers found in $language search path"
	fi
done

cmake -S "$PROOT/tests/cmake" -B "$work/cmake" -G Ninja \
	-DCMAKE_TOOLCHAIN_FILE="$PREFIX/share/musllvm/toolchain.cmake"
cmake --build "$work/cmake" --parallel "$JOBS"

host_arch=$(uname -m)
if [ "$host_arch" = "$ARCH" ] || [ -n "$RUNNER" ]; then
	for program in hello-c-static hello-cxx-static; do
		if [ -n "$RUNNER" ]; then "$RUNNER" "$work/$program"; else "$work/$program"; fi
	done
	for program in hello-c hello-cxx; do
		if [ -n "$RUNNER" ]; then
			"$RUNNER" "$loader" --library-path "$SYSROOT/usr/lib:$SYSROOT/lib" "$work/$program"
		else
			"$loader" --library-path "$SYSROOT/usr/lib:$SYSROOT/lib" "$work/$program"
		fi
	done
else
	printf 'Execution skipped for %s on %s; set RUNNER=qemu-%s to run the programs.\n' "$ARCH" "$host_arch" "$ARCH"
fi
printf 'Verified %s: static/dynamic C and C++, target ELF, isolated headers, and CMake\n' "$TARGET"
