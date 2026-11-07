"""Where a copy came from — the evidence, not a guess dressed up as one.

Every label produced here is backed by a path fact: a Homebrew ``Cellar``
directory, an npm ``lib/node_modules`` tree, a pyenv version directory, and so
on. When no such layout matches, the copy is reported as *standalone* with the
directory it lives in — because "I do not know" is a real answer and the honest
one.

Nothing here runs a command or touches the network. The only file reads are the
first few bytes of the executable, to tell a script from a binary and to read a
Mach-O CPU type (an x86_64-only tool on Apple silicon is its own kind of trap).
"""

from __future__ import annotations

import os
import platform
import struct
from dataclasses import dataclass

HOME = os.path.expanduser("~")


def _hermes_home() -> str:
    """The active Hermes home, profile-aware (``$HERMES_HOME`` wins)."""
    configured = os.environ.get("HERMES_HOME")
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(HOME, ".hermes")

# Mach-O / fat header constants.
_MH_MAGIC_64 = 0xFEEDFACF
_MH_MAGIC_32 = 0xFEEDFACE
_MH_CIGAM_64 = 0xCFFAEDFE
_MH_CIGAM_32 = 0xCEFAEDFE
_FAT_MAGIC = 0xCAFEBABE
_FAT_CIGAM = 0xBEBAFECA
_CPU_ARCH_ABI64 = 0x01000000
_CPU_TYPE_X86 = 7
_CPU_TYPE_ARM = 12

CPU_NAMES = {
    _CPU_TYPE_X86 | _CPU_ARCH_ABI64: "x86_64",
    _CPU_TYPE_ARM | _CPU_ARCH_ABI64: "arm64",
    _CPU_TYPE_X86: "i386",
    _CPU_TYPE_ARM: "arm",
}


@dataclass(frozen=True)
class Origin:
    """What produced this copy, with the evidence that says so."""

    kind: str
    label: str
    evidence: str
    manager: str | None = None
    package: str | None = None
    verified: bool = False

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "evidence": self.evidence,
            "manager": self.manager,
            "package": self.package,
            "verified": self.verified,
        }


def _inside(path: str, prefix: str) -> bool:
    if not path or not prefix:
        return False
    prefix = prefix.rstrip(os.sep)
    return path == prefix or path.startswith(prefix + os.sep)


def _segment_after(path: str, marker: str) -> str | None:
    """Return the path segment right after ``marker`` (``/Cellar/<formula>/…``)."""
    if not path or not marker:
        return None
    needle = marker if marker.endswith(os.sep) else marker + os.sep
    index = path.find(needle)
    if index < 0:
        return None
    rest = path[index + len(needle) :]
    if not rest:
        return None
    return rest.split(os.sep)[0]


def _package_after_node_modules(path: str) -> str | None:
    """``…/lib/node_modules/@openai/codex/bin/x.js`` → ``@openai/codex``."""
    for marker in ("/node_modules/", os.sep + "node_modules" + os.sep):
        index = path.find(marker)
        if index < 0:
            continue
        rest = path[index + len(marker) :]
        parts = [part for part in rest.split(os.sep) if part]
        if not parts:
            return None
        if parts[0].startswith("@"):
            return "/".join(parts[:2]) if len(parts) > 1 else parts[0]
        return parts[0]
    return None


def _hermes_label(path: str, hermes: str) -> tuple[str, str | None]:
    """Name the Hermes-managed location more precisely than "inside HERMES_HOME"."""
    relative = path[len(hermes) :].lstrip(os.sep)
    head = relative.split(os.sep)[0] if relative else ""
    if head == "tools":
        tool_dir = _segment_after(relative, "tools")
        return "a tool Hermes downloaded", tool_dir
    if head == "node":
        return "the Node runtime Hermes installed", None
    if head == "installs":
        return "a Hermes plugin environment", None
    if head == "hermes-agent":
        package = _package_after_node_modules(relative)
        return "a Node package bundled with Hermes", package
    if head == "bin":
        return "Hermes's own bin directory", None
    return "inside Hermes's home directory", None


#: How specific each kind of evidence is. When the name on PATH and the file it
#: resolves to are in different places (a Homebrew symlink, a uv tool that points
#: at a shared interpreter), the more specific label wins — and the resolution is
#: named in the evidence rather than hidden.
_SPECIFICITY = {
    "homebrew_formula": 90,
    "homebrew_cask": 90,
    "npm_global": 85,
    "bun_global": 84,
    "pnpm_global": 84,
    "pyenv": 80,
    "uv_tool": 80,
    "pipx": 80,
    "python_framework": 80,
    "nvm": 78,
    "volta": 78,
    "asdf": 78,
    "hermes_managed": 70,
    "apple_toolchain": 60,
    "system": 50,
    "app_bundle": 40,
    "standalone": 10,
}


def _rank(origin: Origin) -> int:
    return _SPECIFICITY.get(origin.kind, 0)


