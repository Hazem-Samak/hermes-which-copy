"""PATH resolution for Which Copy — where the copies come from, and which is live.

Two things this module refuses to do:

* It never treats "there is only one PATH" as true. There are at least three
  that matter: the PATH of the process running Hermes (``os.environ``, what a
  subprocess spawned with that environment gets), the PATH Hermes's terminal
  tool builds for a command (a login shell plus the directories Hermes adds),
  and the PATH a plain terminal gets from the user's own startup files. This
  module reads the first and the third exactly, and says in the report that the
  second can differ instead of pretending to have measured it.
* It never guesses about a file. A candidate is inspected with ``lstat`` (to see
  the link itself) and ``stat`` (to see what it points at), so a broken symlink
  is reported as broken instead of being skipped or counted as installed.

Everything here is read-only: no file is created, changed, or removed.
"""

from __future__ import annotations

import errno
import glob as _glob
import os
import pwd
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, Sequence

# --------------------------------------------------------------------------- #
# Constants

HERMES_SOURCE = "hermes"
LOGIN_SHELL_SOURCE = "login-shell"
CUSTOM_SOURCE = "custom"

LOGIN_SHELL_TIMEOUT = 3.0
LOGIN_SHELL_BEGIN = "__WHICHCOPY_ENV_BEGIN__"
LOGIN_SHELL_END = "__WHICHCOPY_ENV_END__"

#: The PATH a freshly launched terminal starts from on macOS (and most Linux
#: desktops): the system default from launchd / login(1), not Hermes's PATH.
#: The login-shell probe is seeded with exactly this, so every entry the shell
#: reports beyond it comes from the user's own startup files rather than from
#: Hermes's environment leaking in.
SYSTEM_DEFAULT_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

#: How many entries of a PATH are shown before the report says "and N more".
PATH_PREVIEW = 8

#: Hard ceiling on extra (off-PATH) search roots, so a pathological home
#: directory cannot turn one tool check into a filesystem crawl.
MAX_EXTRA_ROOTS = 80
MAX_GLOB_ROOTS = 8

#: Hermes profile install paths embed two content hashes. They identify nothing a
#: reader can use, so display collapses them.
_INSTALL_HASH_RE = re.compile(r"(installs)/[^/]+(?:/environments/[^/]+)?/venv/")

# Live kinds — a candidate the shell could actually execute.
KIND_EXECUTABLE = "executable"
KIND_EXECUTABLE_SYMLINK = "executable_symlink"
KIND_BROKEN_SYMLINK = "broken_symlink"
KIND_SYMLINK_LOOP = "symlink_loop"
KIND_SYMLINK_UNREADABLE = "symlink_target_unavailable"
KIND_NOT_EXECUTABLE = "not_executable"
KIND_SYMLINK_NOT_EXECUTABLE = "symlink_to_not_executable"
KIND_DIRECTORY = "directory"
KIND_SYMLINK_DIRECTORY = "symlink_to_directory"
KIND_NON_REGULAR = "non_regular"

LIVE_KINDS = frozenset({KIND_EXECUTABLE, KIND_EXECUTABLE_SYMLINK})

KIND_LABELS = {
    KIND_EXECUTABLE: "executable file",
    KIND_EXECUTABLE_SYMLINK: "executable symlink",
    KIND_BROKEN_SYMLINK: "broken symlink (its target does not exist)",
    KIND_SYMLINK_LOOP: "symlink loop (it points back at itself)",
    KIND_SYMLINK_UNREADABLE: "symlink whose target cannot be read",
    KIND_NOT_EXECUTABLE: "file without execute permission",
    KIND_SYMLINK_NOT_EXECUTABLE: "symlink to a file without execute permission",
    KIND_DIRECTORY: "directory, not a program",
    KIND_SYMLINK_DIRECTORY: "symlink to a directory",
    KIND_NON_REGULAR: "special file, not a program",
}


class InvalidToolName(ValueError):
    """The requested name cannot be looked up (empty, too long, control chars)."""


# --------------------------------------------------------------------------- #
# Path sources


@dataclass(frozen=True)
class PathSource:
    """One ordered PATH, with where it came from and whether it is trustworthy."""

    kind: str
    label: str
    entries: tuple[str, ...]
    available: bool = True
    degraded: bool = False
    note: str = ""
    raw: str = ""
    #: For a login shell: the PATH the shell was started with, before its own
    #: startup files ran. It is the system default, never Hermes's PATH.
    seeded: str = ""

    def as_dict(self, home: str = "") -> dict:
        payload = {
            "kind": self.kind,
            "label": self.label,
            "available": self.available,
            "degraded": self.degraded,
            "note": self.note,
            "entry_count": len(self.entries),
            "entries": [_tidy(p, home) for p in self.entries[:64]],
        }
        if self.seeded:
            payload["seeded_path"] = self.seeded
        return payload


