# Which Copy

**Which copy of a tool is Hermes actually going to use?**

On a Mac the same command can exist five times over — a Homebrew formula, an npm
global install, a pyenv shim, a standalone download, and Hermes's own bundled
copy — and the name resolves to whichever one PATH reaches first. No warning,
no note, no nothing. You find out when the wrong version breaks something.

Which Copy answers that in Hermes chat, in plain language: which copy wins,
where it came from, what version it reports, and whether the situation is
healthy or a trap — an old copy shadowing a new one, a dead symlink sitting in
front, or Hermes quietly using its own bundle instead of yours.

It only **diagnoses**. Nothing is installed, moved, relinked, or edited; PATH is
never touched. Read-only, local, no network, no API key.

---

## The answer, on a real machine

Asked `which python3 will you use?` on an ordinary Mac (Homebrew, pyenv, uv, and
Hermes installed), Which Copy replies:

```text
python3 — Hermes runs $HERMES_HOME/tools/python-3.14.9+20261021-darwin-arm64/bin/python3

3.14.9 · a tool Hermes downloaded · PATH slot 6 of 41

⚠ An older copy of python3 wins: Hermes runs 3.14.9, and a newer copy never gets the chance.
    /opt/homebrew/bin/python3 — 3.15.2, Homebrew formula python@3.15, on PATH

! Your terminal and Hermes disagree: your shell (zsh) runs /opt/homebrew/bin/python3 (3.15.2) in a normal terminal, but Hermes runs $HERMES_HOME/tools/python-3.14.9+20261021-darwin-arm64/bin/python3.

• Hermes runs its own copy of python3 (a tool Hermes downloaded). Your copy at /opt/homebrew/bin/python3 is never used for this name.

Copies found (6):
  1. $HERMES_HOME/tools/python-3.14.9+20261021-darwin-arm64/bin/python3 — 3.14.9 · a tool Hermes downloaded  ← Hermes uses this copy (also named: $HERMES_HOME/installs/…/venv/bin/python3)
  2. /opt/homebrew/bin/python3 — 3.15.2 · Homebrew formula python@3.15  ← never reached
  3. /usr/bin/python3 — 3.9.6 · a macOS system copy  ← never reached
  4. $HERMES_HOME/tools/python-3.14.7+20260901-darwin-arm64/bin/python3 — 3.14.7 · a tool Hermes downloaded  ← off PATH entirely
  5. ~/.local/share/uv/tools/skill-lens-cli/bin/python3 — 3.12.14 · a uv tool environment (skill-lens-cli)  ← off PATH entirely
  6. ~/.local/share/uv/tools/trafilatura/bin/python3 — 3.14.7 · a uv tool environment (trafilatura)  ← off PATH entirely

PATH lists 3 directories more than once — only the first position counts.
In your login shell (zsh): python3 → /opt/homebrew/bin/python3 (3.15.2).
```

Six copies of Python. Three different answers depending on who you ask
(`which python3` in your shell, the Python your editor launches, the Python
Hermes spawns), and the *oldest of the six* would win in a normal terminal.
That is the class of problem this plugin exists to make visible.

And the sweep, on the same machine, in about one second:

```text
Checked 25 tools against Hermes's own PATH (41 entries).

1 trap · 5 warnings · 10 notes.

⚠ python3      3.14.9     $HERMES_HOME/tools/…/bin/python3   older copy wins; a newer one is installed
! java         ?          /usr/bin/java                      reported no version
! node         26.12.1    $HERMES_HOME/tools/…/bin/node      your terminal picks a different copy
! npm          12.0.2     $HERMES_HOME/tools/…/bin/npm       your terminal picks a different copy
! npx          12.0.2     $HERMES_HOME/tools/…/bin/npx       your terminal picks a different copy
! pnpm         ?          ~/.local/bin/pnpm                  reported no version
• grok         1.0.77     ~/.grok/bin/grok                   one file, several names
• hermes       0.23.0     $HERMES_HOME/…/.hermes/bin/hermes  your terminal picks a different copy
• pip3         26.2.2     $HERMES_HOME/tools/…/bin/pip3      your terminal picks a different copy
• python       3.14.9     $HERMES_HOME/tools/…/bin/python    one file, several names
✓ brew         7.0.12-176 /opt/homebrew/bin/brew
✓ codex        0.167.0    ~/.local/bin/codex
✓ gh           2.103.3    /opt/homebrew/bin/gh
✓ git          2.54.0     /usr/bin/git
✓ opencode     2.2.6      ~/.opencode/bin/opencode
✓ pipx         1.18.11    /opt/homebrew/bin/pipx
✓ ruby         2.6.10     /usr/bin/ruby
✓ rustc        1.99.1     ~/.cargo/bin/rustc
✓ uv           0.13.7     ~/.local/bin/uv

Not installed: bun, claude, gemini, aider, cursor-agent, go
```

