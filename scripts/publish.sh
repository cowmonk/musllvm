#!/bin/sh
set -eu

root=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
: "${GITHUB_SHA:?GITHUB_SHA must identify the build commit}"
[ "$(git -C "$root" rev-parse HEAD)" = "$GITHUB_SHA" ] || {
	printf '%s\n' 'checkout does not match the build commit' >&2
	exit 1
}
date=$(git -C "$root" show -s --format=%cs "$GITHUB_SHA")
short=$(printf '%.12s' "$GITHUB_SHA")
tag="musllvm-$date-$short"

cd "${1:-$root/build/releases}"
set -- musllvm-x86_64-linux-musl-host-x86_64-linux.tar.xz \
	musllvm-aarch64-linux-musl-host-x86_64-linux.tar.xz
: > SHA256SUMS
for archive do
	[ -s "$archive" ] && [ -s "$archive.sha256" ] || {
		printf 'missing release archive or checksum: %s\n' "$archive" >&2
		exit 1
	}
	read -r digest filename extra < "$archive.sha256"
	[ "$filename" = "$archive" ] && [ -z "$extra" ] || {
		printf 'checksum does not name its release archive: %s\n' "$archive" >&2
		exit 1
	}
	cat "$archive.sha256" >> SHA256SUMS
done
sha256sum -c SHA256SUMS
cp "$root/sources.list" sources.list
{
	printf 'CI built these musllvm toolchains from commit %s.\n\n' "$GITHUB_SHA"
	printf '%s\n' 'The tools run on x86_64 Linux with glibc 2.39 or newer.' \
		'They target x86_64-linux-musl and aarch64-linux-musl.' \
		'The archives include Clang, LLD and LLVM utilities.' '' 'core sources' '------------' ''
	awk 'NF && $1 !~ /^#/ { printf "    %s  %s\n", $1, $2 }' sources.list
	printf '\n%s\n' 'Verify downloads with sha256sum --ignore-missing -c SHA256SUMS.'
} > notes.md

if draft=$(gh release view "$tag" --json isDraft --jq .isDraft 2> view.err); then
	if [ "$draft" = false ]; then
		printf 'release already published: %s\n' "$tag"
		exit
	fi
	gh release upload "$tag" "$@" SHA256SUMS sources.list --clobber
elif grep -F 'release not found' view.err >/dev/null; then
	gh release create "$tag" "$@" SHA256SUMS sources.list --draft \
		--target "$GITHUB_SHA" --title "musllvm $date" --notes-file notes.md
else
	cat view.err >&2
	exit 1
fi
gh release edit "$tag" --notes-file notes.md --draft=false --latest