def split_path(raw: str | None) -> tuple[str, ...]:
    """Split a PATH string, keeping empty entries (they mean "current directory")."""
    if not raw:
        return ()
    return tuple(raw.split(os.pathsep))


def expand_entry(entry: str, cwd: str) -> str:
    """Turn one PATH entry into an absolute directory path."""
    if entry == "":
        return os.path.abspath(cwd)
    expanded = os.path.expanduser(entry)
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd, expanded)
    return os.path.normpath(expanded)


def unstable_entry(entry: str) -> bool:
    """A PATH entry that names no fixed directory: empty, or relative.

    ``""`` and ``.`` mean "whatever directory you happen to be in", so what they
    resolve to is decided by the working directory of the moment — which, for a
    tool called from a chat about a repository, can be that repository. A copy
    reached through one is reported but never executed.
    """
    if entry == "":
        return True
    return not os.path.isabs(os.path.expanduser(entry))


def hermes_home() -> str:
    """The active Hermes home, profile-aware, never hardcoded to ``~/.hermes``.

    Hermes' own resolver is used when this runs inside Hermes, because it also
    knows about a context-local override and the platform default. It is
    imported lazily and tolerated missing: the plugin has to load, and be
    testable, outside a Hermes process too.
    """
    try:
        from hermes_constants import get_hermes_home  # type: ignore[import-not-found]

        return os.path.abspath(os.path.expanduser(str(get_hermes_home())))
    except Exception:  # noqa: BLE001 - no Hermes internals, no problem
        pass
    configured = os.environ.get("HERMES_HOME")
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(os.path.expanduser("~"), ".hermes")


def hermes_source(raw: str | None = None) -> PathSource:
    """The PATH this Hermes process was started with — ``os.environ["PATH"]``.

    It is what any subprocess spawned with this process's environment resolves
    names against. It is **not** necessarily what a command typed into Hermes's
    terminal tool gets: that tool runs the command in a login shell whose PATH
    is the shell's own plus directories Hermes appends (``~/.local/bin``,
    ``$HERMES_HOME/bin``, Homebrew's defaults), so the copy that wins there can
    differ. The report says so instead of pretending the two are one PATH.
    """
    if raw is None:
        raw = os.environ.get("PATH", "")
    entries = split_path(raw)
    if not entries:
        return PathSource(
            kind=HERMES_SOURCE,
            label="Hermes's process PATH",
            entries=(),
            available=False,
            note="Hermes has no PATH in its environment, so nothing can resolve by name.",
            raw=raw,
        )
    return PathSource(
        kind=HERMES_SOURCE,
        label="Hermes's process PATH",
        entries=entries,
        raw=raw,
    )


def custom_source(raw: str) -> PathSource:
    """A PATH the caller supplied — a script's, a cron job's, a colleague's, a demo's.

    This is never presented as Hermes's own PATH: the report says whose PATH it
    is, and states separately what Hermes would do with its own.
    """
    entries = split_path(raw)
    # The note exists to explain why nothing can resolve, so it belongs only on a
    # PATH that really is empty. Attaching it to every custom source made the JSON
    # contradict itself: available=true, two entries, and "the PATH was empty" in
    # the same block.
    note = "" if entries else "The PATH you passed in was empty, so nothing can resolve in it."
    return PathSource(
        kind=CUSTOM_SOURCE,
        label="the PATH you supplied",
        entries=entries,
        available=bool(entries),
        note=note,
        raw=raw,
    )


def login_shell_path() -> str | None:
    """The login shell from the password database. ``$SHELL`` is only a fallback.

    A GUI-launched process often has a stale or missing ``$SHELL``; the password
    entry is the shell the user actually gets in a terminal.
    """
    try:
        shell = pwd.getpwuid(os.getuid()).pw_shell
    except (KeyError, AttributeError, OSError):
        shell = None
    if not shell:
        shell = os.environ.get("SHELL")
    if not shell or not os.path.exists(shell):
        return None
    return shell


