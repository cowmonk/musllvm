#!/bin/sh
set -eu

. "$(dirname "$0")/config.sh"

[ "$LLVM_MODE" = source ] || die "publishing requires LLVM_MODE=source"
[ -f "$BUILD_DIR/stamps/runtimes" ] || die "target runtimes have not finished building"
need python3
python3 "$PROOT/scripts/package.py" --prefix "$PREFIX" --target "$TARGET" \
	--sources "$SOURCES_FILE" --output "${DIST_DIR:-$PROOT/build/releases}"
