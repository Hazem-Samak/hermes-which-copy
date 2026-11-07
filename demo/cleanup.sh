#!/usr/bin/env bash
# Remove the demo environment. Nothing outside $DEMO_ROOT is touched.
set -euo pipefail

DEMO_ROOT="${DEMO_ROOT:-$HOME/which-copy-demo}"

case "$DEMO_ROOT" in
  ""|"/"|"$HOME")
    echo "Refusing to remove '$DEMO_ROOT'." >&2
    exit 1
    ;;
esac

if [ -d "$DEMO_ROOT" ]; then
  rm -rf "$DEMO_ROOT"
  echo "Removed $DEMO_ROOT"
else
  echo "Nothing to remove at $DEMO_ROOT"
fi
