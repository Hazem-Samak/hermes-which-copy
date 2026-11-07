"""Shared fixtures: load the plugin the way Hermes does, and build fake trees.

The plugin directory is not a valid Python identifier ("hermes-which-copy"), so
it is loaded as a package with ``submodule_search_locations`` — exactly what the
Hermes plugin loader does. That keeps the tests exercising the real relative
imports instead of a rewritten copy.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Iterable

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "which_copy_plugin"
SUBMODULES = ("schemas", "known_tools", "origin", "pathmodel", "verdicts", "versions", "tools")

if PACKAGE not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    # The plugin imports its own modules inside register(), so load them here
    # for the fixtures below. This is also what makes the fixtures independent
    # of whether register() ran.
    for name in SUBMODULES:
        importlib.import_module("%s.%s" % (PACKAGE, name))


@pytest.fixture(scope="session")
def plugin():
    return sys.modules[PACKAGE]


@pytest.fixture(scope="session")
def pathmodel(plugin):
    return plugin.pathmodel


@pytest.fixture(scope="session")
def versions(plugin):
    return plugin.versions


@pytest.fixture(scope="session")
def origin_module(plugin):
    return plugin.origin


@pytest.fixture(scope="session")
def verdicts(plugin):
    return plugin.verdicts


@pytest.fixture(scope="session")
def tools(plugin):
    return plugin.tools


# --------------------------------------------------------------------------- #
# Builders


def write_exe(path: Path, version: str | None = None, body: str | None = None) -> Path:
    """Write an executable stub. With ``version`` it answers --version like a tool."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if body is None:
        body = "#!/bin/sh\necho 'Stub %s'\n"
        if version is not None:
            body = '#!/bin/sh\nif [ "$1" = "--version" ]; then echo "Tool %s"; exit 0; fi\nexit 0\n' % version
    path.write_text(body)
    path.chmod(0o755)
    return path


def write_file(path: Path, text: str = "not a program\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o644)
    return path


def make_tree(root: Path, spec: dict[str, str]) -> list[str]:
    """Create executable stubs under ``root`` from {relative_path: version}."""
    entries = []
    for relative, version in spec.items():
        entries.append(str(write_exe(root / relative, version=version)))
    return entries


def snapshot(root: Path) -> list[tuple[str, int, int, str]]:
    """Everything a write would disturb: paths, sizes, mtimes, and content hashes."""
    import hashlib

    state = []
    for path in sorted(root.rglob("*")):
        try:
            info = path.lstat()
        except OSError:  # pragma: no cover - racing filesystem
            continue
        digest = ""
        if path.is_file() and not path.is_symlink():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        state.append((str(path.relative_to(root)), info.st_size, info.st_mtime_ns, digest))
    return state


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """An isolated HOME + HERMES_HOME, so nothing in the tests touches the real one."""
    home = tmp_path / "home"
    hermes = home / ".hermes"
    home.mkdir()
    hermes.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    return tmp_path
