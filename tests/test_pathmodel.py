"""PATH parsing, candidate inspection, and the two kinds of PATH source."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from conftest import write_exe, write_file


# --------------------------------------------------------------------------- #
# Splitting and expanding


def test_split_path_keeps_empty_entries(pathmodel):
    entries = pathmodel.split_path("/a::/b:")
    assert entries == ("/a", "", "/b", "")


def test_split_path_handles_missing(pathmodel):
    assert pathmodel.split_path(None) == ()
    assert pathmodel.split_path("") == ()


def test_expand_entry_treats_empty_as_cwd(pathmodel, tmp_path):
    assert pathmodel.expand_entry("", str(tmp_path)) == str(tmp_path)


def test_expand_entry_expands_tilde(pathmodel):
    home = os.path.expanduser("~")
    assert pathmodel.expand_entry("~/bin", "/") == os.path.join(home, "bin")


def test_expand_entry_resolves_relative_against_cwd(pathmodel, tmp_path):
    assert pathmodel.expand_entry("bin", str(tmp_path)) == os.path.join(str(tmp_path), "bin")


def test_expand_entry_leaves_absolute_alone(pathmodel):
    assert pathmodel.expand_entry("/usr/bin", "/tmp") == "/usr/bin"


# --------------------------------------------------------------------------- #
# Inspecting one candidate


def test_inspect_missing_returns_none(pathmodel, tmp_path):
    assert pathmodel.inspect(str(tmp_path / "nope")) is None


def test_inspect_executable_file(pathmodel, tmp_path):
    exe = write_exe(tmp_path / "bin" / "tool", version="1.0.0")
    candidate = pathmodel.inspect(str(exe), slot=0, directory=str(tmp_path / "bin"))
    assert candidate is not None
    assert candidate.kind == pathmodel.KIND_EXECUTABLE
    assert candidate.is_live is True
    assert candidate.canonical == os.path.realpath(str(exe))
    assert candidate.slot == 0


def test_inspect_file_without_execute_permission(pathmodel, tmp_path):
    plain = write_file(tmp_path / "bin" / "tool")
    candidate = pathmodel.inspect(str(plain))
    assert candidate is not None
    assert candidate.kind == pathmodel.KIND_NOT_EXECUTABLE
    assert candidate.is_live is False
    assert candidate.canonical is None


def test_inspect_directory(pathmodel, tmp_path):
    directory = tmp_path / "bin" / "tool"
    directory.mkdir(parents=True)
    candidate = pathmodel.inspect(str(directory))
    assert candidate is not None
    assert candidate.kind == pathmodel.KIND_DIRECTORY
    assert candidate.is_live is False


def test_inspect_symlink_resolves_target(pathmodel, tmp_path):
    real = write_exe(tmp_path / "real" / "python3.13", version="3.13.1")
    link = tmp_path / "bin" / "python3"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    candidate = pathmodel.inspect(str(link), slot=2, directory=str(tmp_path / "bin"))
    assert candidate is not None
    assert candidate.kind == pathmodel.KIND_EXECUTABLE_SYMLINK
    assert candidate.is_live is True
    assert candidate.canonical == os.path.realpath(str(real))
    assert candidate.chain[0] == str(link)
    assert candidate.chain[-1] == str(real)


def test_inspect_broken_symlink_is_not_live(pathmodel, tmp_path):
    link = tmp_path / "bin" / "pip3"
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp_path / "nowhere" / "pip3")
    candidate = pathmodel.inspect(str(link))
    assert candidate is not None
    assert candidate.kind == pathmodel.KIND_BROKEN_SYMLINK
    assert candidate.is_live is False
    assert "broken symlink" in candidate.kind_label


def test_inspect_symlink_to_directory(pathmodel, tmp_path):
    target = tmp_path / "somewhere"
    target.mkdir()
    link = tmp_path / "bin" / "tool"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    candidate = pathmodel.inspect(str(link))
    assert candidate is not None
    assert candidate.kind == pathmodel.KIND_SYMLINK_DIRECTORY
    assert candidate.is_live is False


def test_inspect_symlink_loop(pathmodel, tmp_path):
    first = tmp_path / "bin" / "a"
    second = tmp_path / "bin" / "b"
    first.parent.mkdir(parents=True)
    first.symlink_to(second)
    second.symlink_to(first)
    candidate = pathmodel.inspect(str(first))
    assert candidate is not None
    assert candidate.kind == pathmodel.KIND_SYMLINK_LOOP
    assert candidate.is_live is False


def test_symlink_chain_stops_on_cycle(pathmodel, tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.symlink_to(second)
    second.symlink_to(first)
    chain = pathmodel.symlink_chain(str(first))
    assert str(first) in chain and str(second) in chain
    assert len(chain) <= 3


# --------------------------------------------------------------------------- #
# Walking a PATH


def test_candidates_on_path_in_order(pathmodel, sandbox):
    first = sandbox / "one"
    second = sandbox / "two"
    write_exe(first / "tool", version="1.0.0")
    write_exe(second / "tool", version="2.0.0")
    source = pathmodel.custom_source("%s:%s" % (first, second))
    candidates = pathmodel.candidates_on_path("tool", source)
    assert [c.slot for c in candidates] == [0, 1]
    assert candidates[0].entry_path == str(first / "tool")
    assert candidates[1].entry_path == str(second / "tool")


def test_candidates_on_path_dedupes_repeated_slots(pathmodel, sandbox):
    first = sandbox / "one"
    write_exe(first / "tool", version="1.0.0")
    source = pathmodel.custom_source("%s:%s:%s" % (first, first, first))
    candidates = pathmodel.candidates_on_path("tool", source)
    assert len(candidates) == 1
    assert pathmodel.repeated_slot_count(source) == 2


def test_candidates_on_path_skips_absent_names(pathmodel, sandbox):
    empty = sandbox / "empty"
    empty.mkdir()
    source = pathmodel.custom_source(str(empty))
    assert pathmodel.candidates_on_path("ghost", source) == []


def test_candidates_on_path_unavailable_source(pathmodel):
    source = pathmodel.PathSource(kind="login-shell", label="shell", entries=(), available=False)
    assert pathmodel.candidates_on_path("tool", source) == []


def test_empty_path_entry_means_current_directory(pathmodel, sandbox, monkeypatch):
    workdir = sandbox / "work"
    workdir.mkdir()
    write_exe(workdir / "tool", version="1.0.0")
    monkeypatch.chdir(workdir)
    source = pathmodel.custom_source("")
    # A single empty entry is an empty string, which split_path drops as "no PATH";
    # a real PATH with an empty slot looks like ":/usr/bin".
    assert source.available is False
    source = pathmodel.custom_source(":/usr/bin")
    candidates = pathmodel.candidates_on_path("tool", source)
    assert candidates and candidates[0].entry_path == str(workdir / "tool")


# --------------------------------------------------------------------------- #
# Extra (off-PATH) roots


def test_extra_roots_only_existing(tmp_path, pathmodel):
    hermes = tmp_path / "hermes"
    home = tmp_path / "home"
    (hermes / "tools" / "python-3.14" / "bin").mkdir(parents=True)
    home.mkdir()
    roots = pathmodel.extra_roots(home=str(home), hermes=str(hermes))
    assert str(hermes / "tools" / "python-3.14" / "bin") in roots
    assert all(os.path.isdir(root) for root in roots)


def test_extra_roots_are_deduped(pathmodel, tmp_path):
    hermes = tmp_path / "hermes"
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    hermes.mkdir()
    roots = pathmodel.extra_roots(home=str(home), hermes=str(hermes))
    assert len(roots) == len(set(roots))


def test_candidates_off_path_skips_known_entries(pathmodel, sandbox):
    root = sandbox / "extra"
    exe = write_exe(root / "tool", version="9.9.9")
    found = pathmodel.candidates_off_path("tool", [str(root)], already=[str(exe)])
    assert found == []
    found = pathmodel.candidates_off_path("tool", [str(root)])
    assert len(found) == 1 and found[0].on_path is False


def test_candidates_off_path_ignores_dead_files(pathmodel, sandbox):
    root = sandbox / "extra"
    write_file(root / "tool")
    assert pathmodel.candidates_off_path("tool", [str(root)]) == []


# --------------------------------------------------------------------------- #
# PATH sources


def test_hermes_source_reads_the_environment(pathmodel):
    source = pathmodel.hermes_source("/usr/bin:/bin")
    assert source.kind == pathmodel.HERMES_SOURCE
    assert source.available is True
    assert source.entries == ("/usr/bin", "/bin")


def test_hermes_source_without_path_is_unavailable(pathmodel):
    source = pathmodel.hermes_source("")
    assert source.available is False
    assert "no PATH" in source.note


def test_custom_source_is_labelled_as_supplied(pathmodel):
    source = pathmodel.custom_source("/x:/y")
    assert source.kind == pathmodel.CUSTOM_SOURCE
    assert source.label == "the PATH you supplied"
    assert source.entries == ("/x", "/y")


def test_custom_source_empty_is_unavailable(pathmodel):
    source = pathmodel.custom_source("")
    assert source.available is False


def test_parse_environment_dump_ignores_banners(pathmodel):
    payload = (
        b"Welcome to zsh!\n"
        + pathmodel.LOGIN_SHELL_BEGIN.encode()
        + b"\n"
        + b"HOME=/Users/x\x00PATH=/a:/b\x00MULTI=one\ntwo\x00"
        + pathmodel.LOGIN_SHELL_END.encode()
        + b"\ntrailing noise\n"
    )
    parsed = pathmodel.parse_environment_dump(payload)
    assert parsed["PATH"] == "/a:/b"
    assert parsed["MULTI"] == "one\ntwo"
    assert "Welcome" not in parsed


def test_parse_environment_dump_without_sentinels(pathmodel):
    assert pathmodel.parse_environment_dump(b"PATH=/a:/b") == {}


def test_parse_environment_dump_without_end_marker(pathmodel):
    data = pathmodel.LOGIN_SHELL_BEGIN.encode() + b"\nPATH=/a\x00"
    assert pathmodel.parse_environment_dump(data) == {}


@pytest.mark.skipif(os.name == "nt", reason="login shell capture is POSIX only")
def test_login_shell_source_is_available_or_explains_itself(pathmodel):
    source = pathmodel.login_shell_source(timeout=3.0)
    assert source.kind == pathmodel.LOGIN_SHELL_SOURCE
    if source.available:
        assert source.entries
        assert source.raw
    else:
        assert source.note  # never a silent failure


def test_login_shell_source_reports_timeout(monkeypatch, pathmodel):
    import subprocess

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="zsh", timeout=3)

    monkeypatch.setattr(pathmodel.subprocess, "run", boom)
    source = pathmodel.login_shell_source()
    assert source.available is False
    assert source.degraded is True
    assert "did not answer" in source.note


def test_login_shell_source_reports_unstartable_shell(monkeypatch, pathmodel):
    def boom(*args, **kwargs):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(pathmodel.subprocess, "run", boom)
    source = pathmodel.login_shell_source()
    assert source.available is False
    assert "Could not start" in source.note


# --------------------------------------------------------------------------- #
# Display


def test_tidy_collapses_home_and_hermes_home(pathmodel, monkeypatch, tmp_path):
    home = tmp_path / "home"
    hermes = home / ".hermes"
    hermes.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    assert pathmodel.tidy(str(home / "bin" / "x")) == "~/bin/x"
    assert pathmodel.tidy(str(hermes / "bin" / "x")) == "$HERMES_HOME/bin/x"


def test_tidy_collapses_profile_install_hashes(pathmodel, monkeypatch, tmp_path):
    home = tmp_path / "home"
    hermes = home / ".hermes"
    deep = hermes / "installs" / ("a" * 32) / "environments" / ("b" * 32) / "venv" / "bin" / "python3"
    hermes.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    assert pathmodel.tidy(str(deep)) == "$HERMES_HOME/installs/…/venv/bin/python3"


def test_path_preview_marks_the_tail(pathmodel, sandbox):
    source = pathmodel.custom_source(":".join("/d%d" % i for i in range(12)))
    preview = pathmodel.path_preview(source)
    assert "(4 more)" in preview


def test_tidy_handles_none(pathmodel):
    assert pathmodel.tidy(None) == ""
