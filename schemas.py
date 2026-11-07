"""Tool schemas — what the model reads before deciding to call them.

The descriptions carry the house rules: report the plain-language summary as it
is, never claim a fix was made, and never guess past what the check proved.
"""

WHICH_COPY = {
    "name": "which_copy",
    "description": (
        "Find out which copy of a command Hermes will actually run, and why — "
        "read-only, local, no network. On a Mac the same tool can be installed "
        "three times (Homebrew, npm, pyenv, a standalone download, Hermes's own "
        "bundle) and the name just resolves to whichever one PATH reaches first, "
        "silently. This tool resolves the name against TWO paths: the PATH Hermes "
        "itself runs with, and the PATH the user's own login shell builds for "
        "their terminal, and reports both when they disagree. For every copy it "
        "finds — on PATH and in well-known install locations — it says where the "
        "copy came from (Homebrew Cellar, npm global, pyenv, uv, pipx, nvm, "
        "Hermes's own directory, a standalone folder, the macOS system), what "
        "version it reports, and whether it can run on this machine (an "
        "Intel-only binary on Apple silicon is flagged). It then gives a verdict: "
        "healthy, an older copy shadowing a newer one, a dead PATH entry in front "
        "of the winner, Hermes using its own bundled copy instead of the user's, "
        "or the user's terminal and Hermes disagreeing. Use it whenever the user "
        "asks 'which python/node/claude will you use?', or when a tool misbehaves "
        "as if it were an older version, or when something is installed but seems "
        "ignored. It only diagnoses: it never edits PATH, never installs, "
        "uninstalls or moves anything. Returns JSON whose 'summary' field is a "
        "plain-language report — show that to the user verbatim inside a fenced "
        "code block, then add one or two sentences at most."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool": {
                "type": "string",
                "description": (
                    "The command name to check, exactly as the user would type it: "
                    '"python3", "node", "claude", "codex". Also accepts an absolute '
                    'path such as "/usr/bin/python3" to describe one specific file '
                    "and whether it is the copy Hermes would run."
                ),
            },
            "check_login_shell": {
                "type": "boolean",
                "description": (
                    "Also read the PATH the user's login shell builds, so the answer "
                    "can say 'your terminal runs a different copy'. Default true. "
                    "Set false to skip starting the shell (it is bounded to 3 "
                    "seconds and never sourced into Hermes)."
                ),
            },
            "probe_versions": {
                "type": "boolean",
                "description": (
                    "Ask each copy for its version by running it with --version, "
                    "with a 3-second limit, no shell and a stripped environment. "
                    "Default true. Set false for a pure filesystem answer with no "
                    "process started at all."
                ),
            },
            "include_off_path": {
                "type": "boolean",
                "description": (
                    "Also look in the usual install locations that are not on PATH "
                    "(~/.local/bin, ~/.pyenv, ~/.nvm, uv and pipx tool dirs, "
                    "Homebrew prefixes, Hermes's own tools directory) so copies the "
                    "user is not currently reaching are still reported. Default true."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Optional. Check this PATH string instead of Hermes's own — a "
                    "script's PATH, a cron job's, a colleague's paste, or a demo "
                    "setup. The report says plainly that it is the PATH supplied and "
                    "still states what Hermes itself would run for that name. Leave "
                    "it out to answer the real question."
                ),
            },
        },
        "required": ["tool"],
    },
}


WHICH_COPY_SCAN = {
    "name": "which_copy_scan",
    "description": (
        "Sweep the whole machine for the copies Hermes will actually run across "
        "the usual AI tools — python and python3, node, npm, npx, bun, pnpm, uv, "
        "pip, pipx, git, gh, brew, and the coding CLIs (claude, codex, opencode, "
        "gemini, grok, aider, cursor-agent), plus any other names given. For each "
        "name it reports the winning copy, its version, where it came from, and "
        "the single most useful thing to know: an older copy shadowing a newer "
        "one, a dead symlink in front of it, Hermes running its own bundled copy, "
        "several copies of the same version, or a name that is not installed. "
        "Read-only and local — no network, no API key, no installs, no changes to "
        "PATH. Use it when the user asks to 'check my environment', 'audit my "
        "PATH', 'is anything shadowed?', or before blaming a version mismatch on "
        "the wrong thing. Returns JSON whose 'summary' field is a plain-language "
        "table — show it verbatim inside a fenced code block, then name the one or "
        "two things worth acting on. Use which_copy on a single name for detail."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of command names to check instead of the default "
                    "set. A comma-separated string is accepted too. Maximum 40."
                ),
            },
            "check_login_shell": {
                "type": "boolean",
                "description": (
                    "Also compare against the PATH the user's login shell builds, "
                    "and name the tools where the terminal and Hermes disagree. "
                    "Default true."
                ),
            },
            "probe_versions": {
                "type": "boolean",
                "description": (
                    "Ask each winning copy for its version (bounded to 2 seconds "
                    "each, sharing a 15-second budget for the sweep). Default true. "
                    "With false the sweep is filesystem-only and finishes instantly, "
                    "but cannot tell an older copy from a newer one."
                ),
            },
            "include_off_path": {
                "type": "boolean",
                "description": (
                    "Also search the usual install locations that are not on PATH, "
                    "so a newer copy the user is not reaching still shows up. "
                    "Default true."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Optional. Sweep this PATH string instead of Hermes's own (a "
                    "script's, a cron job's, or a demo setup). The report says which "
                    "PATH it inspected."
                ),
            },
        },
        "required": [],
    },
}
