#!/bin/sh
set -eu
root=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
for script in "$root"/scripts/*.sh "$root"/files/toolchain/*.sh; do
	sh -n "$script"
done
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$root/tests" -p 'test_*.py'
