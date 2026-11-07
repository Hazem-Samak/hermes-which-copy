"""Verdicts: what the report says, and what it refuses to claim."""

from __future__ import annotations

import json
import os

import pytest

from conftest import write_exe, write_file


HOME = "/Users/tester"
HERMES = "/Users/tester/.hermes"


def make_finding(modules, path, *, version=None, error=None, slot=0, on_path=True, arch="script"):
    pathmodel, origin_module, verdicts, versions = modules
    candidate = pathmodel.inspect(str(path), slot=slot, on_path=on_path)
    assert candidate is not None, path
    origin = origin_module.classify(candidate.entry_path, candidate.canonical, home=HOME, hermes=HERMES)
    probe = None
    if version is not None:
        probe = versions.Probe(argv=("--version",), version=version, raw="Tool %s" % version, exit_code=0)
    elif error is not None:
        probe = versions.Probe(argv=("--version",), error=error)
    return verdicts.Finding(candidate=candidate, origin=origin, probe=probe, arch=arch)


@pytest.fixture
def build(plugin, pathmodel, origin_module, verdicts, versions):
    modules = (pathmodel, origin_module, verdicts, versions)

    def _build(path, **kwargs):
        return make_finding(modules, path, **kwargs)

    return _build


def analyse(verdicts, pathmodel, findings, off_path=(), source=None, shell=None, login_findings=(), **kwargs):
    source = source or pathmodel.custom_source(":".join(str(f.candidate.entry_path) for f in findings) or "/nowhere")
    return verdicts.analyze(
        "python3",
        source,
        findings,
        off_path,
        login_shell=shell,
        login_findings=login_findings,
        host="arm64",
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# One copy, nothing wrong


def test_single_copy_is_ok(build, verdicts, pathmodel, tmp_path):
    finding = build(write_exe(tmp_path / "bin" / "python3", version="3.13.1"), version="3.13.1")
    report = analyse(verdicts, pathmodel, [finding])
    assert report["verdict"] == "ok_single"
    assert report["severity"] == "ok"
    assert report["winner"]["version"] == "3.13.1"
    assert "Copies found (1)" in report["summary"]


def test_aliases_of_one_file_are_not_duplicates(build, verdicts, pathmodel, tmp_path):
    real = write_exe(tmp_path / "real" / "python3.13", version="3.13.1")
    first = tmp_path / "bin" / "python3"
    second = tmp_path / "bin" / "python"
    first.parent.mkdir(parents=True, exist_ok=True)
    first.symlink_to(real)
    second.symlink_to(real)
    findings = [
        build(first, version="3.13.1", slot=0),
        build(second, version="3.13.1", slot=1),
    ]
    report = analyse(verdicts, pathmodel, findings)
    codes = {item["code"] for item in report["verdicts"]}
    assert "ok_aliases" in codes
    assert report["severity"] == "note"
    assert "same file" in report["summary"]


# --------------------------------------------------------------------------- #
# The trap the plugin exists for


def test_older_copy_winning_is_a_trap(build, verdicts, pathmodel, tmp_path):
    old = write_exe(tmp_path / "bin-2021" / "python3", version="3.9.2")
    new = write_exe(tmp_path / "bin-2025" / "python3", version="3.13.1")
    findings = [build(old, version="3.9.2", slot=0), build(new, version="3.13.1", slot=1)]
    report = analyse(verdicts, pathmodel, findings)
    assert report["verdict"] == "shadowed_by_older"
    assert report["severity"] == "trap"
    assert "3.13.1" in report["summary"]
    assert report["verdicts"][0]["code"] == "shadowed_by_older" or any(
        item["code"] == "shadowed_by_older" for item in report["verdicts"]
    )
    assert "older copy" in report["headline"].lower()


def test_newer_copy_winning_is_not_a_trap(build, verdicts, pathmodel, tmp_path):
    new = write_exe(tmp_path / "bin-2025" / "python3", version="3.13.1")
    old = write_exe(tmp_path / "bin-2021" / "python3", version="3.9.2")
    findings = [build(new, version="3.13.1", slot=0), build(old, version="3.9.2", slot=1)]
    report = analyse(verdicts, pathmodel, findings)
    codes = {item["code"] for item in report["verdicts"]}
    assert "shadowed_by_older" not in codes
    assert report["severity"] != "trap"


def test_off_path_newer_copy_counts_as_shadowed(build, verdicts, pathmodel, tmp_path):
    old = write_exe(tmp_path / "bin" / "python3", version="3.9.2")
    homebrew = write_exe(tmp_path / "homebrew" / "python3", version="3.13.1")
    findings = [build(old, version="3.9.2", slot=0)]
    off = [build(homebrew, version="3.13.1", on_path=False)]
    report = analyse(verdicts, pathmodel, findings, off_path=off)
    assert report["verdict"] == "shadowed_by_older"
    assert "outside PATH" in report["summary"]


def test_uncomparable_versions_are_not_ordered(build, verdicts, pathmodel, tmp_path):
    one = write_exe(tmp_path / "a" / "python3", version="2023.10.17")
    two = write_exe(tmp_path / "b" / "python3", version="3.13.1")
    findings = [build(one, version="2023.10.17", slot=0), build(two, version="3.13.1", slot=1)]
    report = analyse(verdicts, pathmodel, findings)
    codes = {item["code"] for item in report["verdicts"]}
    assert "shadowed_by_older" not in codes
    assert "multiple_copies" in codes
    assert "cannot be ordered" in report["summary"]
    assert report["severity"] == "warning"


def test_same_version_twice_is_a_note_not_a_trap(build, verdicts, pathmodel, tmp_path):
    one = write_exe(tmp_path / "a" / "python3", version="3.13.1")
    two = write_exe(tmp_path / "b" / "python3", version="3.13.1")
    findings = [build(one, version="3.13.1", slot=0), build(two, version="3.13.1", slot=1)]
    report = analyse(verdicts, pathmodel, findings)
    codes = {item["code"] for item in report["verdicts"]}
    assert "multiple_copies" in codes
    assert report["severity"] == "note"
    assert "every one of them reports 3.13.1" in report["summary"]


def test_multiple_copies_with_an_unknown_version_are_not_called_equal(
    build, verdicts, pathmodel, tmp_path
):
    """A copy that never answered is not evidence that it is the same version."""
    known = write_exe(tmp_path / "a" / "python3", version="3.13.1")
    silent = write_exe(tmp_path / "b" / "python3", body="#!/bin/sh\nexit 0\n")
    findings = [
        build(known, version="3.13.1", slot=0),
        build(silent, error="no_output", slot=1),
    ]
    report = analyse(verdicts, pathmodel, findings)
    codes = {item["code"] for item in report["verdicts"]}
    assert "multiple_copies" in codes
    # It must not claim they match; it must say a copy stayed silent.
    assert "every one of them reports" not in report["summary"]
    assert "reported no version" in report["summary"]
    assert report["severity"] == "warning"


# --------------------------------------------------------------------------- #
# Dead entries and missing tools


def test_dead_entry_before_the_winner_is_a_warning(build, verdicts, pathmodel, tmp_path):
    broken = tmp_path / "bin-broken" / "python3"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.symlink_to(tmp_path / "nowhere" / "python3")
    working = write_exe(tmp_path / "bin" / "python3", version="3.13.1")
    findings = [build(broken, slot=0), build(working, version="3.13.1", slot=1)]
    report = analyse(verdicts, pathmodel, findings)
    assert report["verdict"] == "skipped_dead_entries"
    assert report["severity"] == "warning"
    assert "silently skips it" in report["summary"]
    assert "broken symlink" in report["summary"]
    assert report["winner"]["path_raw"] == str(working)


def test_nothing_executable_is_not_installed(build, verdicts, pathmodel, tmp_path):
    plain = write_file(tmp_path / "bin" / "python3")
    findings = [build(plain, slot=0)]
    report = analyse(verdicts, pathmodel, findings)
    assert report["verdict"] == "not_installed"
    assert report["winner"] is None
    assert "No usable python3" in report["summary"]
    assert "execute permission" in report["summary"]


def test_nothing_at_all_is_a_quiet_note(verdicts, pathmodel):
    report = verdicts.analyze("python3", pathmodel.custom_source("/nowhere"), [], [], host="arm64")
    assert report["verdict"] == "not_installed"
    assert report["severity"] == "note"
    assert "at all" in report["summary"]


def test_missing_on_a_supplied_path_is_not_attributed_to_hermes(verdicts, pathmodel):
    """The header must name the PATH that was searched, not Hermes's."""
    report = verdicts.analyze("ghost", pathmodel.custom_source("/nowhere"), [], [], host="arm64")
    assert "not on the PATH you supplied" in report["summary"]
    assert "Hermes's process PATH" not in report["summary"]


def test_off_path_only_says_installed_but_unreachable(build, verdicts, pathmodel, tmp_path):
    hidden = write_exe(tmp_path / "hidden" / "python3", version="3.13.1")
    report = analyse(
        verdicts,
        pathmodel,
        [],
        off_path=[build(hidden, version="3.13.1", on_path=False)],
    )
    codes = {item["code"] for item in report["verdicts"]}
    assert "installed_not_on_path" in codes
    assert "cannot run any of them by name" in report["summary"]


# --------------------------------------------------------------------------- #
# Hermes's own copy, and the terminal


def test_hermes_managed_winner_is_explained(build, verdicts, pathmodel, tmp_path):
    hermes_python = write_exe(
        tmp_path / "hermes" / "tools" / "python-3.14.9" / "bin" / "python3", version="3.14.9"
    )
    user_python = write_exe(tmp_path / "homebrew" / "python3", version="3.15.2")
    findings = [
        build(hermes_python, version="3.14.9", slot=0),
        build(user_python, version="3.15.2", slot=1),
    ]
    # Classify as Hermes-managed by pointing HERMES_HOME at the sandbox home.
    findings[0] = build(hermes_python, version="3.14.9", slot=0)
    report = verdicts.analyze("python3", pathmodel.custom_source(str(hermes_python.parent)), findings,
                              host="arm64")
    codes = {item["code"] for item in report["verdicts"]}
    assert "hermes_managed_winner" in codes or "shadowed_by_older" in codes
    assert report["summary"]


def test_terminal_disagreeing_is_a_warning(build, verdicts, pathmodel, tmp_path, monkeypatch):
    hermes_copy = write_exe(tmp_path / "hermes-bin" / "python3", version="3.14.9")
    shell_copy = write_exe(tmp_path / "shell-bin" / "python3", version="3.15.2")
    findings = [build(hermes_copy, version="3.14.9", slot=0)]
    login = [build(shell_copy, version="3.15.2", slot=0)]
    shell = pathmodel.PathSource(
        kind=pathmodel.LOGIN_SHELL_SOURCE,
        label="your login shell (zsh)",
        entries=(str(shell_copy.parent),),
        raw=str(shell_copy.parent),
    )
    report = analyse(verdicts, pathmodel, findings, shell=shell, login_findings=login)
    codes = {item["code"] for item in report["verdicts"]}
    assert "hermes_vs_terminal" in codes
    assert report["severity"] in {"warning", "trap"}
    assert "In your login shell (zsh): python3 →" in report["summary"]
    assert report["terminal"]["agrees_with_hermes"] is False


def test_terminal_dead_entry_is_not_called_the_terminal_winner(
    build, verdicts, pathmodel, tmp_path
):
    """A dead entry is skipped by the shell too, so it is not what the shell runs."""
    broken = tmp_path / "shell-broken" / "python3"
    broken.parent.mkdir(parents=True)
    broken.symlink_to(tmp_path / "nowhere" / "python3")
    shell_live = write_exe(tmp_path / "shell-bin" / "python3", version="3.15.2")
    hermes_copy = write_exe(tmp_path / "hermes-bin" / "python3", version="3.14.9")
    findings = [build(hermes_copy, version="3.14.9", slot=0)]
    login = [build(broken, slot=0), build(shell_live, version="3.15.2", slot=1)]
    shell = pathmodel.PathSource(
        kind=pathmodel.LOGIN_SHELL_SOURCE,
        label="your login shell (zsh)",
        entries=(str(broken.parent), str(shell_live.parent)),
        raw=":".join((str(broken.parent), str(shell_live.parent))),
        seeded="/usr/bin:/bin",
    )
    report = analyse(verdicts, pathmodel, findings, shell=shell, login_findings=login)

    assert report["terminal"]["winner"]["path_raw"] == str(shell_live)
    assert report["terminal"]["skipped"][0]["path_raw"] == str(broken)
    assert "skips it too" in report["summary"]
    assert "broken symlink" in report["summary"]
    # The comparison is against the copy the shell would run, not the dead entry.
    assert "broken" not in report["terminal"]["winner"]["path"]


def test_terminal_with_only_a_dead_entry_has_no_winner(build, verdicts, pathmodel, tmp_path):
    broken = tmp_path / "shell-broken" / "python3"
    broken.parent.mkdir(parents=True)
    broken.symlink_to(tmp_path / "nowhere" / "python3")
    hermes_copy = write_exe(tmp_path / "hermes-bin" / "python3", version="3.14.9")
    shell = pathmodel.PathSource(
        kind=pathmodel.LOGIN_SHELL_SOURCE,
        label="your login shell (zsh)",
        entries=(str(broken.parent),),
        raw=str(broken.parent),
    )
    report = analyse(
        verdicts,
        pathmodel,
        [build(hermes_copy, version="3.14.9", slot=0)],
        shell=shell,
        login_findings=[build(broken, slot=0)],
    )
    assert report["terminal"]["winner"] is None
    assert report["terminal"]["agrees_with_hermes"] is None
    assert "nothing usable is named python3" in report["summary"]
    assert "hermes_vs_terminal" not in {item["code"] for item in report["verdicts"]}


def test_terminal_agreeing_is_reported_as_agreement(build, verdicts, pathmodel, tmp_path):
    same = write_exe(tmp_path / "bin" / "python3", version="3.13.1")
    shell = pathmodel.PathSource(
        kind=pathmodel.LOGIN_SHELL_SOURCE,
        label="your login shell (zsh)",
        entries=(str(same.parent),),
        raw=str(same.parent),
    )
    report = analyse(
        verdicts,
        pathmodel,
        [build(same, version="3.13.1", slot=0)],
        shell=shell,
        login_findings=[build(same, version="3.13.1", slot=0)],
    )
    assert report["terminal"]["agrees_with_hermes"] is True


def test_terminal_agreeing_says_nothing(build, verdicts, pathmodel, tmp_path):
    same = write_exe(tmp_path / "bin" / "python3", version="3.13.1")
    findings = [build(same, version="3.13.1", slot=0)]
    login = [build(same, version="3.13.1", slot=0)]
    shell = pathmodel.PathSource(
        kind=pathmodel.LOGIN_SHELL_SOURCE,
        label="your login shell (zsh)",
        entries=(str(same.parent),),
        raw=str(same.parent),
    )
    report = analyse(verdicts, pathmodel, findings, shell=shell, login_findings=login)
    codes = {item["code"] for item in report["verdicts"]}
    assert "hermes_vs_terminal" not in codes


def test_unreadable_login_shell_explains_itself(build, verdicts, pathmodel, tmp_path):
    finding = build(write_exe(tmp_path / "bin" / "python3", version="3.13.1"), version="3.13.1")
    shell = pathmodel.PathSource(
        kind=pathmodel.LOGIN_SHELL_SOURCE,
        label="your login shell (zsh)",
        entries=(),
        available=False,
        degraded=True,
        note="Your shell did not answer within 3 s (a slow startup file), so its PATH was not read.",
    )
    report = analyse(verdicts, pathmodel, [finding], shell=shell)
    assert "did not answer" in report["summary"]


# --------------------------------------------------------------------------- #
# Unknown versions


def test_version_unknown_is_flagged(build, verdicts, pathmodel, tmp_path):
    finding = build(
        write_exe(tmp_path / "bin" / "python3", body="#!/bin/sh\necho 'not a version'\n"),
        error="no_version_text",
    )
    report = analyse(verdicts, pathmodel, [finding])
    assert report["verdict"] == "version_unknown"
    assert report["severity"] == "warning"
    assert "no version number" in report["summary"]


def test_architecture_trap_is_named(build, verdicts, pathmodel, tmp_path):
    finding = build(
        write_exe(tmp_path / "bin" / "python3", version="3.9.6"),
        version=None,
        error="os_error: Bad CPU type in executable",
        arch="x86_64",
    )
    report = analyse(verdicts, pathmodel, [finding])
    assert report["verdict"] == "winner_cannot_run"
    assert report["severity"] == "trap"
    assert "Rosetta" in report["summary"]


def test_cannot_run_does_not_claim_the_copy_runs(build, verdicts, pathmodel, tmp_path):
    """A binary that could not start must not be described as running under Rosetta."""
    finding = build(
        write_exe(tmp_path / "bin" / "python3", version="3.9.6"),
        version=None,
        error="os_error: Bad CPU type in executable",
        arch="x86_64",
    )
    report = analyse(verdicts, pathmodel, [finding])
    text = next(v["text"] for v in report["verdicts"] if v["code"] == "winner_cannot_run")
    assert "cannot run" in text
    assert "runs under Rosetta" not in text
    assert "needs Rosetta" in text


# --------------------------------------------------------------------------- #
# A supplied PATH


def test_supplied_path_is_labelled_as_supplied(build, verdicts, pathmodel, tmp_path):
    finding = build(write_exe(tmp_path / "bin" / "python3", version="3.9.2"), version="3.9.2")
    report = analyse(verdicts, pathmodel, [finding], source=pathmodel.custom_source(str(tmp_path / "bin")))
    assert report["path"]["kind"] == "custom"
    assert "wins in the PATH you supplied" in report["summary"]
    assert "wins here" in report["summary"]
    # It must not slide into claiming the Hermes copy for a PATH the caller gave.
    assert "Hermes's process PATH resolves to" not in report["summary"]


# --------------------------------------------------------------------------- #
# Report shape


def test_report_is_json_serialisable(build, verdicts, pathmodel, tmp_path):
    finding = build(write_exe(tmp_path / "bin" / "python3", version="3.9.2"), version="3.9.2")
    report = analyse(verdicts, pathmodel, [finding])
    json.dumps(report)  # raises if anything leaked a Path or a dataclass


def test_report_never_recommends_a_mutating_command(build, verdicts, pathmodel, tmp_path):
    old = write_exe(tmp_path / "a" / "python3", version="3.9.2")
    new = write_exe(tmp_path / "b" / "python3", version="3.13.1")
    report = analyse(
        verdicts,
        pathmodel,
        [build(old, version="3.9.2", slot=0), build(new, version="3.13.1", slot=1)],
    )
    lowered = report["summary"].lower()
    for phrase in ("brew install", "brew uninstall", "pip install", "npm install -g", "rm -rf"):
        assert phrase not in lowered


# --------------------------------------------------------------------------- #
# The sweep


def _slim(verdicts, pathmodel, findings, tool, **kwargs):
    report = verdicts.analyze(tool, pathmodel.custom_source("/x"), findings, host="arm64", **kwargs)
    return report


def test_scan_summary_counts_and_table(build, verdicts, pathmodel, tools, tmp_path):
    old = build(write_exe(tmp_path / "a" / "python3", version="3.9.2"), version="3.9.2")
    new = build(write_exe(tmp_path / "b" / "python3", version="3.13.1"), version="3.13.1")
    good = build(write_exe(tmp_path / "c" / "git", version="2.39.3"), version="2.39.3")

    shadowed = verdicts.analyze("python3", pathmodel.custom_source("/a:/b"), [old, new], host="arm64")
    clean = verdicts.analyze("git", pathmodel.custom_source("/c"), [good], host="arm64")
    missing = verdicts.analyze("codex", pathmodel.custom_source("/c"), [], host="arm64")

    slim = [tools_slim(tools, report) for report in (shadowed, clean, missing)]
    text = verdicts.scan_summary(slim, pathmodel.custom_source("/a:/b:/c"), None)
    assert "Checked 3 tools" in text
    assert "1 trap" in text
    assert "Not installed: codex" in text
    # traps are printed before clean tools
    assert text.index("python3") < text.index("git")
    assert "older copy wins" in text
    assert "Scope:" in text


def tools_slim(tools, report):
    """The scan handler's own trim, so this test cannot drift from production."""
    return tools._slim(report)


def test_scan_summary_notes_terminal_disagreement(build, verdicts, pathmodel, tools, tmp_path):
    hermes_copy = build(write_exe(tmp_path / "h" / "python3", version="3.14.9"), version="3.14.9")
    login_copy = build(write_exe(tmp_path / "s" / "python3", version="3.15.2"), version="3.15.2")
    shell = pathmodel.PathSource(
        kind=pathmodel.LOGIN_SHELL_SOURCE,
        label="your login shell (zsh)",
        entries=(str(login_copy.candidate.entry_path),),
        raw="x",
    )
    report = verdicts.analyze(
        "python3",
        pathmodel.custom_source("/h"),
        [hermes_copy],
        login_shell=shell,
        login_findings=[login_copy],
        host="arm64",
    )
    text = verdicts.scan_summary([tools_slim(tools, report)], pathmodel.custom_source("/h"), shell)
    assert "Your terminal resolves these differently: python3" in text


def test_scan_does_not_call_two_names_for_one_file_a_disagreement(
    build, verdicts, pathmodel, tools, tmp_path
):
    """Aliases of one file are agreement, not a terminal-vs-Hermes difference."""
    real = write_exe(tmp_path / "real" / "python3", version="3.13.1")
    hermes_name = tmp_path / "hermes-bin" / "python3"
    shell_name = tmp_path / "shell-bin" / "python3"
    hermes_name.parent.mkdir(parents=True)
    shell_name.parent.mkdir(parents=True)
    hermes_name.symlink_to(real)
    shell_name.symlink_to(real)
    shell = pathmodel.PathSource(
        kind=pathmodel.LOGIN_SHELL_SOURCE,
        label="your login shell (zsh)",
        entries=(str(shell_name.parent),),
        raw=str(shell_name.parent),
    )
    report = verdicts.analyze(
        "python3",
        pathmodel.custom_source(str(hermes_name.parent)),
        [build(hermes_name, version="3.13.1", slot=0)],
        login_shell=shell,
        login_findings=[build(shell_name, version="3.13.1", slot=0)],
        host="arm64",
    )
    assert report["terminal"]["agrees_with_hermes"] is True
    text = verdicts.scan_summary(
        [tools_slim(tools, report)], pathmodel.custom_source(str(hermes_name.parent)), shell
    )
    assert "resolves these differently" not in text


def test_scan_note_does_not_call_unorderable_copies_the_same(build, verdicts, pathmodel, tmp_path):
    """The one-line note repeats the verdict; it does not assume "same version"."""
    dated = build(write_exe(tmp_path / "a" / "python3", version="2023.10.17"), version="2023.10.17")
    semantic = build(write_exe(tmp_path / "b" / "python3", version="3.13.1"), version="3.13.1")
    report = verdicts.analyze(
        "python3", pathmodel.custom_source("/a:/b"), [dated, semantic], host="arm64"
    )
    note = verdicts._scan_note(report)
    assert "cannot be ordered" in note
    assert "same version" not in note
