"""Version parsing, comparison, and the bounded probe runner."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from conftest import write_exe, write_file


# --------------------------------------------------------------------------- #
# Parsing real banner strings


@pytest.mark.parametrize(
    "banner,expected",
    [
        ("Python 3.9.6", "3.9.6"),
        ("Python 3.13.1", "3.13.1"),
        ("v20.11.0", "20.11.0"),
        ("node v26.12.1", "26.12.1"),
        ("git version 2.39.3 (Apple Git-145)", "2.39.3"),
        ("go version go1.22.1 darwin/arm64", "1.22.1"),
        ('openjdk version "17.0.9" 2023-10-17', "17.0.9"),
        ("ruby 3.3.0p0 (2023-12-25 revision 5124f9ac75)", "3.3.0"),
        ("npm 10.2.4", "10.2.4"),
        ("2.0.1-beta.3", "2.0.1-beta.3"),
        ("Python 3.12.0a4", "3.12.0a4"),
        ("claude 1.0.60 (Claude Code)", "1.0.60"),
        ("Homebrew 4.3.2", "4.3.2"),
    ],
)
def test_parse_version_text_reads_real_banners(versions, banner, expected):
    parsed = versions.parse_version_text(banner)
    assert parsed is not None, banner
    assert parsed.text == expected


@pytest.mark.parametrize(
    "text",
    ["", "no version here", "ready", "version unknown", "1", "v", "abc.def"],
)
def test_parse_version_text_rejects_non_versions(versions, text):
    assert versions.parse_version_text(text) is None


def test_parse_version_text_takes_the_first_version(versions):
    parsed = versions.parse_version_text("Tool 4.2.0, engine 9.9.9")
    assert parsed is not None and parsed.text == "4.2.0"


def test_parse_version_text_records_prerelease(versions):
    parsed = versions.parse_version_text("Python 3.12.0a4")
    assert parsed is not None
    assert parsed.prerelease.startswith("a")
    assert parsed.numbers == (3, 12, 0)


# --------------------------------------------------------------------------- #
# Comparison


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("3.9.2", "3.13.1", -1),
        ("3.13.1", "3.9.2", 1),
        ("3.14.9", "3.14.9", 0),
        ("3.12.0", "3.12.0a4", 1),
        ("3.12.0a4", "3.12.0", -1),
        ("1.2", "1.2.0", 0),
        ("20.11.0", "18.19.0", 1),
        ("4.3.2", "4.4.0", -1),
    ],
)
def test_compare_versions(versions, left, right, expected):
    assert versions.compare_versions(left, right) == expected


@pytest.mark.parametrize(
    "left,right",
    [
        ("2023.10.17", "3.12.0"),   # a date against a semantic version
        ("1.2", "1.2.3.4"),         # different depths
        ("nonsense", "3.12.0"),
        ("3.12.0", "nonsense"),
    ],
)
def test_compare_versions_refuses_what_it_cannot_order(versions, left, right):
    assert versions.compare_versions(left, right) is None


# --------------------------------------------------------------------------- #
# Text cleaning


def test_clean_text_strips_ansi_and_collapses(versions):
    raw = "\x1b[32mPython 3.9.2\x1b[0m\r\n\nsecond line"
    assert versions.clean_text(raw) == "Python 3.9.2 | second line"


def test_clean_text_caps_length(versions):
    assert len(versions.clean_text("x" * 900)) == 400


# --------------------------------------------------------------------------- #
# The bounded runner


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group semantics")
def test_run_bounded_captures_output(versions, tmp_path):
    script = write_exe(tmp_path / "hello", body="#!/bin/sh\necho hello\n")
    result = versions.run_bounded([str(script)], timeout=3, env=versions.probe_environment(""))
    assert result.exit_code == 0
    assert result.stdout.strip() == b"hello"
    assert result.timed_out is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group semantics")
def test_run_bounded_times_out_and_kills(versions, tmp_path):
    script = write_exe(tmp_path / "slow", body="#!/bin/sh\nsleep 30\n")
    started = time.monotonic()
    result = versions.run_bounded([str(script)], timeout=0.4, env=versions.probe_environment(""))
    elapsed = time.monotonic() - started
    assert result.timed_out is True
    assert elapsed < 5


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group semantics")
def test_run_bounded_caps_output(versions, tmp_path):
    script = write_exe(
        tmp_path / "chatty",
        body="#!/bin/sh\ni=0\nwhile [ $i -lt 4000 ]; do printf 'aaaaaaaaaa'; i=$((i+1)); done\n",
    )
    result = versions.run_bounded(
        [str(script)], timeout=5, env=versions.probe_environment(""), limit=1024
    )
    assert len(result.stdout) <= 1024
    assert result.truncated is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group semantics")
def test_probe_environment_hides_secrets(versions, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "also-secret")
    script = write_exe(
        tmp_path / "envdump",
        body='#!/bin/sh\necho "key=$OPENAI_API_KEY other=$ANTHROPIC_API_KEY"\n',
    )
    result = versions.run_bounded(
        [str(script)], timeout=3, env=versions.probe_environment("/usr/bin:/bin")
    )
    assert b"sk-should-not-leak" not in result.stdout
    assert b"also-secret" not in result.stdout
    assert result.stdout.strip() == b"key= other="


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group semantics")
def test_probe_runs_in_the_filesystem_root(versions, tmp_path):
    script = write_exe(tmp_path / "pwd", body="#!/bin/sh\npwd\n")
    result = versions.run_bounded([str(script)], timeout=3, env=versions.probe_environment(""))
    assert result.stdout.strip() == b"/"


def test_run_bounded_reports_missing_binary(versions, tmp_path):
    result = versions.run_bounded(
        [str(tmp_path / "ghost")], timeout=3, env=versions.probe_environment("")
    )
    assert result.error is not None
    assert result.error.startswith("os_error")


# --------------------------------------------------------------------------- #
# One probe


def test_probe_reads_a_version(versions, tmp_path):
    script = write_exe(tmp_path / "python3", version="3.9.2")
    probe = versions.probe(str(script), tool="python3", timeout=3, path_value="/usr/bin:/bin")
    assert probe.ok is True
    assert probe.version == "3.9.2"
    assert probe.argv == ("--version",)
    assert probe.error is None


def test_probe_uses_the_tools_own_flag(versions, tmp_path):
    script = write_exe(
        tmp_path / "go", body='#!/bin/sh\nif [ "$1" = "version" ]; then echo "go version go1.22.1"; fi\n'
    )
    probe = versions.probe(str(script), tool="go", timeout=3, path_value="")
    assert probe.ok is True
    assert probe.version == "1.22.1"
    assert probe.argv == ("version",)


def test_probe_reads_stderr_too(versions, tmp_path):
    script = write_exe(
        tmp_path / "java",
        body='#!/bin/sh\necho \'openjdk version "17.0.9"\' >&2\n',
    )
    probe = versions.probe(str(script), tool="java", timeout=3, path_value="")
    assert probe.ok is True
    assert probe.version == "17.0.9"
    assert probe.stream == "stderr"


def test_probe_reports_silence(versions, tmp_path):
    script = write_exe(tmp_path / "quiet", body="#!/bin/sh\nexit 0\n")
    probe = versions.probe(str(script), tool="quiet", timeout=3, path_value="")
    assert probe.ok is False
    assert probe.error == "no_output"
    assert "nothing at all" in probe.error_hint


def test_probe_reports_missing_version_text(versions, tmp_path):
    script = write_exe(tmp_path / "junk", body="#!/bin/sh\necho 'try --help'\n")
    probe = versions.probe(str(script), tool="junk", timeout=3, path_value="")
    assert probe.ok is False
    assert probe.error == "no_version_text"


def test_probe_refuses_a_non_executable(versions, tmp_path):
    plain = write_file(tmp_path / "tool")
    probe = versions.probe(str(plain), tool="tool", timeout=3, path_value="")
    assert probe.ok is False
    assert probe.error == "not_executable"


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group semantics")
def test_probe_reports_timeout(versions, tmp_path):
    script = write_exe(tmp_path / "sleepy", body="#!/bin/sh\nsleep 30\n")
    probe = versions.probe(str(script), tool="sleepy", timeout=0.4, path_value="")
    assert probe.ok is False
    assert probe.timed_out is True
    assert probe.error == "timeout"


def test_probe_dict_is_json_safe(versions, tmp_path):
    script = write_exe(tmp_path / "python3", version="3.9.2")
    probe = versions.probe(str(script), timeout=3, path_value="")
    payload = probe.as_dict()
    assert payload["ok"] is True
    assert payload["version"] == "3.9.2"
    assert isinstance(payload["command"], list)
