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


# --------------------------------------------------------------------------- #
# The demo scripts delete a directory: the guard has to hold


def _run_setup(demo_root: str, home: Path):
    import os
    import shutil
    import subprocess

    if shutil.which("bash") is None:
        pytest.skip("the demo scripts need bash")
    env = dict(os.environ)
    env["DEMO_ROOT"] = demo_root
    env["HOME"] = str(home)
    return subprocess.run(
        ["bash", str(ROOT / "demo" / "setup.sh")],
        cwd=str(home),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_demo_setup_refuses_the_filesystem_root(tmp_path):
    result = _run_setup("/", tmp_path)
    assert result.returncode != 0
    assert "Refusing" in result.stdout + result.stderr


def test_demo_setup_refuses_a_foreign_non_empty_directory(tmp_path):
    foreign = tmp_path / "not-the-demo"
    foreign.mkdir()
    keep = foreign / "keep.txt"
    keep.write_text("important\n")

    result = _run_setup(str(foreign), tmp_path)

    assert result.returncode != 0
    assert "Refusing" in result.stdout + result.stderr
    assert keep.read_text() == "important\n"


def test_demo_setup_still_builds_the_demo(tmp_path):
    import shutil

    if shutil.which("python3") is None:
        pytest.skip("the demo needs a python3 to delegate to")
    root = tmp_path / "which-copy-demo"

    result = _run_setup(str(root), tmp_path)

    assert result.returncode == 0, result.stderr
    assert (root / ".which-copy-demo").exists()
    assert (root / "bin-2021" / "python3").exists()


# --------------------------------------------------------------------------- #
# Wording: the docs claim what the code does


def test_readme_does_not_claim_the_process_path_is_what_commands_inherit():
    readme = (ROOT / "README.md").read_text()
    assert "what anything Hermes spawns inherits" not in readme
    assert "terminal tool" in readme


def test_schema_probe_versions_description_mentions_the_login_shell(plugin):
    description = plugin.schemas.WHICH_COPY["parameters"]["properties"]["probe_versions"][
        "description"
    ]
    assert "check_login_shell" in description
    assert "no process started at all" not in description


def test_schema_says_a_named_path_is_not_executed(plugin):
    """The model has to know that naming a file does not run it."""
    description = plugin.schemas.WHICH_COPY["parameters"]["properties"]["tool"]["description"]
    assert "never executed" in description or "not executed" in description
    assert "executed with its version flag" not in description


def test_schema_says_a_supplied_path_is_not_executed(plugin):
    for schema in (plugin.schemas.WHICH_COPY, plugin.schemas.WHICH_COPY_SCAN):
        description = schema["parameters"]["properties"]["path"]["description"]
        assert "never run" in description or "not run" in description


def test_manifest_description_does_not_claim_named_files_are_run(plugin):
    """Requirement from the review: the manifest must describe the new behaviour."""
    manifest = (ROOT / "plugin.yaml").read_text()
    assert "copy it found (argv only" not in manifest
    assert "Nothing named in a tool" in manifest
    assert "prompt-injected repository" in manifest
    # The supplied PATH may pick candidates, never the interpreter a probe uses.
    assert "never the raw supplied string" in " ".join(manifest.split())


def test_readme_says_nothing_named_in_an_argument_is_executed():
    readme = (ROOT / "README.md").read_text().lower()
    assert "nothing named in a tool call is ever run" in readme
    assert "including a file you name yourself" not in readme
    assert "a path named by the caller is executed" not in readme
    assert "executed with its version flag" not in readme
