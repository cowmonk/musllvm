#/bin/sh

while IFS= read -r url; do \
[ -z "$url" ] && continue; \
fname="$(printf '%s' "$url" | sed -E 's/[?#].*$//' | sed -E 's!.*/!!')"; \
if [ -e "$(OUTDIR)/$fname" ]; then \
	printf "SKIP: %s (already exists)\n" "$fname"; \
else \
	printf "GET: %s -> %s\n" "$url" "$fname"; \
	curl -o "./sources/$fname" "$url" || { printf "ERROR: failed to download %s\n" "$url"; exit 1; }; \
fi; \
done < ${SOURCES_FILE}; \
