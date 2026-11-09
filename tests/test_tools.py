"""The tool handlers: what the model sees, and what they refuse to do."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from conftest import snapshot, write_exe, write_file


def call(tools, arguments):
    raw = tools.which_copy(arguments)
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


def scan(tools, arguments):
    return json.loads(tools.which_copy_scan(arguments))


@pytest.fixture
def messy(sandbox, monkeypatch):
    """A three-copy PATH: old first, new second, a broken symlink, then a real dir."""
    old = write_exe(sandbox / "bin-2021" / "python3", version="3.9.2")
    new = write_exe(sandbox / "bin-2025" / "python3", version="3.13.1")
    broken = sandbox / "bin-broken" / "pip3"
    broken.parent.mkdir(parents=True)
    broken.symlink_to(sandbox / "nowhere" / "pip3")
    system = sandbox / "system"
    write_exe(system / "git", version="2.39.3")
    path = ":".join(
        [str(old.parent), str(new.parent), str(broken.parent), str(system)]
    )
    monkeypatch.setenv("PATH", path)
    return {"old": old, "new": new, "broken": broken, "system": system, "path": path}


# --------------------------------------------------------------------------- #
# One name


def test_which_copy_reports_the_winner(tools, messy):
    payload = call(tools, {"tool": "python3", "check_login_shell": False})
    assert payload["status"] == "ok"
    assert payload["mode"] == "name"
    assert payload["verdict"] == "shadowed_by_older"
    assert payload["severity"] == "trap"
    assert payload["winner"]["path_raw"] == str(messy["old"])
    assert payload["winner"]["version"] == "3.9.2"
    assert "older copy" in payload["headline"].lower()


def test_which_copy_summary_is_plain_language(tools, messy):
    payload = call(
        tools,
        {"tool": "python3", "check_login_shell": False, "include_off_path": False},
    )
    summary = payload["summary"]
    assert summary.startswith("python3 — Hermes's process PATH resolves to")
    assert "3.9.2" in summary and "3.13.1" in summary
    assert "Copies found (2)" in summary
    assert "wins in Hermes's PATH" in summary
    # The report must not imply it measured the PATH the terminal tool builds.
    assert "Scope: this is the PATH of the Hermes process." in summary


def test_which_copy_without_versions_starts_no_process(tools, messy, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("probe must not run when probe_versions is false")

    monkeypatch.setattr(tools.versions, "probe", explode)
    payload = call(
        tools,
        {
            "tool": "python3",
            "check_login_shell": False,
            "probe_versions": False,
            "include_off_path": False,
        },
    )
    assert payload["status"] == "ok"
    assert payload["probed"] is False
    assert payload["winner"]["version"] is None
    # Without versions there is no honest way to say which copy is older.
    assert payload["verdict"] == "multiple_copies"
    assert "Versions were not checked" in payload["summary"]


def test_which_copy_finds_a_dead_entry_in_front(tools, messy):
    payload = call(tools, {"tool": "pip3", "check_login_shell": False})
    assert payload["status"] == "ok"
    assert payload["winner"] is None
    assert payload["verdict"] in {"not_installed", "installed_not_on_path"}
    assert "broken symlink" in payload["summary"]


def test_which_copy_reports_a_missing_tool(tools, messy):
    payload = call(tools, {"tool": "definitely-not-installed", "check_login_shell": False})
    assert payload["status"] == "ok"
    assert payload["verdict"] == "not_installed"
    assert payload["winner"] is None


def test_which_copy_finds_off_path_copies(tools, messy, sandbox):
    hidden = write_exe(sandbox / "home" / ".local" / "bin" / "python3", version="3.12.0")
    payload = call(
        tools,
        {"tool": "python3", "check_login_shell": False, "include_off_path": True},
    )
    paths = [copy["path_raw"] for copy in payload["copies"]]
    assert str(hidden) in paths


def test_which_copy_can_skip_off_path_search(tools, messy, sandbox):
    write_exe(sandbox / "home" / ".local" / "bin" / "python3", version="3.12.0")
    payload = call(
        tools,
        {"tool": "python3", "check_login_shell": False, "include_off_path": False},
    )
    assert len(payload["copies"]) == 2


# --------------------------------------------------------------------------- #
# A supplied PATH


def test_which_copy_accepts_a_supplied_path(tools, sandbox, monkeypatch):
    old = write_exe(sandbox / "a" / "python3", version="3.9.2")
    new = write_exe(sandbox / "b" / "python3", version="3.13.1")
    hermes_python = write_exe(sandbox / "hermes-bin" / "python3", version="3.14.9")
    monkeypatch.setenv("PATH", str(hermes_python.parent))

    payload = call(
        tools,
        {
            "tool": "python3",
            "path": "%s:%s" % (old.parent, new.parent),
            "include_off_path": False,
        },
    )
    assert payload["mode"] == "custom-path"
    # The two copies are found and ordered, but neither is run: the PATH came
    # from the argument, so nothing in it is trusted to execute.
    assert payload["headline"]
    assert [copy["path_raw"] for copy in payload["copies"]] == [
        str(old),
        str(new),
    ]
    assert [copy["version"] for copy in payload["copies"]] == [None, None]
    assert [copy["probe"] for copy in payload["copies"]] == [None, None]
    assert all(copy["not_run"] for copy in payload["copies"])
    assert payload["verdict"] == "multiple_copies"
    assert "wins in the PATH you supplied" in payload["summary"]
    assert "Not run (2)" in payload["summary"]
    assert "Separately: Hermes's own process PATH resolves python3 to" in payload["summary"]
    assert str(hermes_python) in payload["summary"]
    # The machine's PATH is named only in the separate line, never as the answer.
    assert "Hermes's process PATH resolves to" not in payload["summary"]
    assert "the PATH you supplied" in payload["how_to_read"]


def test_a_supplied_path_report_reads_its_own_path_everywhere(tools, sandbox, monkeypatch):
    """No part of a supplied-PATH answer may describe a different PATH."""
    old = write_exe(sandbox / "a" / "python3", version="3.9.2")
    new = write_exe(sandbox / "b" / "python3", version="3.13.1")
    hermes_python = write_exe(sandbox / "hermes-bin" / "python3", version="3.14.9")
    monkeypatch.setenv("PATH", str(hermes_python.parent))

    payload = call(
        tools,
        {
            "tool": "python3",
            "path": "%s:%s" % (old.parent, new.parent),
            "include_off_path": False,
            "check_login_shell": False,
        },
    )
    assert "the PATH you supplied" in payload["how_to_read"]
    assert "Hermes process resolves" not in payload["how_to_read"]
    # The not-run reason must not claim a login shell was consulted.
    assert all("no login shell was read" in copy["not_run"] for copy in payload["copies"])
    assert "your login shell's PATH" not in payload["summary"]


def test_a_supplied_path_never_starts_a_probe(tools, sandbox, monkeypatch):
    """A PATH string is read, never executed — even with probing on."""
    def explode(*args, **kwargs):
        raise AssertionError("a supplied PATH must never be probed")

    old = write_exe(sandbox / "a" / "python3", version="3.9.2")
    write_exe(sandbox / "b" / "python3", version="3.13.1")
    # Hermes's own PATH has nothing to probe for this name either.
    monkeypatch.setenv("PATH", str(sandbox / "empty-bin"))
    monkeypatch.setattr(tools.versions, "probe", explode)
    payload = call(
        tools,
        {
            "tool": "python3",
            "path": "%s:%s" % (old.parent, sandbox / "b"),
            "include_off_path": False,
            "check_login_shell": False,
        },
    )
    assert payload["status"] == "ok"
    assert payload["probed"] is True
    assert [copy["version"] for copy in payload["copies"]] == [None, None]


def test_a_supplied_path_is_still_probed_where_a_real_path_has_the_same_file(
    tools, sandbox, monkeypatch
):
    """A copy that is also on a real PATH is not "found only" in the argument."""
    real = write_exe(sandbox / "hermes-bin" / "python3", version="3.14.9")
    monkeypatch.setenv("PATH", str(real.parent))

    payload = call(
        tools,
        {
            "tool": "python3",
            "path": "%s:%s" % (real.parent, sandbox / "somewhere-else"),
            "include_off_path": False,
            "check_login_shell": False,
        },
    )
    assert payload["copies"][0]["version"] == "3.14.9"
    assert payload["copies"][0]["not_run"] is None


def test_which_copy_rejects_an_empty_supplied_path(tools, sandbox):
    payload = call(tools, {"tool": "python3", "path": "   "})
    # Whitespace is not a PATH; the tool falls back to Hermes's own rather than
    # pretending the empty string is one.
    assert payload["status"] in {"ok", "no_path"}


def test_missing_tool_on_a_supplied_path_names_that_path(tools, sandbox):
    empty = sandbox / "empty"
    empty.mkdir()
    payload = call(
        tools,
        {"tool": "ghost-tool", "path": str(empty), "check_login_shell": False, "include_off_path": False},
    )
    assert payload["status"] == "ok"
    assert payload["mode"] == "custom-path"
    assert "not on the PATH you supplied" in payload["summary"]
    assert "not on Hermes's process PATH" not in payload["summary"]


# --------------------------------------------------------------------------- #
# An explicit file


def test_which_copy_describes_one_file(tools, messy):
    payload = call(tools, {"tool": str(messy["new"]), "check_login_shell": False})
    assert payload["status"] == "ok"
    assert payload["mode"] == "path"
    # Described, not executed: the version is reported as unknown here.
    assert payload["version"] is None
    assert payload["executed"] is None
    assert payload["not_run"]["reason"] == "named_by_caller"
    assert payload["is_path_winner"] is False
    assert "never reached" in payload["summary"]


def test_which_copy_describes_a_missing_file(tools, messy, sandbox):
    payload = call(tools, {"tool": str(sandbox / "ghost"), "check_login_shell": False})
    assert payload["status"] == "not_found"
    assert "nothing at" in payload["message"]


def test_path_mode_keeps_the_files_own_path(tools, messy):
    """`path` is the file that was asked about; the PATH lives under `path_source`."""
    payload = call(tools, {"tool": str(messy["new"]), "check_login_shell": False})
    assert payload["path"] == str(messy["new"])
    assert payload["path_source"]["kind"] == "hermes"
    assert payload["path_source"]["label"] == "Hermes's process PATH"


def test_path_mode_never_runs_the_named_file(tools, messy, monkeypatch):
    """The file is named in an argument, so it is described and left alone."""
    def explode(*args, **kwargs):
        raise AssertionError("a file named by the caller must never be executed")

    monkeypatch.setattr(tools.versions, "probe", explode)
    payload = call(tools, {"tool": str(messy["new"]), "check_login_shell": False})
    assert payload["status"] == "ok"
    assert payload["executed"] is None
    assert payload["version"] is None
    assert "does not run a file you name" in payload["not_run"]["text"]
    assert payload["not_run"]["run_it_yourself"] == "%s --version" % messy["new"]
    assert "Version check: not run" in payload["summary"]
    assert "never reached" in payload["summary"]


def test_path_mode_without_versions_still_says_it_did_not_run(tools, messy, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("probe must not run when probe_versions is false")

    monkeypatch.setattr(tools.versions, "probe", explode)
    payload = call(
        tools,
        {"tool": str(messy["new"]), "check_login_shell": False, "probe_versions": False},
    )
    assert payload["status"] == "ok"
    assert payload["executed"] is None
    assert payload["version"] is None
    assert "Version check: not run" in payload["summary"]


def test_a_supplied_path_without_versions_does_not_probe_hermes_copy(tools, sandbox, monkeypatch):
    """`probe_versions: false` starts no probe anywhere, including the Hermes line."""
    def explode(*args, **kwargs):
        raise AssertionError("probe must not run when probe_versions is false")

    monkeypatch.setattr(tools.versions, "probe", explode)
    hermes_python = write_exe(sandbox / "hermes-bin" / "python3", version="3.14.9")
    monkeypatch.setenv("PATH", str(hermes_python.parent))
    write_exe(sandbox / "a" / "python3", version="3.9.2")
    write_exe(sandbox / "b" / "python3", version="3.13.1")

    payload = call(
        tools,
        {
            "tool": "python3",
            "path": "%s:%s" % (sandbox / "a", sandbox / "b"),
            "probe_versions": False,
            "check_login_shell": False,
            "include_off_path": False,
        },
    )
    assert payload["status"] == "ok"
    assert payload["probed"] is False
    assert "version not checked" in payload["summary"]


def test_scan_names_the_tools_where_the_terminal_disagrees(tools, sandbox, monkeypatch):
    """End to end, through the same trimming the handler uses."""
    hermes_python = write_exe(sandbox / "hermes-bin" / "python3", version="3.14.9")
    shell_python = write_exe(sandbox / "shell-bin" / "python3", version="3.15.2")
    monkeypatch.setenv("PATH", str(hermes_python.parent))
    monkeypatch.setattr(
        tools.pathmodel,
        "login_shell_source",
        lambda *a, **k: tools.pathmodel.PathSource(
            kind=tools.pathmodel.LOGIN_SHELL_SOURCE,
            label="your login shell (zsh)",
            entries=(str(shell_python.parent),),
            raw=str(shell_python.parent),
            seeded=tools.pathmodel.SYSTEM_DEFAULT_PATH,
        ),
    )

    payload = scan(tools, {"tools": ["python3"], "include_off_path": False})

    assert "Your terminal resolves these differently: python3" in payload["summary"]
    entry = payload["tools"][0]
    assert entry["terminal"]["winner"]["path_raw"] == str(shell_python)
    assert entry["terminal"]["agrees_with_hermes"] is False
    assert "Scope:" in payload["summary"]


# --------------------------------------------------------------------------- #
# Bad input never raises


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"tool": ""},
        {"tool": "   "},
        {"tool": "x" * 500},
        {"tool": "bad\x00name"},
        {"tool": "line\nbreak"},
        {"tool": 12345},
        {"tool": ["python3"]},
        {"tool": "🎉"},
        {"tool": "python3", "check_login_shell": "not-a-bool"},
        None,
    ],
)
def test_which_copy_never_raises(tools, messy, arguments):
    raw = tools.which_copy(arguments)
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    assert "status" in payload


def test_which_copy_without_a_path_source(tools, monkeypatch):
    monkeypatch.setenv("PATH", "")
    payload = call(tools, {"tool": "python3", "check_login_shell": False})
    assert payload["status"] == "no_path"
    assert "no PATH" in payload["message"]


# --------------------------------------------------------------------------- #
# The sweep


def test_scan_checks_the_named_tools(tools, messy):
    payload = scan(
        tools,
        {
            "tools": ["python3", "git", "nothing-here"],
            "check_login_shell": False,
            "include_off_path": False,
        },
    )
    assert payload["status"] == "ok"
    assert payload["mode"] == "scan"
    assert [entry["tool"] for entry in payload["tools"]] == ["python3", "git", "nothing-here"]
    assert payload["counts"]["traps"] == 1
    assert payload["counts"]["installed"] == 2
    assert "python3" in payload["summary"] and "nothing-here" in payload["summary"]


def test_scan_accepts_a_comma_separated_string(tools, messy):
    payload = scan(tools, {"tools": "python3, git", "check_login_shell": False})
    assert [entry["tool"] for entry in payload["tools"]] == ["python3", "git"]


def test_scan_caps_the_tool_count(tools, messy):
    names = ["tool%d" % index for index in range(80)]
    payload = scan(tools, {"tools": names, "check_login_shell": False, "probe_versions": False})
    assert payload["status"] == "ok"
    assert len(payload["tools"]) == tools.known_tools.MAX_TOOLS


def test_scan_default_list_runs(tools, messy, monkeypatch):
    """The default sweep must not blow up on a machine full of absent tools."""
    monkeypatch.setattr(tools.pathmodel, "extra_roots", lambda *a, **k: [])
    payload = scan(
        tools,
        {"check_login_shell": False, "probe_versions": False, "include_off_path": False},
    )
    assert payload["status"] == "ok"
    assert payload["counts"]["tools"] == len(tools.known_tools.default_scan())
    assert payload["counts"]["installed"] == 2


def test_scan_can_sweep_a_supplied_path(tools, sandbox):
    write_exe(sandbox / "a" / "python3", version="3.9.2")
    write_exe(sandbox / "b" / "python3", version="3.13.1")
    payload = scan(
        tools,
        {
            "path": "%s:%s" % (sandbox / "a", sandbox / "b"),
            "tools": ["python3"],
            "include_off_path": False,
            "check_login_shell": False,
        },
    )
    assert payload["mode"] == "custom-path"
    assert payload["counts"]["traps"] == 0
    assert payload["tools"][0]["winner"]["version"] is None
    assert payload["tools"][0]["copies"] == 2
    assert "several copies, versions not checked" in payload["summary"]
    assert "Scope: this is the PATH you supplied" in payload["summary"]
    assert "Scope: the PATH of the Hermes process" not in payload["summary"]
    assert "the PATH you supplied" in payload["how_to_read"]


def test_scan_of_a_supplied_path_does_not_call_off_path_copies_uninstalled(
    tools, sandbox, monkeypatch
):
    """A tool the pasted PATH lacks may still exist on the machine."""
    elsewhere = write_exe(sandbox / "elsewhere" / "python3", version="3.13.1")
    empty = sandbox / "empty"
    empty.mkdir()
    monkeypatch.setattr(tools.pathmodel, "extra_roots", lambda *a, **k: [str(elsewhere.parent)])

    payload = scan(
        tools,
        {
            "path": str(empty),
            "tools": ["python3"],
            "check_login_shell": False,
            "probe_versions": False,
        },
    )
    assert "Not in the PATH you supplied: python3" in payload["summary"]
    assert "Not installed: python3" not in payload["summary"]
    texts = [verdict["text"] for verdict in payload["tools"][0]["verdicts"]]
    assert any("installed outside the PATH you supplied" in text for text in texts)


def test_scan_without_a_path(tools, monkeypatch):
    monkeypatch.setenv("PATH", "")
    payload = scan(tools, {"check_login_shell": False})
    assert payload["status"] == "no_path"


# --------------------------------------------------------------------------- #
# What is never executed
#
# A prompt injected into a repository can put any string it likes into these
# arguments. The plugin describes what it finds and runs nothing the argument
# put there — that is the security boundary, so it is tested as an attack.


def _tripwire(path: Path, script: str = "3.9.2") -> Path:
    """An executable that leaves evidence when it is run."""
    marker = path.parent / "was-run"
    return write_exe(
        path,
        body="#!/bin/sh\ntouch %s\necho 'Python %s'\n" % (marker, script),
    )


def test_a_directory_named_in_path_cannot_get_its_copy_executed(tools, sandbox, monkeypatch):
    repo = sandbox / "injected-repo"
    copy = _tripwire(repo / "python3")
    monkeypatch.setenv("PATH", str(sandbox / "empty-bin"))

    payload = call(
        tools,
        {
            "tool": "python3",
            "path": str(repo),
            "include_off_path": False,
            "check_login_shell": False,
        },
    )

    assert payload["status"] == "ok"
    # Reported, in the right order, with its origin — and not run.
    assert payload["copies"][0]["path_raw"] == str(copy)
    assert payload["copies"][0]["version"] is None
    assert payload["copies"][0]["not_run"]
    assert not (repo / "was-run").exists(), "the repository's own script was executed"


@pytest.mark.skipif(os.name == "nt", reason="POSIX shebang semantics")
@pytest.mark.parametrize("handler", ["which_copy", "which_copy_scan"])
def test_supplied_path_cannot_hijack_a_trusted_scripts_interpreter(
    tools, sandbox, monkeypatch, handler
):
    """A trusted script's ``#!`` lookup must not resolve inside a supplied PATH.

    ``ProbeTrust`` only vouches for the script file itself. The kernel resolves
    its interpreter with the child PATH, so a caller-named repository placed
    before the trusted directory must not be able to run its own ``fakeinterp``.
    """
    repo = sandbox / "injected-repo"
    trusted = sandbox / "trusted-bin"
    machine = sandbox / "machine-bin"
    marker = repo / "was-run"

    # Redirection is a shell builtin: before the fix the child PATH holds only
    # the supplied directories, so a bare `touch` might not resolve and the
    # test would pass for the wrong reason. The decoy version distinguishes an
    # executed interpreter from a probe that merely failed.
    write_exe(
        repo / "fakeinterp",
        body="#!/bin/sh\n: > '%s'\necho 'Tool 9.9.9'\n" % marker,
    )
    write_exe(machine / "fakeinterp", body="#!/bin/sh\necho 'Tool 1.2.3'\n")
    target = write_exe(
        trusted / "wc-env-probe-target",
        body="#!/usr/bin/env fakeinterp\n",
    )

    monkeypatch.setenv(
        "PATH", os.pathsep.join((str(machine), str(trusted), "/usr/bin", "/bin"))
    )
    supplied_path = os.pathsep.join((str(repo), str(trusted)))

    base = {
        "path": supplied_path,
        "probe_versions": True,
        "check_login_shell": False,
        "include_off_path": False,
    }
    if handler == "which_copy":
        payload = call(tools, dict(base, tool="wc-env-probe-target"))
    else:
        payload = scan(tools, dict(base, tools=["wc-env-probe-target"]))

    assert payload["status"] == "ok"
    assert payload["mode"] == "custom-path"
    assert not marker.exists(), "the supplied PATH selected the probe's interpreter"

    if handler == "which_copy":
        copies = [copy for copy in payload["copies"] if copy["path_raw"] == str(target)]
        assert len(copies) == 1
        assert copies[0]["version"] == "1.2.3"
    else:
        winner = payload["tools"][0]["winner"]
        assert winner["path_raw"] == str(target)
        assert winner["version"] == "1.2.3"


def test_a_file_named_in_tool_cannot_get_itself_executed(tools, sandbox, monkeypatch):
    repo = sandbox / "injected-repo"
    file = _tripwire(repo / "setup")
    monkeypatch.setenv("PATH", str(sandbox / "empty-bin"))

    payload = call(tools, {"tool": str(file), "check_login_shell": False})

    assert payload["status"] == "ok"
    assert payload["not_run"]["reason"] == "named_by_caller"
    assert payload["version"] is None
    assert not (repo / "was-run").exists(), "a file named in the argument was executed"


def test_a_relative_path_entry_is_never_probed(tools, sandbox, monkeypatch):
    """``""`` in PATH means "wherever I am" — which can be the injected repo."""
    repo = sandbox / "injected-repo"
    copy = _tripwire(repo / "python3")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("PATH", ":".join(["", "/usr/bin", "/bin"]))

    payload = call(
        tools,
        {"tool": "python3", "check_login_shell": False, "include_off_path": False},
    )

    assert payload["copies"][0]["path_raw"] == str(copy)
    assert payload["copies"][0]["candidate"]["relative_path_entry"] is True
    assert payload["copies"][0]["not_run"]
    assert "relative or empty PATH entry" in payload["copies"][0]["not_run"]
    assert not (repo / "was-run").exists(), "a copy behind an empty PATH entry was executed"


def test_a_fixed_install_directory_is_still_probed(tools, sandbox, monkeypatch):
    """The other half of the rule: the usual install directories are run."""
    off_path = write_exe(sandbox / "home" / ".local" / "bin" / "python3", version="3.12.0")
    monkeypatch.setenv("PATH", str(sandbox / "empty-bin"))

    payload = call(
        tools,
        {"tool": "python3", "check_login_shell": False, "include_off_path": True},
    )

    found = [copy for copy in payload["copies"] if copy["path_raw"] == str(off_path)]
    assert found, "a copy in ~/.local/bin should be found"
    assert found[0]["version"] == "3.12.0"
    assert found[0]["not_run"] is None


# --------------------------------------------------------------------------- #
# Read-only, under any input


def test_both_tools_leave_the_filesystem_untouched(tools, messy, sandbox, monkeypatch):
    """The copies being inspected must not be touched, and nothing lands in cwd.

    A probed binary is free to write its own caches (CPython on macOS makes one
    under ``~/Library/Caches``); what must not happen is this plugin creating,
    editing, or deleting anything — least of all in the directory the user is
    working in.
    """
    inspected = [messy["old"].parent, messy["new"].parent, messy["system"]]
    before = {str(path): snapshot(path) for path in inspected}
    workdir = sandbox / "project"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    cwd_before = snapshot(workdir)

    call(tools, {"tool": "python3", "check_login_shell": False, "include_off_path": False})
    call(tools, {"tool": "pip3", "check_login_shell": False, "include_off_path": False})
    scan(
        tools,
        {
            "tools": ["python3", "git", "pip3"],
            "check_login_shell": False,
            "include_off_path": False,
        },
    )
    call(tools, {"tool": str(messy["old"]), "check_login_shell": False})

    assert {str(path): snapshot(path) for path in inspected} == before
    assert snapshot(workdir) == cwd_before


def test_a_probe_does_not_write_into_the_working_directory(tools, sandbox, monkeypatch):
    noisy = write_exe(
        sandbox / "bin" / "writetool",
        body="#!/bin/sh\necho 'Tool 1.0.0'\ntouch ./should-not-exist\n",
    )
    monkeypatch.setenv("PATH", "%s:/usr/bin:/bin" % noisy.parent)
    workdir = sandbox / "project"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    payload = call(
        tools, {"tool": "writetool", "check_login_shell": False, "include_off_path": False}
    )
    assert payload["winner"]["version"] == "1.0.0"
    assert not (workdir / "should-not-exist").exists()


def test_a_hanging_tool_does_not_hang_the_check(tools, sandbox, monkeypatch):
    write_exe(sandbox / "bin" / "sleepy", body="#!/bin/sh\nsleep 30\n")
    monkeypatch.setenv("PATH", "%s:/usr/bin:/bin" % (sandbox / "bin"))
    monkeypatch.setattr(tools, "SINGLE_PROBE_TIMEOUT_S", 0.4)
    monkeypatch.setattr(tools, "SINGLE_PROBE_BUDGET_S", 1.0)
    payload = call(
        tools, {"tool": "sleepy", "check_login_shell": False, "include_off_path": False}
    )
    assert payload["status"] == "ok"
    assert payload["verdict"] == "version_unknown"
    assert "time limit" in payload["summary"]


def test_the_handler_accepts_a_none_argument(tools, messy):
    assert json.loads(tools.which_copy_scan(None))["status"] == "ok"
