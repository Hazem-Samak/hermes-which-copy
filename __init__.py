"""Which Copy — which copy of a tool is Hermes actually going to use?

Registers two tools and one bundled skill. Nothing heavy is imported at load
time and nothing runs at load time: the first tool call is what reads PATH. The
plugin only ever reads — it never installs, moves, relinks or edits anything.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TOOLSET = "diagnostics"


def register(ctx) -> None:
    # Imported here rather than at module level for two reasons. Nothing is
    # loaded until Hermes actually registers the plugin, and this directory's
    # name ("hermes-which-copy") is not a valid Python identifier: pytest
    # imports this file as a top-level module when it collects the repository
    # root, and a module-level relative import makes a plain `pytest` run fail
    # with "attempted relative import with no known parent package".
    from . import schemas, tools

    ctx.register_tool(
        name="which_copy",
        toolset=TOOLSET,
        schema=schemas.WHICH_COPY,
        handler=tools.which_copy,
        description="Which copy of a command Hermes will actually run, and why",
        emoji="🧭",
    )
    ctx.register_tool(
        name="which_copy_scan",
        toolset=TOOLSET,
        schema=schemas.WHICH_COPY_SCAN,
        handler=tools.which_copy_scan,
        description="Audit the whole PATH for shadowed or duplicate AI tool copies",
        emoji="🗺️",
    )

    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                try:
                    ctx.register_skill(child.name, skill_md)
                except Exception as exc:  # noqa: BLE001 - never fail the plugin for a skill
                    logger.warning("which-copy: could not register skill %s: %s", child.name, exc)
