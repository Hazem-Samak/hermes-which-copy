"""Asking a copy what version it is — carefully, and never for long.

Running ``--version`` on an unknown binary is the only thing in this plugin that
executes anything, so it is fenced in:

* argv only, never a shell — the path cannot be turned into a command line.
* a fresh, stripped environment: the probe never sees ``OPENAI_API_KEY``,
  ``ANTHROPIC_API_KEY``, or anything else from Hermes's environment. A shadowing
  binary gets a PATH, ``HOME`` and a locale, and nothing worth stealing.
* ``cwd`` is the filesystem root, which the user cannot write to, so a tool that
  drops files "next to itself" fails instead of littering a project.
* its own process group, killed as a group on timeout.
* a wall-clock deadline (3 s by default) and a hard cap on how much output is
  kept, so a runaway program cannot flood the chat or the memory.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass

PROBE_TIMEOUT = 3.0
PROBE_OUTPUT_LIMIT = 8192

DEFAULT_ARGS: tuple[str, ...] = ("--version",)

#: Tools whose version flag is not the usual ``--version``.
PER_TOOL_ARGS = {
    "go": ("version",),
    "java": ("-version",),
    "ssh": ("-V",),
    "javac": ("-version",),
}

PROBE_ERROR_HINTS = {
    "timeout": "it did not answer within the time limit",
    "not_executable": "it is not executable",
    "os_error": "the system refused to start it",
    "no_output": "it printed nothing at all",
    "no_version_text": "it printed no version number",
    "output_limit": "it printed too much to read safely",
    "not_probed": "there was no time left in this check's budget to ask it",
    "probe_error": "the check itself failed while running it",
    "missing_helper": "it could not find a command it needs, because PATH does not reach it",
}

_VERSION_RE = re.compile(
    r"(?<![0-9.])"
    r"(\d{1,4}(?:\.\d{1,4}){1,3}"
    r"(?:[-+~][0-9A-Za-z][0-9A-Za-z.\-]{0,15}|(?:a|b|rc)[0-9]{1,2})?)"
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass(frozen=True)
class ParsedVersion:
    text: str
    numbers: tuple[int, ...]
    prerelease: str

    @property
    def comparable_core(self) -> tuple[int, ...]:
        return self.numbers


@dataclass
class Probe:
    """What one copy said about itself."""

    argv: tuple[str, ...]
    version: str | None = None
    raw: str = ""
    stream: str = ""
    exit_code: int | None = None
    error: str | None = None
    timed_out: bool = False
    truncated: bool = False
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.version is not None

    @property
    def error_hint(self) -> str:
        if not self.error:
            return ""
        base = self.error.split(":")[0]
        return PROBE_ERROR_HINTS.get(base, base)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "version": self.version,
            "raw": self.raw,
            "stream": self.stream,
            "command": list(self.argv),
            "exit_code": self.exit_code,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class RunResult:
    exit_code: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False
    truncated: bool = False
    error: str | None = None
    elapsed_ms: int = 0


def probe_environment(path_value: str) -> dict:
    """A deliberately small environment for a probed binary."""
    env = {
        "PATH": path_value or "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "CLICOLOR": "0",
        "PYTHONIOENCODING": "utf-8",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }
    for name in ("HOME", "LANG", "LC_ALL", "TMPDIR", "USER"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    env.setdefault("HOME", os.path.expanduser("~"))
    return {key: value for key, value in env.items() if value != "" or key == "PATH"}


def _reader(stream, buffer: bytearray, limit: int, state: dict) -> None:
    """Drain a pipe, keeping at most ``limit`` bytes but never blocking the child."""
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            room = limit - len(buffer)
            if room > 0:
                buffer.extend(chunk[:room])
                if len(chunk) > room:
                    state["truncated"] = True
            else:
                state["truncated"] = True
    except (ValueError, OSError):
        pass
    finally:
        try:
            stream.close()
        except Exception:  # noqa: BLE001 - closing a dead pipe must not raise
            pass


def _kill(process: subprocess.Popen) -> None:
    """Kill the probe and anything it started."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        process.kill()
    except (ProcessLookupError, OSError):
        pass


