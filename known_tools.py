"""The tools worth checking, and how each one answers "what version?".

The default sweep is deliberately small: it is the set of names whose PATH
resolution Hermes users actually get surprised by — the runtimes and package
managers Hermes spawns, and the AI coding CLIs people install three times over.

``python`` and ``python3`` are listed separately on purpose. They are different
names to the shell and can resolve to different copies, which is the whole
subject of this plugin.
"""

from __future__ import annotations

from dataclasses import dataclass

CATEGORY_RUNTIME = "runtime"
CATEGORY_PACKAGES = "package-manager"
CATEGORY_AGENT = "coding-agent"
CATEGORY_TOOLS = "developer-tool"
CATEGORY_HERMES = "hermes"


@dataclass(frozen=True)
class KnownTool:
    name: str
    display: str
    category: str
    version_args: tuple[str, ...] = ("--version",)


KNOWN_TOOLS: tuple[KnownTool, ...] = (
    # Hermes itself, first: it is the one name Hermes obviously cares about.
    KnownTool("hermes", "Hermes", CATEGORY_HERMES),
    # Runtimes Hermes and its plugins spawn.
    KnownTool("python3", "Python 3", CATEGORY_RUNTIME),
    KnownTool("python", "Python", CATEGORY_RUNTIME),
    KnownTool("node", "Node.js", CATEGORY_RUNTIME),
    KnownTool("bun", "Bun", CATEGORY_RUNTIME),
    KnownTool("deno", "Deno", CATEGORY_RUNTIME),
    KnownTool("ruby", "Ruby", CATEGORY_RUNTIME),
    KnownTool("go", "Go", CATEGORY_RUNTIME, ("version",)),
    KnownTool("rustc", "Rust", CATEGORY_RUNTIME),
    KnownTool("java", "Java", CATEGORY_RUNTIME, ("-version",)),
    # Package managers.
    KnownTool("npm", "npm", CATEGORY_PACKAGES),
    KnownTool("npx", "npx", CATEGORY_PACKAGES),
    KnownTool("pnpm", "pnpm", CATEGORY_PACKAGES),
    KnownTool("yarn", "Yarn", CATEGORY_PACKAGES),
    KnownTool("uv", "uv", CATEGORY_PACKAGES),
    KnownTool("pip3", "pip 3", CATEGORY_PACKAGES),
    KnownTool("pip", "pip", CATEGORY_PACKAGES),
    KnownTool("pipx", "pipx", CATEGORY_PACKAGES),
    KnownTool("brew", "Homebrew", CATEGORY_PACKAGES),
    KnownTool("cargo", "Cargo", CATEGORY_PACKAGES),
    # The AI coding CLIs, which is where most of the duplicate installs live.
    KnownTool("claude", "Claude Code", CATEGORY_AGENT),
    KnownTool("codex", "Codex CLI", CATEGORY_AGENT),
    KnownTool("opencode", "OpenCode", CATEGORY_AGENT),
    KnownTool("gemini", "Gemini CLI", CATEGORY_AGENT),
    KnownTool("grok", "Grok CLI", CATEGORY_AGENT),
    KnownTool("aider", "Aider", CATEGORY_AGENT),
    KnownTool("cursor-agent", "Cursor Agent", CATEGORY_AGENT),
    KnownTool("qodercli", "Qoder CLI", CATEGORY_AGENT),
    KnownTool("agy", "Antigravity CLI", CATEGORY_AGENT),
    KnownTool("kimi", "Kimi CLI", CATEGORY_AGENT),
    KnownTool("vibe", "Mistral Vibe", CATEGORY_AGENT),
    KnownTool("pi", "Pi", CATEGORY_AGENT),
    KnownTool("omp", "Oh My Pi", CATEGORY_AGENT),
    KnownTool("copilot", "GitHub Copilot CLI", CATEGORY_AGENT),
    # Everyday tools whose shadowing hurts just as much.
    KnownTool("git", "git", CATEGORY_TOOLS),
    KnownTool("gh", "GitHub CLI", CATEGORY_TOOLS),
    KnownTool("docker", "Docker", CATEGORY_TOOLS),
    KnownTool("jq", "jq", CATEGORY_TOOLS),
    KnownTool("rg", "ripgrep", CATEGORY_TOOLS),
)

BY_NAME = {tool.name: tool for tool in KNOWN_TOOLS}

#: What ``which_copy_scan`` checks when the model does not name tools.
DEFAULT_SCAN: tuple[str, ...] = (
    "hermes",
    "python3",
    "python",
    "node",
    "npm",
    "npx",
    "bun",
    "pnpm",
    "uv",
    "pip3",
    "pipx",
    "git",
    "gh",
    "brew",
    "claude",
    "codex",
    "opencode",
    "gemini",
    "grok",
    "aider",
    "cursor-agent",
    "rustc",
    "go",
    "ruby",
    "java",
)

#: Hard ceiling, so a tool list from the model cannot become a 10-minute scan.
MAX_TOOLS = 40


def lookup(name: str) -> KnownTool:
    """The catalogue entry for a name, or a sensible default for an unknown one."""
    clean = (name or "").strip()
    known = BY_NAME.get(clean)
    if known:
        return known
    return KnownTool(clean, clean, "other")


def version_args(name: str) -> tuple[str, ...]:
    return lookup(name).version_args


def default_scan() -> tuple[str, ...]:
    return DEFAULT_SCAN
