#!/usr/bin/env bash
# Build a deliberately messy PATH for the demo.
#
# Three copies of python3, oldest first, so the third one — the real one — never
# runs. Plus two copies of claude and a broken symlink named pip3 sitting in
# front of everything.
#
# The stubs are honest fakes: they answer --version like the copy they stand in
# for and hand every other argument to the real interpreter, so a demo PATH can
# never break a shell that happens to use it.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

# shellcheck source=demo/guard.sh
. "$HERE/guard.sh"

# The guard refuses "/", the home directory, the repository, and any existing
# non-empty directory that is not this demo, and prints the resolved path.
DEMO_ROOT="$(demo_root_or_die "${DEMO_ROOT:-$HOME/which-copy-demo}" "$REPO")"

rm -rf -- "$DEMO_ROOT"
mkdir -p -- "$DEMO_ROOT/bin-2021" "$DEMO_ROOT/bin-2025" "$DEMO_ROOT/bin-broken"
: > "$DEMO_ROOT/$WHICH_COPY_DEMO_MARKER"

REAL_PYTHON="$(command -v python3 || true)"
if [ -z "$REAL_PYTHON" ]; then
  echo "This demo needs a real python3 on PATH to delegate to." >&2
  exit 1
fi

# write_stub <path> <version-string> <real-binary> <tool-name>
write_stub() {
  local path="$1" version="$2" real="$3" name="$4"
  cat > "$path" <<EOF
#!/bin/sh
# Demo stub standing in for $name. It lies about --version only.
case "\$1" in
  --version|-V) echo "$name $version"; exit 0 ;;
esac
exec "$real" "\$@"
EOF
  chmod +x "$path"
}

write_stub "$DEMO_ROOT/bin-2021/python3" "3.9.2" "$REAL_PYTHON" "Python"
write_stub "$DEMO_ROOT/bin-2025/python3" "3.13.1" "$REAL_PYTHON" "Python"

# claude is not managed by Hermes, so this pair demonstrates the plain
# duplicates case: an old copy first, a new one behind it.
CLAUDE_REAL="$(command -v claude || echo /usr/bin/true)"
write_stub "$DEMO_ROOT/bin-2021/claude" "0.9.1 (Claude Code)" "$CLAUDE_REAL" "claude"
write_stub "$DEMO_ROOT/bin-2025/claude" "2.0.4 (Claude Code)" "$CLAUDE_REAL" "claude"

# An entry that exists but cannot run: PATH still lists it, the shell skips it.
ln -s "$DEMO_ROOT/nowhere/pip3" "$DEMO_ROOT/bin-broken/pip3"

cat <<EOF
Demo environment ready in $DEMO_ROOT

  bin-2021/python3    says Python 3.9.2   (the old copy, first in PATH)
  bin-2025/python3    says Python 3.13.1  (the new copy, second)
  bin-broken/pip3     a broken symlink    (listed in PATH, runs nothing)
  claude              0.9.1 in bin-2021, 2.0.4 in bin-2025

To see the ordering in a shell, put the sandbox first:

  export PATH="$DEMO_ROOT/bin-2021:$DEMO_ROOT/bin-2025:$DEMO_ROOT/bin-broken:\$PATH"

Hermes keeps its own PATH — it is built when Hermes starts — so a sandbox PATH
you paste into the chat is read, ordered and reported. Nothing that exists only
in it is run: a copy is probed only when one of the machine's own PATHs or a
known install directory already has it. Ask it anyway; the report says which
copies it left alone and why:

  hermes chat -q "which python3 will you use?"

  hermes chat -q "which copy wins in this PATH: $DEMO_ROOT/bin-2021:$DEMO_ROOT/bin-2025:$DEMO_ROOT/bin-broken:/usr/local/bin:/usr/bin:/bin"
EOF
