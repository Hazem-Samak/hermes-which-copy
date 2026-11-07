#!/usr/bin/env bash
# Shared guard for the demo scripts: decide which directory the demo may use,
# and refuse to delete anything that is not obviously it.
#
# setup.sh and cleanup.sh both delete DEMO_ROOT. A typo in that variable
# (`DEMO_ROOT=$HOME`, `DEMO_ROOT=/`, `DEMO_ROOT=$PWD`) must not turn a demo into
# a data-loss incident, so every rule is checked before anything is removed:
#
#   * an absolute path, not "/", not the home directory
#   * not the repository, and not a parent of it
#   * if it already exists, it is empty — or it carries this demo's marker, or
#     it already has the demo layout (bin-2021 / bin-2025)
#
# setup.sh writes the marker as soon as the directory is its own.

WHICH_COPY_DEMO_MARKER=".which-copy-demo"

# demo_root_or_die <requested-path> <repo-dir>
# Prints the resolved demo path on success; prints why and returns 1 on refusal.
demo_root_or_die() {
  local root="${1:-}"
  local repo="${2:-$PWD}"
  local parent base home_resolved

  if [ -z "$root" ]; then
    echo "Refusing to work in an empty demo path." >&2
    return 1
  fi
  case "$root" in
    /*) ;;
    *)
      echo "Refusing to use '$root': the demo path must be absolute." >&2
      return 1
      ;;
  esac

  # Strip trailing slashes so "$HOME/" and "$HOME" compare equal.
  while [ "${root%/}" != "$root" ] && [ "$root" != "/" ]; do
    root="${root%/}"
  done

  base="$(basename -- "$root")"
  parent="$(dirname -- "$root")"
  if [ "$base" = "." ] || [ "$base" = ".." ]; then
    echo "Refusing to use '$root': it does not name a directory of its own." >&2
    return 1
  fi
  if [ ! -d "$parent" ]; then
    echo "Refusing to use '$root': its parent directory does not exist." >&2
    return 1
  fi

  # Resolve symlinks and ".." in the parent, so /tmp/x/../.. cannot slip past.
  parent="$(cd -- "$parent" && pwd -P)"
  if [ -d "$root" ]; then
    root="$(cd -- "$root" && pwd -P)"
  else
    root="$parent/$base"
  fi
  home_resolved="$(cd -- "$HOME" 2>/dev/null && pwd -P || printf '%s' "$HOME")"
  repo="$(cd -- "$repo" 2>/dev/null && pwd -P || printf '%s' "$repo")"

  if [ "$root" = "/" ] || [ "$root" = "$parent" ]; then
    echo "Refusing to use '$root' as the demo directory." >&2
    return 1
  fi
  if [ "$root" = "$home_resolved" ]; then
    echo "Refusing to use '$root': that is your home directory." >&2
    return 1
  fi
  case "$repo/" in
    "$root"/*)
      echo "Refusing to use '$root': this repository lives inside it." >&2
      return 1
      ;;
  esac
  if [ -e "$root" ] && [ ! -d "$root" ]; then
    echo "Refusing to use '$root': it exists and is not a directory." >&2
    return 1
  fi

  if [ -d "$root" ] && [ -n "$(ls -A -- "$root" 2>/dev/null)" ]; then
    if [ ! -f "$root/$WHICH_COPY_DEMO_MARKER" ] \
      && [ ! -d "$root/bin-2021" ] && [ ! -d "$root/bin-2025" ]; then
      echo "Refusing to delete '$root': it is not empty and it does not look like the demo" >&2
      echo "(no $WHICH_COPY_DEMO_MARKER marker, no bin-2021/bin-2025 directories)." >&2
      echo "Point DEMO_ROOT at a new directory if you want the demo somewhere else." >&2
      return 1
    fi
  fi

  printf '%s\n' "$root"
}