def classify(
    entry_path: str,
    canonical: str | None,
    *,
    home: str | None = None,
    hermes: str | None = None,
) -> Origin:
    """Classify one copy from its entry path and the file it resolves to.

    Both ends are classified, because each can carry the better evidence: the
    entry says what the user installed (``~/.local/share/uv/tools/x/bin/python3``)
    while the resolved file says which manager owns the actual bytes (a Homebrew
    Cellar directory, a shared uv interpreter). The more specific of the two
    wins, and when they disagree the resolution is stated in the evidence.
    """
    home = home or HOME
    entry = entry_path or ""
    real = canonical or entry
    hermes = hermes or _hermes_home()
    entry_origin = _classify_single(entry, entry, home=home, hermes=hermes)
    if real and real != entry:
        real_origin = _classify_single(real, real, home=home, hermes=hermes)
    else:
        real_origin = entry_origin

    chosen = entry_origin if _rank(entry_origin) >= _rank(real_origin) else real_origin

    if real != entry and _display(real, home, hermes) not in chosen.evidence:
        if real_origin.kind == chosen.kind:
            suffix = "; the name itself resolves to %s" % _display(real, home, hermes)
        else:
            suffix = "; the name itself resolves to %s (%s)" % (
                _display(real, home, hermes),
                real_origin.label,
            )
        return Origin(
            kind=chosen.kind,
            label=chosen.label,
            evidence=chosen.evidence + suffix,
            manager=chosen.manager,
            package=chosen.package,
            verified=chosen.verified,
        )
    return chosen


def _classify_single(entry: str, real: str, *, home: str, hermes: str | None) -> Origin:

    # 1. Hermes's own copies come first: a Hermes-managed path is the most
    #    specific true statement, and it is what usually explains a surprise.
    if _inside(real, hermes) or _inside(entry, hermes):
        where = real if _inside(real, hermes) else entry
        label, package = _hermes_label(where, hermes)
        return Origin(
            kind="hermes_managed",
            label=label,
            evidence="it lives in %s, which is Hermes's own directory" % _display(where, home, hermes),
            manager="Hermes",
            package=package,
            verified=True,
        )

    # 2. Homebrew Cellar / Caskroom — the resolved path names the formula.
    formula = _segment_after(real, "/Cellar/")
    if formula:
        return Origin(
            kind="homebrew_formula",
            label="Homebrew formula %s" % formula,
            evidence="it resolves into Homebrew's Cellar at %s" % _display(real, home, hermes),
            manager="Homebrew",
            package=formula,
            verified=True,
        )
    cask = _segment_after(real, "/Caskroom/")
    if cask:
        return Origin(
            kind="homebrew_cask",
            label="Homebrew cask %s" % cask,
            evidence="it resolves into Homebrew's Caskroom at %s" % _display(real, home, hermes),
            manager="Homebrew",
            package=cask,
            verified=True,
        )

    # 3. JavaScript package managers. Bun before npm: its tree also contains
    #    "node_modules", and mislabelling bun as npm would send the user to the
    #    wrong uninstall command.
    for needle, kind, manager, label in (
        ("/.bun/install/global/node_modules/", "bun_global", "Bun", "a Bun global package"),
        ("/.pnpm/global/", "pnpm_global", "pnpm", "a pnpm global package"),
    ):
        if needle in real or needle in entry:
            package = _package_after_node_modules(real)
            return Origin(
                kind=kind,
                label="%s%s" % (label, " %s" % package if package else ""),
                evidence="it resolves into %s's global module directory at %s"
                % (manager, _display(real, home, hermes)),
                manager=manager,
                package=package,
                verified=True,
            )
    package = _package_after_node_modules(real)
    if package:
        return Origin(
            kind="npm_global",
            label="npm global package %s" % package,
            evidence="it resolves into a node_modules tree at %s" % _display(real, home, hermes),
            manager="npm",
            package=package,
            verified=True,
        )

    # 4. Python version managers and installers.
    pyenv_version = _segment_after(real, "/.pyenv/versions/")
    if pyenv_version:
        return Origin(
            kind="pyenv",
            label="a pyenv Python %s" % pyenv_version,
            evidence="it resolves into pyenv's versions directory at %s" % _display(real, home, hermes),
            manager="pyenv",
            package=pyenv_version,
            verified=True,
        )
    if "/.pyenv/shims/" in entry or "/.pyenv/shims/" in real:
        return Origin(
            kind="pyenv_shim",
            label="a pyenv shim",
            evidence="it goes through pyenv's shim directory at %s" % _display(entry, home, hermes),
            manager="pyenv",
            verified=True,
        )
    uv_tool = _segment_after(real, "/.local/share/uv/tools/")
    if uv_tool:
        return Origin(
            kind="uv_tool",
            label="a uv tool environment (%s)" % uv_tool,
            evidence="it resolves into uv's tool directory at %s" % _display(real, home, hermes),
            manager="uv",
            package=uv_tool,
            verified=True,
        )
    pipx_tool = _segment_after(real, "/.local/pipx/venvs/")
    if pipx_tool:
        return Origin(
            kind="pipx",
            label="a pipx environment (%s)" % pipx_tool,
            evidence="it resolves into pipx's venv directory at %s" % _display(real, home, hermes),
            manager="pipx",
            package=pipx_tool,
            verified=True,
        )
    framework_version = _segment_after(real, "/Library/Frameworks/Python.framework/Versions/")
    if framework_version:
        return Origin(
            kind="python_framework",
            label="the python.org installer (Python %s)" % framework_version,
            evidence="it resolves into the python.org framework at %s"
            % _display(real, home, hermes),
            manager="python.org",
            package=framework_version,
            verified=True,
        )

    # 5. Other version managers.
    nvm_version = _segment_after(real, "/.nvm/versions/node/")
    if nvm_version:
        return Origin(
            kind="nvm",
            label="an nvm Node %s" % nvm_version,
            evidence="it resolves into nvm's versions directory at %s"
            % _display(real, home, hermes),
            manager="nvm",
            package=nvm_version,
            verified=True,
        )
    if _inside(real, os.path.join(home, ".volta")):
        return Origin(
            kind="volta",
            label="a Volta-managed copy",
            evidence="it resolves into Volta's home at %s" % _display(real, home, hermes),
            manager="Volta",
            verified=True,
        )
    asdf_version = _segment_after(real, "/.asdf/installs/")
    if asdf_version:
        return Origin(
            kind="asdf",
            label="an asdf install",
            evidence="it resolves into asdf's installs at %s" % _display(real, home, hermes),
            manager="asdf",
            verified=True,
        )

    # 6. Apple's own toolchains, then macOS itself.
    if _inside(real, "/Library/Developer/CommandLineTools") or "/Xcode" in real and ".app/" in real:
        return Origin(
            kind="apple_toolchain",
            label="Apple's developer toolchain",
            evidence="it resolves into %s" % _display(real, home, hermes),
            manager="Apple",
            verified=True,
        )
    entry_dir = os.path.dirname(entry.rstrip(os.sep)) if entry else ""
    if entry_dir in {"/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/libexec"}:
        return Origin(
            kind="system",
            label="a macOS system copy",
            evidence="it sits in %s, which ships with macOS" % entry_dir,
            manager="Apple",
            verified=True,
        )
    if ".app/Contents/" in real or ".app/Contents/" in entry:
        return Origin(
            kind="app_bundle",
            label="a copy inside an application bundle",
            evidence="it lives inside %s" % _display(real, home, hermes),
            verified=False,
        )

    # 7. Honest unknown: a plain copy in a directory we can name.
    directory = os.path.dirname(real.rstrip(os.sep)) if real else ""
    name = os.path.basename(directory.rstrip(os.sep)) or directory
    return Origin(
        kind="standalone",
        label="a standalone copy in %s" % (name or "an unnamed directory"),
        evidence="nothing identifies a package manager; the file is %s"
        % _display(real, home, hermes),
        manager=None,
        verified=False,
    )