def _login_shell_env() -> dict:
    """A small, deliberate environment for the login-shell probe.

    The user's own shell startup files run here, so they need the basics
    (``HOME``, ``USER``, ``TERM``) — but nothing else from Hermes's environment
    is handed over, and no secret in it is passed along.

    ``PATH`` is seeded with :data:`SYSTEM_DEFAULT_PATH`, *not* with Hermes's
    PATH. Seeding it with Hermes's PATH would make a shell that never touches
    PATH look like it agrees with Hermes, and would attribute Hermes's own
    directories to the user's terminal. Starting from the system default means
    every extra entry in the captured PATH was put there by the user's shell.
    """
    keep = ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR")
    env = {name: os.environ[name] for name in keep if os.environ.get(name)}
    env.setdefault("HOME", os.path.expanduser("~"))
    env.setdefault("TERM", "xterm-256color")
    env["PATH"] = SYSTEM_DEFAULT_PATH
    return env


def parse_environment_dump(data: bytes) -> dict:
    """Parse a NUL-delimited ``env -0`` dump between the sentinels.

    Values containing newlines survive because the delimiter is NUL, not a line
    break. Anything printed outside the sentinels (a greeting from an rc file, a
    prompt) is discarded.
    """
    begin = (LOGIN_SHELL_BEGIN + "\n").encode()
    end = LOGIN_SHELL_END.encode()
    start = data.find(begin)
    if start < 0:
        return {}
    finish = data.find(end, start + len(begin))
    if finish < 0:
        return {}
    payload = data[start + len(begin) : finish]
    result: dict[str, str] = {}
    for chunk in payload.split(b"\x00"):
        if not chunk:
            continue
        text = chunk.decode("utf-8", "replace")
        key, sep, value = text.partition("=")
        if sep and key:
            result[key] = value
    return result


def login_shell_source(timeout: float = LOGIN_SHELL_TIMEOUT) -> PathSource:
    """Resolve the PATH a terminal on this machine would get.

    The shell is launched ``-l -i`` so its startup files run, printing an
    ``env -0`` dump between two sentinels. Output is *captured only* — nothing is
    sourced or evaluated into this process. If it fails or takes longer than
    ``timeout``, the result says so instead of inventing a PATH.
    """
    label = "your login shell"
    if sys.platform.startswith("win"):
        return PathSource(
            kind=LOGIN_SHELL_SOURCE,
            label=label,
            entries=(),
            available=False,
            note="Reading a login shell's PATH is macOS/Linux only.",
        )

    shell = login_shell_path()
    if not shell:
        return PathSource(
            kind=LOGIN_SHELL_SOURCE,
            label=label,
            entries=(),
            available=False,
            note="Could not determine your login shell from the user database.",
            seeded=SYSTEM_DEFAULT_PATH,
        )
    label = f"your login shell ({os.path.basename(shell)})"
    script = (
        'printf "\\n%s\\n"; env -0; printf "%s\\n"'
        % (LOGIN_SHELL_BEGIN, LOGIN_SHELL_END)
    )
    argv = [shell, "-l", "-i", "+m", "-c", script]
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            env=_login_shell_env(),
            close_fds=True,
        )
    except subprocess.TimeoutExpired:
        return PathSource(
            kind=LOGIN_SHELL_SOURCE,
            label=label,
            entries=(),
            available=False,
            degraded=True,
            note=(
                "Your shell did not answer within %.0f s (a slow startup file), so "
                "its PATH was not read. Carrier of truth here: Hermes's process PATH."
                % timeout
            ),
            seeded=SYSTEM_DEFAULT_PATH,
        )
    except OSError as exc:
        return PathSource(
            kind=LOGIN_SHELL_SOURCE,
            label=label,
            entries=(),
            available=False,
            note="Could not start %s (%s)." % (shell, exc.strerror or exc),
            seeded=SYSTEM_DEFAULT_PATH,
        )

    dump = parse_environment_dump(completed.stdout or b"")
    raw = dump.get("PATH", "")
    if not raw:
        return PathSource(
            kind=LOGIN_SHELL_SOURCE,
            label=label,
            entries=(),
            available=False,
            degraded=True,
            note=(
                "Your shell answered but printed no PATH, so its PATH was not "
                "read. Carrier of truth here: Hermes's process PATH."
            ),
            seeded=SYSTEM_DEFAULT_PATH,
        )
    return PathSource(
        kind=LOGIN_SHELL_SOURCE,
        label=label,
        entries=split_path(raw),
        raw=raw,
        seeded=SYSTEM_DEFAULT_PATH,
    )


# --------------------------------------------------------------------------- #
# Candidates


