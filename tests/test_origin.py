"""Provenance: which manager owns a copy, and can this machine run it."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest


def classify(origin_module, path, canonical=None, home="/home/x", hermes="/home/x/.hermes"):
    return origin_module.classify(str(path), None if canonical is None else str(canonical),
                                  home=home, hermes=hermes)


HOME = "/Users/tester"
HERMES = "/Users/tester/.hermes"


@pytest.mark.parametrize(
    "entry,expected_kind,expected_manager",
    [
        (f"{HERMES}/tools/python-3.14.9-darwin/bin/python3", "hermes_managed", "Hermes"),
        (f"{HERMES}/installs/abc/environments/def/venv/bin/python3", "hermes_managed", "Hermes"),
        (f"{HERMES}/hermes-agent/node_modules/.bin/prettier", "hermes_managed", "Hermes"),
        (f"{HERMES}/bin/which-copy", "hermes_managed", "Hermes"),
        ("/opt/homebrew/Cellar/python@3.13/3.13.7/bin/python3.13", "homebrew_formula", "Homebrew"),
        ("/opt/homebrew/Caskroom/codex/1.2.3/bin/codex", "homebrew_cask", "Homebrew"),
        ("/opt/homebrew/lib/node_modules/@openai/codex/bin/codex.js", "npm_global", "npm"),
        (f"{HOME}/.bun/install/global/node_modules/opencode/bin/opencode", "bun_global", "Bun"),
        (f"{HOME}/.pyenv/versions/3.11.4/bin/python3", "pyenv", "pyenv"),
        (f"{HOME}/.pyenv/shims/python3", "pyenv_shim", "pyenv"),
        (f"{HOME}/.local/share/uv/tools/ruff/bin/ruff", "uv_tool", "uv"),
        (f"{HOME}/.local/pipx/venvs/black/bin/black", "pipx", "pipx"),
        (f"{HOME}/.nvm/versions/node/v20.11.0/bin/node", "nvm", "nvm"),
        (f"{HOME}/.volta/bin/node", "volta", "Volta"),
        ("/Library/Frameworks/Python.framework/Versions/3.12/bin/python3", "python_framework", "python.org"),
        ("/Library/Developer/CommandLineTools/usr/bin/clang", "apple_toolchain", "Apple"),
        ("/usr/bin/python3", "system", "Apple"),
        ("/sbin/ping", "system", "Apple"),
        ("/Applications/Some App.app/Contents/MacOS/tool", "app_bundle", None),
        ("/Users/tester/Downloads/tool-2.0/tool", "standalone", None),
    ],
)
def test_classify_names_the_manager(origin_module, entry, expected_kind, expected_manager):
    result = classify(origin_module, entry, home=HOME, hermes=HERMES)
    assert result.kind == expected_kind
    assert result.manager == expected_manager


def test_homebrew_package_name_is_the_formula(origin_module):
    result = classify(
        origin_module,
        "/opt/homebrew/Cellar/python@3.13/3.13.7/bin/python3.13",
        home=HOME,
        hermes=HERMES,
    )
    assert result.package == "python@3.13"
    assert result.verified is True
    assert "Cellar" in result.evidence


def test_scoped_npm_package_keeps_its_scope(origin_module):
    result = classify(
        origin_module,
        "/opt/homebrew/lib/node_modules/@openai/codex/bin/codex.js",
        home=HOME,
        hermes=HERMES,
    )
    assert result.package == "@openai/codex"


def test_standalone_is_not_claimed_as_verified(origin_module):
    result = classify(origin_module, "/Users/tester/Downloads/tool-2.0/tool", home=HOME, hermes=HERMES)
    assert result.verified is False
    assert "nothing identifies a package manager" in result.evidence


def test_hermes_tools_label_names_the_tool(origin_module):
    result = classify(
        origin_module,
        f"{HERMES}/tools/python-3.14.9-darwin/bin/python3",
        home=HOME,
        hermes=HERMES,
    )
    assert result.label == "a tool Hermes downloaded"
    assert result.package == "python-3.14.9-darwin"


def test_homebrew_symlink_is_named_by_its_cellar_target(origin_module):
    """The name on PATH is a symlink; the Cellar target is the evidence."""
    result = classify(
        origin_module,
        "/opt/homebrew/bin/python3",
        canonical="/opt/homebrew/Cellar/python@3.15/3.15.2/bin/python3.15",
        home=HOME,
        hermes=HERMES,
    )
    assert result.kind == "homebrew_formula"
    assert result.package == "python@3.15"


def test_uv_tool_wins_over_its_shared_interpreter(origin_module):
    """A uv tool's bin is a symlink into uv's shared python, which owns nothing."""
    result = classify(
        origin_module,
        f"{HOME}/.local/share/uv/tools/skill-lens-cli/bin/python3",
        canonical=f"{HOME}/.local/share/uv/python/cpython-3.12.14/bin/python3.12",
        home=HOME,
        hermes=HERMES,
    )
    assert result.kind == "uv_tool"
    assert "skill-lens-cli" in result.label
    assert "resolves to" in result.evidence


def test_hermes_venv_reports_the_environment_and_the_resolution(origin_module):
    entry = f"{HERMES}/installs/abc/environments/def/venv/bin/python3"
    real = f"{HERMES}/tools/python-3.14.9-darwin/bin/python3"
    result = classify(origin_module, entry, canonical=real, home=HOME, hermes=HERMES)
    assert result.kind == "hermes_managed"
    assert result.label == "a Hermes plugin environment"
    assert "resolves to" in result.evidence


def test_classify_is_stable_without_a_canonical(origin_module):
    result = classify(origin_module, "/usr/bin/git", home=HOME, hermes=HERMES)
    assert result.kind == "system"


# --------------------------------------------------------------------------- #
# Architecture


def macho(path: Path, cpu: int, magic: int = 0xFEEDFACF) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<I", magic) + struct.pack("<I", cpu) + b"\x00" * 32)
    path.chmod(0o755)
    return path


def test_binary_arch_reads_arm64(origin_module, tmp_path):
    path = macho(tmp_path / "tool", 0x0100000C)
    assert origin_module.binary_arch(str(path)) == "arm64"


def test_binary_arch_reads_x86_64(origin_module, tmp_path):
    path = macho(tmp_path / "tool", 0x01000007)
    assert origin_module.binary_arch(str(path)) == "x86_64"


def test_binary_arch_reads_universal(origin_module, tmp_path):
    path = tmp_path / "tool"
    path.write_bytes(b"\xca\xfe\xba\xbe" + b"\x00" * 32)
    assert origin_module.binary_arch(str(path)) == "universal"


def test_binary_arch_reads_a_script(origin_module, tmp_path):
    path = tmp_path / "tool"
    path.write_text("#!/bin/sh\necho hi\n")
    assert origin_module.binary_arch(str(path)) == "script"


def test_binary_arch_reads_elf(origin_module, tmp_path):
    path = tmp_path / "tool"
    path.write_bytes(b"\x7fELF" + b"\x00" * 32)
    assert origin_module.binary_arch(str(path)) == "elf"


def test_binary_arch_unknown_for_junk(origin_module, tmp_path):
    path = tmp_path / "tool"
    path.write_bytes(b"just some text")
    assert origin_module.binary_arch(str(path)) == "unknown"


def test_binary_arch_unknown_when_unreadable(origin_module, tmp_path):
    assert origin_module.binary_arch(str(tmp_path / "missing")) == "unknown"


def test_arch_warning_explains_rosetta(origin_module):
    note = origin_module.arch_warning("x86_64", host="arm64")
    assert note is not None and "Rosetta" in note


def test_arch_warning_says_nothing_when_native(origin_module):
    assert origin_module.arch_warning("arm64", host="arm64") is None
    assert origin_module.arch_warning("universal", host="arm64") is None
    assert origin_module.arch_warning("script", host="arm64") is None


def test_arch_warning_flags_arm_binary_on_intel(origin_module):
    note = origin_module.arch_warning("arm64", host="x86_64")
    assert note is not None and "cannot run natively" in note


def test_host_arch_is_a_real_answer(origin_module):
    assert origin_module.host_arch() in {"arm64", "x86_64"} or origin_module.host_arch()
