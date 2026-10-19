#!/bin/sh

die()
{
	printf 'musllvm: %s\n' "$*" >&2
	exit 1
}

need()
{
	command -v "$1" >/dev/null 2>&1 || die "required program not found: $1"
}

absolute_path()
{
	case "$1" in
	/*) printf '%s\n' "$1" ;;
	*) printf '%s/%s\n' "$PROOT" "$1" ;;
	esac
}

validate_directory()
{
	case "$1" in
	*[!a-zA-Z0-9_./-]*) die "build paths must use letters, digits, slashes, dots, underscores or hyphens: $1" ;;
	esac
	case "$1" in
	/|/usr|/usr/local|/bin|/lib|/lib64|/etc|/home|/tmp|"$PROOT")
		die "choose a dedicated directory, not $1" ;;
	*/../*|*/..|*/./*|*/.|*/)
		die "directory must have no dot components or trailing slash: $1" ;;
	esac
}

source_info()
{
	source_line=$(awk -v component="$1" '$1 == component { print; count++ } END { if (count != 1) exit 1 }' "$SOURCES_FILE") ||
		die "expected one $1 entry in $SOURCES_FILE"
	read -r component archive digest url extra <<EOF
$source_line
EOF
	case "$archive" in
	*[!a-zA-Z0-9._-]*|'') die "invalid archive name: $archive" ;;
	esac
	case "$digest" in
	*[!a-f0-9]*|'') die "invalid SHA-256 for $archive" ;;
	esac
	[ "${#digest}" -eq 64 ] && [ -z "$extra" ] || die "invalid source entry for $component"
	case "$url" in
	https://*) ;;
	*) die "source URL must use HTTPS: $url" ;;
	esac
	source_name=${archive%.tar.*}
}

archive_ok()
{
	[ -f "$SOURCES_DIR/$archive" ] || return 1
	actual_digest=$(sha256sum "$SOURCES_DIR/$archive") || return 1
	[ "${actual_digest%% *}" = "$digest" ]
}

extract_source()
{
	source_info "$1"
	archive_ok || die "missing or corrupt $archive; run make pull"
	set -- "$PROOT/patches/$component/"*.patch
	source_digest=$digest
	if [ -f "$1" ]; then
		need patch
		source_digest=$({
			printf '%s\n' "$digest"
			for source_patch do
				printf '%s\n' "${source_patch##*/}"
				cat "$source_patch"
			done
		} | sha256sum)
		source_digest=${source_digest%% *}
	fi
	source_path="$PROOT/build/src/$source_name"
	if [ -f "$source_path/.musllvm-source" ]; then
		[ "$(cat "$source_path/.musllvm-source")" = "$source_digest" ] ||
			die "source or patches changed; remove $source_path and clean the affected toolchain before rebuilding"
		return
	fi
	[ ! -e "$source_path" ] || die "incomplete source directory: $source_path"
	mkdir -p "$PROOT/build/src"
	source_lock="$source_path.lock"
	(
		mkdir "$source_lock" 2>/dev/null || die "source is being extracted: $source_name"
		trap 'rm -rf "$source_lock"' 0
		trap 'exit 1' HUP INT TERM
		source_tmp="$source_lock/tree"
		mkdir "$source_tmp"
		printf 'Extracting %s\n' "$archive"
		tar -xf "$SOURCES_DIR/$archive" --strip-components=1 -C "$source_tmp" || die "could not extract $archive"
		for source_patch do
			[ -f "$source_patch" ] || continue
			printf 'Applying %s\n' "${source_patch##*/}"
			patch --batch --forward --fuzz=0 -p1 -d "$source_tmp" < "$source_patch" ||
				die "could not apply $source_patch"
		done
		printf '%s\n' "$source_digest" > "$source_tmp/.musllvm-source"
		mv "$source_tmp" "$source_path"
	)
}

PROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
ARCH=${ARCH:-x86_64}
TARGET=${TARGET:-$ARCH-linux-musl}
case "$ARCH" in
x86_64) KERNEL_ARCH=x86; ELF_MACHINE='Advanced Micro Devices X86-64' ;;
aarch64) KERNEL_ARCH=arm64; ELF_MACHINE='AArch64' ;;
*) die "unsupported ARCH=$ARCH; choose x86_64 or aarch64" ;;
esac
case "$TARGET" in
"$ARCH-linux-musl"|"$ARCH-unknown-linux-musl") ;;
*) die "TARGET=$TARGET does not match ARCH=$ARCH and the musl ABI" ;;
esac
LLVM_MODE=${LLVM_MODE:-system}
case "$LLVM_MODE" in
system|source) ;;
*) die "LLVM_MODE must be system or source" ;;
esac
JOBS=${JOBS:-2}
LINK_JOBS=${LINK_JOBS:-1}
for jobs in "$JOBS" "$LINK_JOBS"; do
	case "$jobs" in
	*[!0-9]*|'') die "JOBS and LINK_JOBS must be positive integers" ;;
	esac
	[ "$jobs" -gt 0 ] 2>/dev/null || die "JOBS and LINK_JOBS must be positive integers"
done
PREFIX=$(absolute_path "${PREFIX:-build/$TARGET}")
BUILD_DIR=$(absolute_path "${BUILD_DIR:-build/work/$TARGET}")
SOURCES_DIR=$(absolute_path "${SOURCES_DIR:-sources}")
SOURCES_FILE=$(absolute_path "${SOURCES_FILE:-sources.list}")
validate_directory "$PREFIX"
validate_directory "$BUILD_DIR"
validate_directory "$SOURCES_DIR"
case "$PROOT" in
*[!a-zA-Z0-9_./-]*) die "move the checkout to a path without whitespace or shell metacharacters" ;;
esac
case "$PREFIX/" in
"$BUILD_DIR/"*) die "PREFIX must be separate from BUILD_DIR" ;;
esac
case "$BUILD_DIR/" in
"$PREFIX/"*) die "BUILD_DIR must be separate from PREFIX" ;;
esac
SYSROOT="$PREFIX/sysroot"
HOST_CC=${HOST_CC:-clang}
HOST_CXX=${HOST_CXX:-clang++}
TARGET_CFLAGS=${TARGET_CFLAGS:--O2}
HOST_CFLAGS=${HOST_CFLAGS:-}
HOST_CXXFLAGS=${HOST_CXXFLAGS:-}
HOST_LDFLAGS=${HOST_LDFLAGS:-}
RUNNER=${RUNNER:-}
export PROOT ARCH TARGET PREFIX BUILD_DIR SOURCES_DIR SOURCES_FILE LLVM_MODE JOBS LINK_JOBS
export HOST_CC HOST_CXX TARGET_CFLAGS HOST_CFLAGS HOST_CXXFLAGS HOST_LDFLAGS RUNNER