@dataclass(frozen=True)
class Candidate:
    """One place a tool name resolves to, on or off PATH."""

    entry_path: str
    kind: str
    executable: bool
    slot: int | None = None
    directory: str = ""
    on_path: bool = True
    extra_root: str | None = None
    canonical: str | None = None
    chain: tuple[str, ...] = ()
    inode: int | None = None
    size: int | None = None
    error: str = ""
    #: True when the PATH entry this came from was empty or relative, so the
    #: directory it names is decided by the caller's working directory.
    unstable_entry: bool = False

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def is_live(self) -> bool:
        return self.executable and self.kind in LIVE_KINDS

    def as_dict(self, home: str = "") -> dict:
        payload = {
            "path": _tidy(self.entry_path, home),
            "path_raw": self.entry_path,
            "kind": self.kind,
            "kind_label": self.kind_label,
            "usable": self.is_live,
            "on_path": self.on_path,
            "canonical": _tidy(self.canonical, home) if self.canonical else None,
            "canonical_raw": self.canonical,
        }
        if self.slot is not None:
            payload["path_slot"] = self.slot
            payload["path_directory"] = _tidy(self.directory, home)
        if self.unstable_entry:
            payload["relative_path_entry"] = True
        if self.extra_root:
            payload["extra_root"] = _tidy(self.extra_root, home)
        if len(self.chain) > 1:
            payload["symlink_chain"] = [_tidy(p, home) for p in self.chain]
        if self.inode is not None:
            payload["inode"] = self.inode
        if self.size is not None:
            payload["size"] = self.size
        if self.error:
            payload["error"] = self.error
        return payload


def symlink_chain(path: str, limit: int = 32) -> tuple[str, ...]:
    """Follow a symlink chain by hand, so a loop is reported instead of raised."""
    chain: list[str] = [path]
    current = path
    for _ in range(limit):
        try:
            target = os.readlink(current)
        except OSError:
            break
        if not os.path.isabs(target):
            target = os.path.normpath(os.path.join(os.path.dirname(current), target))
        if target in chain:
            chain.append(target)
            break
        chain.append(target)
        current = target
    return tuple(chain)


