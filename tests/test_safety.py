"""The promises in the README, checked against the source.

This is a static audit, so it cannot prove safety — but it can catch the cheap
accidents: a stray network import, a write, a shell string, an eval.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted(
    path for path in ROOT.glob("*.py") if path.name not in {"conftest.py"}
)
SKILL_SOURCES = sorted((ROOT / "skills").rglob("*.md"))


def source_text() -> str:
    return "\n".join(path.read_text() for path in SOURCES)


def test_sources_were_found():
    assert len(SOURCES) >= 6


@pytest.mark.parametrize(
    "module",
    ["socket", "ssl", "urllib", "http.client", "requests", "ftplib", "telnetlib", "smtplib"],
)
def test_no_network_modules_are_imported(module):
    pattern = re.compile(r"^\s*(?:import|from)\s+%s\b" % re.escape(module), re.MULTILINE)
    assert not pattern.search(source_text()), module


def test_no_shell_is_ever_used():
    text = source_text()
    for needle in ("shell=True", "os.system", "os.popen", "subprocess.call(", "subprocess.getoutput"):
        assert needle not in text, needle


def test_no_dynamic_execution():
    text = source_text()
    for pattern in (r"(?<![\w.])eval\(", r"(?<![\w.])exec\(", r"__import__\(", r"(?<![\w.])compile\("):
        assert not re.search(pattern, text), pattern


def test_nothing_is_written_to_disk():
    text = source_text()
    for pattern in (
        r"open\([^)]*[\"'][wax]",
        r"\.write_text\(",
        r"\.write_bytes\(",
        r"\.mkdir\(",
        r"\.makedirs\(",
        r"os\.makedirs",
        r"\bshutil\.",
    ):
        assert not re.search(pattern, text), pattern


def test_nothing_is_deleted_or_moved():
    text = source_text()
    for pattern in (
        r"os\.remove\(",
        r"os\.unlink\(",
        r"os\.rename\(",
        r"os\.replace\(",
        r"os\.rmdir\(",
        r"os\.chmod\(",
        r"os\.chown\(",
        r"os\.symlink\(",
        r"os\.link\(",
        r"os\.utime\(",
        r"rm -rf",
    ):
        assert not re.search(pattern, text), pattern


def test_subprocess_is_confined_to_the_two_modules_that_need_it():
    offenders = []
    for path in SOURCES:
        if path.name in {"pathmodel.py", "versions.py"}:
            continue
        if re.search(r"^\s*import subprocess", path.read_text(), re.MULTILINE):
            offenders.append(path.name)
    assert offenders == []


def test_every_subprocess_call_is_a_list_not_a_string():
    """A string first argument is the shape that invites shell quoting bugs."""
    text = source_text()
    calls = re.findall(r"subprocess\.(?:run|Popen)\(\s*([^\n]*)", text)
    assert calls, "expected the two deliberate subprocess calls"
    for first_argument in calls:
        assert not first_argument.strip().startswith('"'), first_argument
        assert not first_argument.strip().startswith("'"), first_argument


def test_no_credential_store_is_read():
    text = source_text()
    for needle in ("auth.json", ".netrc", "keychain", "security find-generic-password", '".env"', "'.env'"):
        assert needle not in text, needle


def test_skill_files_do_not_promise_a_fix():
    text = "\n".join(path.read_text() for path in SKILL_SOURCES).lower()
    assert "never say you fixed" in text
    assert "read-only" in text or "only read" in text


def test_plugin_yaml_declares_no_python_dependencies():
    manifest = (ROOT / "plugin.yaml").read_text()
    assert "python_dependencies: []" in manifest
