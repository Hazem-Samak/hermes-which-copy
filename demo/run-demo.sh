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

# The sandbox part of the PATH, kept as a string so the question can name it.
SANDBOX_PATH="$DEMO_ROOT/bin-2021:$DEMO_ROOT/bin-2025:$DEMO_ROOT/bin-broken"
FULL_PATH="$SANDBOX_PATH:/usr/local/bin:/usr/bin:/bin"

export PATH="$SANDBOX_PATH:$PATH"

echo "PATH now starts with:"
echo "  1. $DEMO_ROOT/bin-2021      (python3 3.9.2, claude 0.9.1)"
echo "  2. $DEMO_ROOT/bin-2025      (python3 3.13.1, claude 2.0.4)"
echo "  3. $DEMO_ROOT/bin-broken    (pip3, a broken symlink)"
echo
echo "A normal terminal now resolves python3 to:"
echo "  $(command -v python3)  →  $(python3 --version 2>&1)"
echo

if ! command -v hermes >/dev/null 2>&1; then
  echo "hermes is not on PATH; run demo/setup.sh and use the PATH it prints." >&2
  exit 1
fi

QUERY="Which python3 will you use? Then check the same name against this messy PATH and tell me which copy wins in it: ${FULL_PATH}"

echo "Asking Hermes:"
echo "  $QUERY"
echo

exec hermes chat -q "$QUERY"