def _display(path: str, home: str, hermes: str) -> str:
    text = path
    if hermes and (text == hermes or text.startswith(hermes + os.sep)):
        return "$HERMES_HOME" + text[len(hermes) :]
    if home and (text == home or text.startswith(home + os.sep)):
        return "~" + text[len(home) :]
    return text


# --------------------------------------------------------------------------- #
# What kind of file is it, and does this machine run it natively?


def binary_arch(path: str) -> str:
    """Read the file's first bytes: ``script``, ``arm64``, ``x86_64``, …

    A script (anything starting with ``#!``) is reported as ``script``. A Mach-O
    header gives the CPU it was compiled for; a fat header gives ``universal``.
    Anything unreadable is ``unknown`` — never a guess.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError:
        return "unknown"
    if not head:
        return "unknown"
    if head.startswith(b"#!"):
        return "script"
    if head.startswith(b"\x7fELF"):
        return "elf"
    if len(head) >= 4:
        magic = struct.unpack(">I", head[:4])[0]
        if magic in (_FAT_MAGIC, _FAT_CIGAM):
            return "universal"
    if len(head) >= 8:
        little = struct.unpack("<I", head[:4])[0]
        if little in (_MH_MAGIC_64, _MH_MAGIC_32):
            cpu = struct.unpack("<I", head[4:8])[0]
            return CPU_NAMES.get(cpu, "mach-o")
        big = struct.unpack(">I", head[:4])[0]
        if big in (_MH_MAGIC_64, _MH_MAGIC_32):
            cpu = struct.unpack(">I", head[4:8])[0]
            return CPU_NAMES.get(cpu, "mach-o")
    return "unknown"


def host_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    return machine or "unknown"


def arch_warning(arch: str, host: str | None = None) -> str | None:
    """Explain an architecture mismatch a user would actually feel."""
    host = host or host_arch()
    if not arch or arch in ("script", "unknown", "elf", "universal"):
        return None
    if host == "arm64" and arch == "x86_64":
        return "it is an Intel-only binary, so it runs under Rosetta on this Mac"
    if host == "x86_64" and arch == "arm64":
        return "it is an Apple-silicon binary and cannot run natively on this Mac"
    return None
