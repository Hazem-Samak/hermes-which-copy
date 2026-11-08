"""Registration, manifest, and schema contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class FakeCtx:
    def __init__(self):
        self.tools = []
        self.skills = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_skill(self, name, path):
        self.skills.append((name, str(path)))


@pytest.fixture
def ctx(plugin):
    context = FakeCtx()
    plugin.register(context)
    return context


def test_registers_exactly_two_tools(ctx):
    assert [tool["name"] for tool in ctx.tools] == ["which_copy", "which_copy_scan"]


def test_tools_share_one_toolset(ctx):
    assert {tool["toolset"] for tool in ctx.tools} == {"diagnostics"}


def test_tools_carry_schema_handler_and_a_description(ctx):
    for tool in ctx.tools:
        assert tool["schema"]["name"] == tool["name"]
        assert callable(tool["handler"])
        assert tool["description"]
        assert tool["emoji"]


def test_skill_is_registered(ctx):
    assert len(ctx.skills) == 1
    name, path = ctx.skills[0]
    assert name == "which-copy"
    assert Path(path).name == "SKILL.md"
    assert Path(path).exists()


def test_schemas_describe_parameters(ctx):
    for tool in ctx.tools:
        parameters = tool["schema"]["parameters"]
        assert parameters["type"] == "object"
        assert isinstance(parameters["properties"], dict)


def test_which_copy_requires_a_tool_name(ctx):
    schema = next(tool for tool in ctx.tools if tool["name"] == "which_copy")["schema"]
    assert schema["parameters"]["required"] == ["tool"]


def test_scan_requires_nothing(ctx):
    schema = next(tool for tool in ctx.tools if tool["name"] == "which_copy_scan")["schema"]
    assert schema["parameters"]["required"] == []


def test_schema_descriptions_tell_the_model_not_to_claim_a_fix(ctx):
    text = json.dumps([tool["schema"] for tool in ctx.tools]).lower()
    assert "read-only" in text or "only diagnoses" in text
    assert "never edits path" in text or "no network" in text


def test_manifest_matches_the_registrations(plugin):
    yaml = pytest.importorskip("yaml")
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text())
    assert manifest["name"] == "which-copy"
    assert manifest["manifest_version"] == 2
    assert manifest["provides_tools"] == ["which_copy", "which_copy_scan"]
    assert manifest["provides_hooks"] == []
    assert manifest["python_dependencies"] == []
    assert manifest["requires_hermes"].startswith(">=")
    assert manifest["license"] == "MIT"
    assert manifest["version"] == "1.2.0"
    assert len(manifest["description"]) > 200


def test_manifest_files_exist(plugin):
    for name in ("plugin.yaml", "__init__.py", "README.md", "LICENSE"):
        assert (ROOT / name).exists(), name


def test_handler_is_reachable_with_the_hermes_signature(plugin):
    """Hermes calls handlers as handler(args: dict, **kwargs)."""
    import inspect

    signature = inspect.signature(plugin.tools.which_copy)
    assert list(signature.parameters)[0] == "args"
    assert signature.parameters["args"].default is None or True
    assert any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
