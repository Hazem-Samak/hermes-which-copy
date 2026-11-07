#!/usr/bin/env bash
# Remove the demo environment. Nothing outside $DEMO_ROOT is touched.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

# shellcheck source=demo/guard.sh
. "$HERE/guard.sh"

# Same rules as setup.sh: "/", the home directory, the repository, and any
# existing directory that is not this demo are refused, not deleted.
DEMO_ROOT="$(demo_root_or_die "${DEMO_ROOT:-$HOME/which-copy-demo}" "$REPO")"

if [ -d "$DEMO_ROOT" ]; then
  rm -rf -- "$DEMO_ROOT"
  echo "Removed $DEMO_ROOT"
else
  echo "Nothing to remove at $DEMO_ROOT"
fi