def inspect(
    entry_path: str,
    *,
    slot: int | None = None,
    directory: str = "",
    on_path: bool = True,
    extra_root: str | None = None,
    unstable_entry: bool = False,
) -> Candidate | None:
    """Inspect one path. ``None`` means nothing is there at all."""
    try:
        link_info = os.lstat(entry_path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        return Candidate(
            entry_path=entry_path,
            kind=KIND_SYMLINK_UNREADABLE,
            executable=False,
            slot=slot,
            directory=directory,
            on_path=on_path,
            extra_root=extra_root,
            unstable_entry=unstable_entry,
            error=exc.strerror or str(exc),
        )

    is_link = stat.S_ISLNK(link_info.st_mode)
    target_info = link_info
    if is_link:
        try:
            target_info = os.stat(entry_path)
        except OSError as exc:
            if exc.errno in (errno.ENOENT, errno.ENOTDIR):
                kind = KIND_BROKEN_SYMLINK
            elif exc.errno == errno.ELOOP:
                kind = KIND_SYMLINK_LOOP
            else:
                kind = KIND_SYMLINK_UNREADABLE
            return Candidate(
                entry_path=entry_path,
                kind=kind,
                executable=False,
                slot=slot,
                directory=directory,
                on_path=on_path,
                extra_root=extra_root,
                unstable_entry=unstable_entry,
                chain=symlink_chain(entry_path),
                error=exc.strerror or str(exc),
            )

    mode = target_info.st_mode
    if stat.S_ISREG(mode):
        executable = os.access(entry_path, os.X_OK)
        if is_link:
            kind = KIND_EXECUTABLE_SYMLINK if executable else KIND_SYMLINK_NOT_EXECUTABLE
        else:
            kind = KIND_EXECUTABLE if executable else KIND_NOT_EXECUTABLE
    elif stat.S_ISDIR(mode):
        executable = False
        kind = KIND_SYMLINK_DIRECTORY if is_link else KIND_DIRECTORY
    else:
        executable = False
        kind = KIND_NON_REGULAR

    canonical = None
    if executable:
        canonical = os.path.realpath(entry_path)

    size = None
    inode = None
    if stat.S_ISREG(mode):
        size = int(target_info.st_size)
        inode = int(target_info.st_ino)

    return Candidate(
        entry_path=entry_path,
        kind=kind,
        executable=executable,
        slot=slot,
        directory=directory,
        on_path=on_path,
        extra_root=extra_root,
        canonical=canonical,
        chain=symlink_chain(entry_path) if is_link else (entry_path,),
        inode=inode,
        size=size,
        unstable_entry=unstable_entry,
    )


def candidates_on_path(
    name: str, source: PathSource, cwd: str | None = None
) -> list[Candidate]:
    """Every PATH slot that holds something called ``name``, in PATH order.

    A directory listed twice in PATH contributes one candidate, at its first
    position — that is where the shell would stop, and repeating it would only
    make the report look longer than the machine is complicated.
    """
    if not source.available:
        return []
    cwd = cwd or os.getcwd()
    found: list[Candidate] = []
    seen: set[str] = set()
    for slot, raw_entry in enumerate(source.entries):
        directory = expand_entry(raw_entry, cwd)
        entry_path = os.path.join(directory, name)
        key = os.path.normpath(entry_path)
        if key in seen:
            continue
        seen.add(key)
        candidate = inspect(
            entry_path,
            slot=slot,
            directory=raw_entry,
            unstable_entry=unstable_entry(raw_entry),
        )
        if candidate is not None:
            found.append(candidate)
    return found


def repeated_slot_count(source: PathSource, cwd: str | None = None) -> int:
    """How many PATH entries are a repeat of an earlier one."""
    if not source.available:
        return 0
    cwd = cwd or os.getcwd()
    seen: set[str] = set()
    repeats = 0
    for raw_entry in source.entries:
        key = os.path.normpath(expand_entry(raw_entry, cwd))
        if key in seen:
            repeats += 1
        else:
            seen.add(key)
    return repeats


def extra_roots(home: str | None = None, hermes: str | None = None) -> list[str]:
    """Well-known install locations, whether or not they are on PATH.

    This is what lets the report say "there is another copy you are not using"
    rather than only listing what PATH already sees. Only directories that exist
    are returned, the list is deduplicated, and it is capped.
    """
    home = home or os.path.expanduser("~")
    hermes = hermes or hermes_home()

    fixed = [
        os.path.join(hermes, "bin"),
        os.path.join(hermes, "node", "bin"),
        os.path.join(hermes, "hermes-agent", "node_modules", ".bin"),
        os.path.join(home, ".local", "bin"),
        os.path.join(home, ".local", "shims"),
        os.path.join(home, ".npm-global", "bin"),
        os.path.join(home, ".bun", "bin"),
        os.path.join(home, ".volta", "bin"),
        os.path.join(home, ".deno", "bin"),
        os.path.join(home, ".cargo", "bin"),
        os.path.join(home, ".pyenv", "shims"),
        os.path.join(home, "bin"),
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/usr/local/sbin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    patterns = [
        (os.path.join(hermes, "tools", "*", "bin"), MAX_GLOB_ROOTS),
        (os.path.join(home, ".nvm", "versions", "node", "*", "bin"), 6),
        (os.path.join(home, ".pyenv", "versions", "*", "bin"), 6),
        (os.path.join(home, ".local", "share", "uv", "tools", "*", "bin"), 8),
        (os.path.join(home, ".local", "pipx", "venvs", "*", "bin"), 8),
        (os.path.join(home, ".asdf", "installs", "*", "*", "bin"), 6),
    ]

    roots: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        normalized = os.path.normpath(path)
        if normalized in seen:
            return
        if not os.path.isdir(normalized):
            return
        seen.add(normalized)
        roots.append(normalized)

    for path in fixed:
        add(path)
    for pattern, cap in patterns:
        matches = sorted(_glob.glob(pattern))[:cap]
        for match in matches:
            add(match)
    return roots[:MAX_EXTRA_ROOTS]


def candidates_off_path(
    name: str,
    roots: Sequence[str],
    already: Iterable[str] = (),
) -> list[Candidate]:
    """Copies of ``name`` that exist in known locations but not on any PATH slot."""
    covered = {os.path.normpath(path) for path in already}
    found: list[Candidate] = []
    for root in roots:
        entry_path = os.path.join(root, name)
        if os.path.normpath(entry_path) in covered:
            continue
        candidate = inspect(entry_path, on_path=False, extra_root=root)
        if candidate is not None and candidate.is_live:
            found.append(candidate)
    return found


# --------------------------------------------------------------------------- #
# What this check is allowed to execute


#: Why a copy was described but never run. Each string finishes the sentence
#: "not run: …" in a report, so it is written for a person, not a log.
NOT_RUN_NAMED = "this check does not run a file you name"
NOT_RUN_OUTSIDE = (
    "it is not in a directory this check runs files from — Hermes's PATH, your "
    "login shell's PATH, or a known install directory"
)
NOT_RUN_RELATIVE = (
    "it sits in a relative or empty PATH entry, which resolves against whatever "
    "directory you happen to be in"
)


@dataclass(frozen=True)
class ProbeTrust:
    """The directories this check may execute a copy from.

    Built from the machine's own configuration — the PATH of the Hermes process,
    the PATH the user's login shell builds, and the fixed install directories —
    and **never** from an argument. That is the whole defense: a prompt-injected
    repository can ask for a path, or pass a PATH string, but it cannot change
    the PATH the user's own shell and Hermes were started with, so it cannot get
    a file of its choosing executed. Files it names are still described.

    A copy is run only when the directory that holds it is one of these; the
    comparison is on the resolved directory, so a PATH entry that is itself a
    symlink is judged by the directory it really names. The entry's own target is
    not part of the test: a symlinked copy in a trusted directory is exactly what
    a shell would reach, which is the thing this plugin exists to report.
    """

    directories: tuple[str, ...] = ()

    def allows(self, entry_path: str) -> bool:
        """May the copy at ``entry_path`` be executed?"""
        if not entry_path:
            return False
        directory = os.path.dirname(os.path.abspath(entry_path))
        try:
            resolved = os.path.realpath(directory)
        except OSError:  # pragma: no cover - realpath only fails pathologically
            return False
        return resolved in self.directories


def probe_trust(
    *,
    shell: PathSource | None = None,
    home: str | None = None,
    hermes: str | None = None,
) -> ProbeTrust:
    """Assemble the executable-by-this-check directories for one call.

    ``shell`` is the login-shell source when the call read one; the Hermes
    process PATH and the fixed install roots are always included. Nothing a
    caller passed in as an argument takes part.
    """
    directories: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        # An empty or relative entry names no fixed directory: it must not make
        # today's working directory executable.
        if not raw or unstable_entry(raw):
            return
        expanded = os.path.normpath(os.path.abspath(os.path.expanduser(raw)))
        try:
            resolved = os.path.realpath(expanded)
        except OSError:  # pragma: no cover - realpath only fails pathologically
            return
        if resolved in seen:
            return
        seen.add(resolved)
        directories.append(resolved)

    for source in (hermes_source(), shell):
        if source is None or not source.available:
            continue
        for entry in source.entries:
            add(entry)
    for root in extra_roots(home=home, hermes=hermes):
        add(root)
    return ProbeTrust(directories=tuple(directories))


def refusal(candidate: Candidate, trust: ProbeTrust) -> str:
    """Why this copy must not be executed — ``""`` when it may be."""
    if candidate.unstable_entry:
        return NOT_RUN_RELATIVE
    if not trust.allows(candidate.entry_path):
        return NOT_RUN_OUTSIDE
    return ""


# --------------------------------------------------------------------------- #
# Presentation helpers


def _tidy(path: str | None, home: str = "") -> str:
    """Shorten a path for display: ``$HERMES_HOME`` first, then ``~``.

    Profile install paths carry two long hashes that say nothing to a reader, so
    ``installs/<hash>/environments/<hash>/venv`` collapses to
    ``installs/…/venv``. Nothing else is abbreviated: the directory a copy lives
    in is the evidence.
    """
    if not path:
        return ""
    home = home or os.path.expanduser("~")
    hermes = hermes_home()
    text = path
    if hermes and (text == hermes or text.startswith(hermes + os.sep)):
        text = "$HERMES_HOME" + text[len(hermes) :]
    elif home and (text == home or text.startswith(home + os.sep)):
        text = "~" + text[len(home) :]
    text = _INSTALL_HASH_RE.sub(r"\1/…/venv/", text)
    return text


def tidy(path: str | None, home: str = "") -> str:
    """Public form of :func:`_tidy`."""
    return _tidy(path, home)


def path_preview(source: PathSource, home: str = "") -> str:
    """A short readable rendering of a PATH, for the report header."""
    if not source.available:
        return source.note or "unavailable"
    shown = [_tidy(entry or "(current dir)", home) for entry in source.entries[:PATH_PREVIEW]]
    tail = len(source.entries) - len(shown)
    text = os.pathsep.join(shown)
    if tail > 0:
        text += " … (%d more)" % tail
    return text
