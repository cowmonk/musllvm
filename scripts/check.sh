#!/bin/sh
set -eu

source ./scripts/config.sh

while IFS= read -r url; do \
[ -z "$url" ] && continue; \
fname="$(printf '%s' "$url" | sed -E 's/[?#].*$//' | sed -E 's!.*/!!')"; \
if [ -e "./sources/$fname" ]; then \
	printf "SKIP: %s (already exists)\n" "$fname"; \
else \
	printf "GET: %s -> %s\n" "$url" "$fname"; \
	curl -f -L -O -S --output-dir "./sources/" "$url" || { printf "ERROR: failed to download %s\n" "$url"; exit 1; }; \
fi; \
done < "$SOURCES_FILE"; \