def run_bounded(
    argv: list[str] | tuple[str, ...],
    *,
    timeout: float = PROBE_TIMEOUT,
    env: dict | None = None,
    cwd: str | None = None,
    limit: int = PROBE_OUTPUT_LIMIT,
) -> RunResult:
    """Run ``argv`` with a deadline, a bounded buffer and its own process group."""
    started = time.monotonic()
    cwd = cwd or os.path.abspath(os.sep)
    try:
        process = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env if env is not None else probe_environment(""),
            cwd=cwd,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        return RunResult(
            error="os_error: %s" % (exc.strerror or exc),
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    out, err = bytearray(), bytearray()
    state = {"truncated": False}
    threads = [
        threading.Thread(target=_reader, args=(process.stdout, out, limit, state), daemon=True),
        threading.Thread(target=_reader, args=(process.stderr, err, limit, state), daemon=True),
    ]
    for thread in threads:
        thread.start()

    timed_out = False
    remaining = max(0.0, timeout - (time.monotonic() - started))
    try:
        exit_code = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill(process)
        try:
            exit_code = process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            exit_code = None

    for thread in threads:
        thread.join(0.5)

    return RunResult(
        exit_code=exit_code,
        stdout=bytes(out),
        stderr=bytes(err),
        timed_out=timed_out,
        truncated=state["truncated"],
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


def clean_text(raw: str, limit: int = 400) -> str:
    """One readable line of a tool's output: no ANSI, no control characters."""
    text = _ANSI_RE.sub("", raw or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    joined = " | ".join(lines[:3])
    joined = "".join(ch if ch.isprintable() else " " for ch in joined)
    joined = re.sub(r"\s{2,}", " ", joined).strip()
    return joined[:limit]


def parse_version_text(text: str) -> ParsedVersion | None:
    """Pull the first version-shaped token out of a line of output."""
    match = _VERSION_RE.search(text or "")
    if not match:
        return None
    token = match.group(1)
    core = token
    prerelease = ""
    for index, char in enumerate(token):
        if char in "-+~":
            core, prerelease = token[:index], token[index + 1 :]
            break
        if char in "ab" and index > 0 and token[index + 1 : index + 2].isdigit():
            core, prerelease = token[:index], token[index:]
            break
        if token[index : index + 2] == "rc" and index > 0:
            core, prerelease = token[:index], token[index:]
            break
    numbers: list[int] = []
    for part in core.split("."):
        if not part.isdigit():
            return None
        numbers.append(int(part))
    if len(numbers) < 2:
        return None
    return ParsedVersion(text=token, numbers=tuple(numbers), prerelease=prerelease)


def compare_versions(left: str, right: str) -> int | None:
    """``-1`` if left is older, ``1`` if newer, ``0`` if equal, ``None`` if unsure.

    ``None`` is a real answer: two numbers that were never meant to be compared
    (a date-version against a semantic one, or schemes with different depths)
    are refused rather than ordered confidently and wrongly.
    """
    a = parse_version_text(left)
    b = parse_version_text(right)
    if a is None or b is None:
        return None
    if abs(len(a.numbers) - len(b.numbers)) >= 2:
        return None
    if (max(a.numbers) >= 1000) != (max(b.numbers) >= 1000):
        return None
    depth = max(len(a.numbers), len(b.numbers))
    left_core = a.numbers + (0,) * (depth - len(a.numbers))
    right_core = b.numbers + (0,) * (depth - len(b.numbers))
    if left_core != right_core:
        return -1 if left_core < right_core else 1
    if bool(a.prerelease) != bool(b.prerelease):
        # A prerelease sorts before the release it leads up to.
        return -1 if a.prerelease else 1
    if a.prerelease != b.prerelease:
        return -1 if a.prerelease < b.prerelease else 1
    return 0


def probe(
    executable: str,
    *,
    tool: str = "",
    timeout: float = PROBE_TIMEOUT,
    path_value: str = "",
    args: tuple[str, ...] | None = None,
) -> Probe:
    """Ask one copy its version. Never raises."""
    argv = args or PER_TOOL_ARGS.get(tool, DEFAULT_ARGS)
    if not os.access(executable, os.X_OK):
        return Probe(argv=tuple(argv), error="not_executable")
    result = run_bounded(
        [executable, *argv],
        timeout=timeout,
        env=probe_environment(path_value),
    )
    if result.error:
        return Probe(argv=tuple(argv), error=result.error, elapsed_ms=result.elapsed_ms)

    stdout = result.stdout.decode("utf-8", "replace")
    stderr = result.stderr.decode("utf-8", "replace")
    stream = "stdout" if stdout.strip() else ("stderr" if stderr.strip() else "")
    text = clean_text(stdout if stream == "stdout" else stderr)

    if result.timed_out:
        return Probe(
            argv=tuple(argv),
            raw=text,
            stream=stream,
            exit_code=result.exit_code,
            error="timeout",
            timed_out=True,
            truncated=result.truncated,
            elapsed_ms=result.elapsed_ms,
        )
    if not text:
        return Probe(
            argv=tuple(argv),
            exit_code=result.exit_code,
            error="no_output",
            elapsed_ms=result.elapsed_ms,
        )

    parsed = parse_version_text(text)
    return Probe(
        argv=tuple(argv),
        version=parsed.text if parsed else None,
        raw=text,
        stream=stream,
        exit_code=result.exit_code,
        error=(
            None
            if parsed
            else ("missing_helper" if result.exit_code == 127 else "no_version_text")
        ),
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
    )