---

## Install

```bash
hermes plugins install Hazem-Samak/hermes-which-copy --yes-deps --enable
```

No Python dependencies — it is standard library only. Like any plugin, its tools
appear in the next Hermes session (restart the app, or `hermes gateway restart`
from a normal terminal, if the tool does not show up in the current one).

Then just ask:

> which python3 will you use?
>
> is anything on my PATH shadowed?
>
> which claude will you run?

## The two tools

| Tool | What it answers |
| --- | --- |
| `which_copy(tool)` | One name. The winning copy, its version and origin, every other copy found (on and off PATH), and a verdict. Also accepts an absolute path, and an optional `path` to check a *different* PATH string. |
| `which_copy_scan(tools?)` | The usual AI tools — `python3`, `python`, `node`, `npm`, `npx`, `bun`, `pnpm`, `uv`, `pip3`, `pipx`, `git`, `gh`, `brew`, `hermes`, `claude`, `codex`, `opencode`, `gemini`, `grok`, `aider`, `cursor-agent`, `rustc`, `go`, `ruby`, `java` — or any list you pass. One line per tool, worst first. |

Both are read-only. `probe_versions: false` makes either one a pure filesystem
answer that starts no process at all.

## The 90-second demo

A deliberately messy PATH: three copies of `python3`, oldest first, two of
`claude`, and a broken `pip3` symlink in front of everything.

```bash
git clone https://github.com/Hazem-Samak/hermes-which-copy
cd hermes-which-copy
bash demo/run-demo.sh
```

`demo/setup.sh` writes the mess to `~/which-copy-demo` (nothing else on the
machine is touched) and `run-demo.sh` asks Hermes the question. The stubs in the
demo only lie about `--version`; every other argument is handed to the real
interpreter, so a demo PATH can never break your shell.

What it shows, in the order to record it:

1. `which -a python3` in that shell → the 2021 copy, 3.9.2, first.
2. *"Which python3 will you use? Then check the same name against this messy
   PATH: …/bin-2021:…/bin-2025:…/bin-broken:…"* → two answers. First the one for
   the PATH you supplied, and then the line that reframes the whole question:

```text
python3 — wins in the PATH you supplied: ~/which-copy-demo/bin-2021/python3

3.9.2 · a standalone copy in bin-2021 · PATH slot 1 of 6

⚠ An older copy of python3 wins: the name resolves to 3.9.2, and a newer copy never gets the chance.
    ~/which-copy-demo/bin-2025/python3 — 3.13.1, a standalone copy in bin-2025, on PATH
    /usr/bin/python3 — 3.9.6, a macOS system copy, on PATH

Copies found (3):
  1. ~/which-copy-demo/bin-2021/python3 — 3.9.2 · a standalone copy in bin-2021  ← wins here
  2. ~/which-copy-demo/bin-2025/python3 — 3.13.1 · a standalone copy in bin-2025  ← never reached
  3. /usr/bin/python3 — 3.9.6 · a macOS system copy  ← never reached

Separately: this is not the PATH Hermes runs with. For python3, Hermes itself would run $HERMES_HOME/tools/python-3.14.9+20261021-darwin-arm64/bin/python3 (3.14.9).
```

3. *"And check the whole environment."* → the sweep, one trap and the rest clean.

The last line is the part people do not expect: Hermes does not use your shell's
PATH at all. It builds its own at startup from your login shell plus the
directories it manages, which is why the answer to "which python?" has three
different correct answers on one machine.

## What the verdicts mean

| Verdict | Severity | Meaning |
| --- | --- | --- |
| `shadowed_by_older` | trap | The copy that wins is older than another copy on this machine. The newer one never runs. |
| `winner_cannot_run` | trap | The winning file cannot execute here — an Intel-only binary on Apple silicon, for instance. |
| `skipped_dead_entries` | warning | A broken symlink or non-executable file sits earlier in PATH. The shell silently skips it, but `which` and your expectations do not. |
| `version_unknown` | warning | The winner answered the version check with nothing usable, so it may not even be the tool you think it is. |
| `hermes_vs_terminal` | warning / note | Your login shell resolves the name to a different file. Warning when the versions differ, note when they do not. |
| `multiple_copies` | note / warning | Several separate copies are installed: same version (note), or versions that cannot honestly be ordered (warning). |
| `hermes_managed_winner` | note | Hermes runs its own copy of this tool, not yours. Deliberate on Hermes's part — worth knowing. |
| `installed_not_on_path` | note | Copies exist, but nothing on PATH can reach them. |
| `not_installed` | note / warning | Nothing usable on PATH — a warning when something *looks* installed but cannot run. |
| `ok_aliases` | note | Several PATH names, one file. Nothing to shadow. |
| `ok_single` | ok | One usable copy, nothing behind it. |

