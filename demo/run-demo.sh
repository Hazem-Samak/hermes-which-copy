#!/usr/bin/env bash
# One command for the demo: build the messy PATH, then ask Hermes the question.
#
#   bash demo/run-demo.sh
#
# Everything happens on this machine. No network, no API key beyond the one
# Hermes already uses, nothing written outside $DEMO_ROOT (~/which-copy-demo).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEMO_ROOT="${DEMO_ROOT:-$HOME/which-copy-demo}"

DEMO_ROOT="$DEMO_ROOT" bash "$HERE/setup.sh" >/dev/null

export PATH="$DEMO_ROOT/bin-2021:$DEMO_ROOT/bin-2025:$DEMO_ROOT/bin-broken:$PATH"

echo "PATH now starts with:"
echo "  1. $DEMO_ROOT/bin-2021      (python3 3.9.2, claude 0.9.1)"
echo "  2. $DEMO_ROOT/bin-2025      (python3 3.13.1, claude 2.0.4)"
echo "  3. $DEMO_ROOT/bin-broken    (pip3, a broken symlink)"
echo

if ! command -v hermes >/dev/null 2>&1; then
  echo "hermes is not on PATH; run demo/setup.sh and use the PATH it prints." >&2
  exit 1
fi

exec hermes chat -q 'Which python3 will you use? And which claude? Use which_copy and show me the report.'
