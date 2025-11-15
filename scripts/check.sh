#!/bin/sh
set -eu

SOURCES_FILE=./sources.list

while IFS= read -r url; do \
[ -z "$url" ] && continue; \
fname="$(printf '%s' "$url" | sed -E 's/[?#].*$//' | sed -E 's!.*/!!')"; \
if [ -e "./sources/$fname" ]; then \
	printf "SKIP: %s (already exists)\n" "$fname"; \
else \
	printf "GET: %s -> %s\n" "$url" "$fname"; \
	curl -o "./sources/$fname" "$url" || { printf "ERROR: failed to download %s\n" "$url"; exit 1; }; \
fi; \
done < "$SOURCES_FILE"; \
