#!/bin/sh
set -eu

. $PWD/scripts/config.sh

while IFS= read -r url; do \
[ -z "$url" ] && continue; \
fname="$(printf '%s' "$url" | sed -E 's/[?#].*$//' | sed -E 's!.*/!!')"; \
if [ -e "$PROOT/sources/$fname" ]; then \
	printf "SKIP: %s (already exists)\n" "$fname"; \
else \
	printf "GET: %s -> %s\n" "$url" "$fname"; \
	curl -f -L -O -S --output-dir "$PROOT/sources/" "$url" || { printf "ERROR: failed to download %s\n" "$url"; exit 1; }; \
fi; \
done < "$SOURCES_FILE"; \