## How it decides

**Two PATHs, never one.** A GUI-launched app has a useless inherited PATH, and
Hermes rebuilds its own at startup — so "the PATH" is not a single fact. Which
Copy resolves both:

- **Hermes's own PATH** — the environment of the running Hermes process, which is
  what anything Hermes spawns inherits. This is the default answer.
- **Your login shell's PATH** — captured by running your real login shell
  (`-l -i`) and reading an `env -0` dump between sentinels, bounded to 3 seconds.
  Output is captured only; your shell's startup files are never sourced into
  Hermes. If it fails or times out, the report says so instead of inventing a
  PATH.

**Copy inspection is done with `lstat` + `stat`,** so a broken symlink is
reported as broken rather than skipped, a directory named like the tool is
reported as a directory, and a file without execute permission is reported as
one. Six bytes of the target decide `script` / `arm64` / `x86_64` /
`universal` / `elf`, because an Intel-only tool on Apple silicon is its own trap.

**Provenance is path evidence, not a guess.** Each copy is classified from what
its path actually says: a Homebrew `Cellar` directory names the formula,
`Caskroom` the cask, a `lib/node_modules` tree the npm package (including the
`@scope`), pyenv's `versions/`, uv's `tools/`, pipx's `venvs/`, nvm's
`versions/node/`, a `.app/Contents/`, a `$HERMES_HOME` subdirectory. Anything
that matches no known layout is called a **standalone copy in <directory>** and
marked unverified — because "I do not know" is the honest answer.

**Versions are asked, not inferred.** The discovered binary is run with its
version flag — argv only, never a shell — with:

- a 3-second deadline per probe and a shared budget for a sweep;
- its own process group, killed as a group on timeout;
- output capped at 8 KB and truncated rather than buffered;
- a **stripped environment**: PATH, `HOME`, a locale, `TERM=dumb`. The probed
  program never sees `OPENAI_API_KEY` or anything else from Hermes's
  environment;
- `cwd=/`, so a tool that writes "next to itself" fails instead of littering
  your project.

**And it refuses to overstate.** Two version strings that were never meant to be
compared (a date version against a semantic one, or schemes with different
depths) are reported as *"cannot be ordered"* rather than sorted by whichever
number looks bigger. A tool that prints no version is "reported no version", not
guessed from its filename.

## Safety and privacy

- **No network calls.** No API key, no telemetry, no update check. The only
  processes started are your login shell (to read its PATH) and the copies being
  asked their version.
- **No writes.** It creates, edits, deletes, moves and relinks nothing — not your
  files, not PATH, not the copies it inspects. The test suite asserts this
  against a directory tree before and after every tool call. (A probed program is
  free to touch its own caches — CPython on macOS makes one under
  `~/Library/Caches` — that is the tool's business, not this plugin's.)
- **No credentials.** It never reads `.env`, `auth.json`, a keychain, or another
  tool's login, and it strips the environment it hands to a probed binary.
- **No shell strings.** Every subprocess is an argv list; `shell=True` does not
  appear anywhere in the source, and neither does `eval`/`exec`.
- **Nothing is fixed for you.** No `brew uninstall`, no PATH advice with commands
  baked in. The report tells you what is true and leaves the decision to you.

## Limits, stated plainly

- **macOS and Linux.** The login-shell probe is POSIX; on Windows the plugin
  would need a different environment source and is untested there.
- **It describes the PATH it can see.** If Hermes was launched by an unusual
  supervisor with its own PATH, the report describes *that* PATH — truthfully,
  with the entries listed.
- **A hostile binary is still a binary.** Probes run without a shell and without
  your secrets, but they do execute the discovered file. If you would rather
  execute nothing, pass `probe_versions: false`; the report then says versions
  were not checked instead of guessing.
- **`PATH` has no precedence between a symlink and its target.** Which Copy
  reports both — the name and what it resolves to — because "it is a Homebrew
  formula" and "the name lives in `/opt/homebrew/bin`" are both true and people
  ask about each.
- **Version ordering is textual and conservative.** `3.9.2` < `3.13.1` is
  arithmetic on version components, not a claim about which release is better.

## Development

```bash
python -m pytest tests -q        # 211 tests, no fixtures to download
hermes plugins doctor . --ci     # real loader, real contracts
hermes plugins validate .        # the catalog admission gate
```

The suite covers symlinked, broken, looped, non-executable and directory
candidates; PATH parsing including empty and repeated slots; login-shell capture
and its timeout/error paths; provenance for every manager layout; version
parsing against real banner strings and the cases where comparison must be
refused; every verdict including the ones that only appear when Hermes's copy
wins; the read-only guarantee; and a static audit of the source for network
imports, shell strings, writes and deletes.

## License

MIT © Hazem Samak
