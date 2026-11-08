#!/usr/bin/env bash
# One command for the demo: build the messy PATH, then ask Hermes about it.
#
#   bash demo/run-demo.sh
#
# Everything happens on this machine. No network, no API key beyond the one
# Hermes already uses, nothing written outside $DEMO_ROOT (~/which-copy-demo).
#
# One thing to expect on camera: the sandbox copies are not on Hermes's own PATH.
# Hermes builds its PATH when it starts, so copies in a PATH *pasted into the
# chat* are described and ordered but not executed. That is the security property
# the report is making, and its "Not run" line says so.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

# shellcheck source=demo/guard.sh
. "$HERE/guard.sh"

# Resolved once, with the same guard setup.sh and cleanup.sh use, so the paths
# printed below are the paths that were actually built.
DEMO_ROOT="$(demo_root_or_die "${DEMO_ROOT:-$HOME/which-copy-demo}" "$REPO")"

DEMO_ROOT="$DEMO_ROOT" bash "$HERE/setup.sh" >/dev/null

# The sandbox part of the PATH, kept as a string so the question can name it.
SANDBOX_PATH="$DEMO_ROOT/bin-2021:$DEMO_ROOT/bin-2025:$DEMO_ROOT/bin-broken"
FULL_PATH="$SANDBOX_PATH:/usr/local/bin:/usr/bin:/bin"

echo "The sandbox PATH, in order:"
echo "  1. $DEMO_ROOT/bin-2021      (python3 3.9.2, claude 0.9.1)"
echo "  2. $DEMO_ROOT/bin-2025      (python3 3.13.1, claude 2.0.4)"
echo "  3. $DEMO_ROOT/bin-broken    (pip3, a broken symlink)"
echo
echo "In a shell that puts that PATH first, python3 is:"
echo "  $(PATH="$SANDBOX_PATH:$PATH" command -v python3)  →  $(PATH="$SANDBOX_PATH:$PATH" python3 --version 2>&1)"
echo "  (the 3.13.1 sitting right behind it is never reached)"
echo
echo "Hermes keeps its own PATH, built when it started, so ask it both questions:"
echo "  1. which python3 will you use?                 → Hermes's own answer"
echo "  2. which copy wins in the sandbox PATH below?  → read, not run"
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
