#!/bin/sh
set -eu

. "$(dirname "$0")/config.sh"
need sha256sum
[ -f "$SOURCES_FILE" ] || die "source manifest not found: $SOURCES_FILE"
case "${1:-pull}" in
pull) need curl; mkdir -p "$SOURCES_DIR" ;;
verify) ;;
*) die "usage: check.sh [pull|verify]" ;;
esac

for name in musl linux llvm atomic; do
	source_info "$name"
	if archive_ok; then
		printf 'OK %s\n' "$archive"
		continue
	fi
	[ "${1:-pull}" = pull ] || die "missing or corrupt archive: $archive"
	printf 'Downloading %s\n' "$archive"
	part="$SOURCES_DIR/$archive.part.$$"
	trap 'rm -f "$part"' 0
	trap 'exit 1' HUP INT TERM
	curl --fail --location --show-error --retry 3 --connect-timeout 20 \
		--output "$part" "$url"
	actual_digest=$(sha256sum "$part")
	[ "${actual_digest%% *}" = "$digest" ] || die "SHA-256 mismatch for $archive"
	mv "$part" "$SOURCES_DIR/$archive"
	trap - 0 HUP INT TERM
done
