# Which Copy

**Which copy of a tool is the Hermes process actually going to use?**

On a Mac the same command can exist five times over — a Homebrew formula, an npm
global install, a pyenv shim, a standalone download, and Hermes's own bundled
copy — and the name resolves to whichever one PATH reaches first. No warning,
no note, no nothing. You find out when the wrong version breaks something.

Which Copy answers that in Hermes chat, in plain language: which copy wins,
where it came from, what version it reports, and whether the situation is
healthy or a trap — an old copy shadowing a new one, a dead symlink sitting in
front, or Hermes preferring its own bundle over yours.

It only **diagnoses**. Nothing is installed, moved, relinked, or edited; PATH is
never touched; it writes no files and makes no network call. The one thing it
executes is a bounded version check of a copy that **this machine** put there —
Hermes's own PATH, your login shell's PATH, or a known install directory.
Nothing named in a tool call is ever run: a file you name, a copy that exists
only in a PATH string you pass in, and a copy behind a relative PATH entry are
all described with their version left unchecked. See
[Safety](#safety-and-privacy) — a prompt-injected repository is the reason.

---

## Which PATH is it talking about?

There are three, and they are not interchangeable:

| PATH | How it is read | What it answers |
| --- | --- | --- |
| **Hermes's process PATH** | `os.environ["PATH"]` of the process running Hermes | what a subprocess spawned with Hermes's own environment resolves — plugins, Python code, hooks |
| **Your login shell's PATH** | your real shell, started `-l -i` from the **system default** PATH, `env -0` between sentinels, 3-second limit | what a fresh Terminal window resolves |
| **Hermes's terminal tool** | *not measured* — the tool runs commands in a login shell and appends directories Hermes manages | what a command typed into Hermes's terminal resolves |

Which Copy reports the first two exactly, and **says in every report** that the
third exists and can differ. It does not pretend the process PATH is the PATH a
terminal command gets, and it does not invent a number for the third.

---

## The answer, on a real machine

Asked `which python3 will you use?` on an ordinary Mac (Homebrew, uv, and Hermes
installed), Which Copy replies:

```text
python3 — Hermes's process PATH resolves to $HERMES_HOME/tools/python-3.14.9+20261021-darwin-arm64/bin/python3

3.14.9 · a tool Hermes downloaded · PATH slot 6 of 41

⚠ An older copy of python3 wins: Hermes's process PATH picks 3.14.9, and a newer copy never gets the chance.
    /opt/homebrew/bin/python3 — 3.15.2, Homebrew formula python@3.15, on PATH

! Your terminal and Hermes disagree: your shell (zsh) runs /opt/homebrew/bin/python3 (3.15.2) in a normal terminal, but Hermes's process PATH picks $HERMES_HOME/tools/python-3.14.9+20261021-darwin-arm64/bin/python3.

• Hermes's process PATH picks its own copy of python3 (a tool Hermes downloaded). Your copy at /opt/homebrew/bin/python3 is never used for this name.

Copies found (6):
  1. $HERMES_HOME/tools/python-3.14.9+20261021-darwin-arm64/bin/python3 — 3.14.9 · a tool Hermes downloaded  ← wins in Hermes's PATH (also named: $HERMES_HOME/installs/…/venv/bin/python3)
  2. /opt/homebrew/bin/python3 — 3.15.2 · Homebrew formula python@3.15  ← never reached
  3. /usr/bin/python3 — 3.9.6 · a macOS system copy  ← never reached
  4. $HERMES_HOME/tools/python-3.14.7+20260901-darwin-arm64/bin/python3 — 3.14.7 · a tool Hermes downloaded  ← off PATH entirely
  5. ~/.local/share/uv/tools/skill-lens-cli/bin/python3 — 3.12.14 · a uv tool environment (skill-lens-cli)  ← off PATH entirely
  6. ~/.local/share/uv/tools/trafilatura/bin/python3 — 3.14.7 · a uv tool environment (trafilatura)  ← off PATH entirely

PATH lists 3 directories more than once — only the first position counts.
In your login shell (zsh): python3 → /opt/homebrew/bin/python3 (3.15.2).
That shell was started with the system default PATH (/usr/bin:/bin:/usr/sbin:/sbin) before its own startup files ran, so the entries above are the shell's doing.

Scope: this is the PATH of the Hermes process. A command run through Hermes's terminal tool gets a login shell whose PATH also gains directories Hermes adds (~/.local/bin, $HERMES_HOME/bin, Homebrew's defaults), so that shell can pick a different copy.
```

Six entries, five distinct files (the venv `python3` is a second name for the
same interpreter, so it is listed as an alias, not as another copy). Three
different answers depending on who you ask — and the one Hermes's own PATH
reaches is neither the newest (Homebrew's 3.15.2, which your terminal runs) nor
the oldest (the system's 3.9.6). That is the class of problem this plugin exists
to make visible.

And the sweep, on the same machine:

```text
Checked 25 tools against Hermes's process PATH (41 entries).

1 trap · 6 warnings · 10 notes.

⚠ python3      3.14.9     $HERMES_HOME/tools/…/bin/python3   older copy wins; a newer one is installed
! java         ?          /usr/bin/java                      reported no version
! node         26.12.1    $HERMES_HOME/tools/…/bin/node      your terminal picks a different copy
! npm          12.0.2     $HERMES_HOME/tools/…/bin/npm       your terminal picks a different copy
! npx          12.0.2     $HERMES_HOME/tools/…/bin/npx       your terminal picks a different copy
! pnpm         ?          ~/.local/bin/pnpm                  reported no version
! python       3.14.9     $HERMES_HOME/tools/…/bin/python    several copies, some not probed
• grok         1.0.77     ~/.grok/bin/grok                   one file, several names
• hermes       0.23.0     $HERMES_HOME/…/.hermes/bin/hermes  your terminal picks a different copy
• pip3         26.2.2     $HERMES_HOME/tools/…/bin/pip3      your terminal picks a different copy
• uv           0.13.7     ~/.local/bin/uv                    several copies, newest wins
✓ brew         7.0.12-176 /opt/homebrew/bin/brew
✓ codex        0.167.0    ~/.local/bin/codex
✓ gh           2.103.3    /opt/homebrew/bin/gh
✓ git          2.54.0     /usr/bin/git
✓ opencode     2.2.6      ~/.opencode/bin/opencode
✓ pipx         1.18.11    /opt/homebrew/bin/pipx
✓ ruby         2.6.10     /usr/bin/ruby
✓ rustc        1.99.1     ~/.cargo/bin/rustc

Not installed: bun, claude, gemini, aider, cursor-agent, go

Your terminal resolves these differently: hermes, python3, node, npm, npx, pip3. Use which_copy on one of them for the detail.

Scope: the PATH of the Hermes process. Hermes's terminal tool adds directories to its shell's PATH, so a command it runs can resolve a different copy.
```

`several copies, some not probed` is the honest answer for `python`: a sweep
caps how many copies it asks, and a copy nobody asked is not reported as
matching the others.

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
| `which_copy(tool)` | One name. The winning copy on the Hermes process PATH, its version and origin, every other copy found (on and off PATH), and a verdict. Also accepts an absolute path to describe one file. |
| `which_copy_scan(tools?)` | The usual AI tools — `python3`, `python`, `node`, `npm`, `npx`, `bun`, `pnpm`, `uv`, `pip3`, `pipx`, `git`, `gh`, `brew`, `hermes`, `claude`, `codex`, `opencode`, `gemini`, `grok`, `aider`, `cursor-agent`, `rustc`, `go`, `ruby`, `java` — or any list you pass. One line per tool, worst first. |

Neither installs, moves or edits anything, and neither runs a file you name.
`probe_versions: false` starts no version check at all; because the login-shell
check is on by default and does
start your shell, set `check_login_shell: false` as well for a call that starts
no process whatsoever.

## The 90-second demo

The strongest demo is the machine you are already on: ask *"which python3 will
you use?"* and you get the report above. To make the shadowing case reproducible
on a machine that has only one of everything, the repository ships a
deliberately messy PATH: three copies of `python3` oldest first, two of `claude`,
and a broken `pip3` symlink in front of everything.

```bash
git clone https://github.com/Hazem-Samak/hermes-which-copy
cd hermes-which-copy
bash demo/setup.sh        # builds ~/which-copy-demo, prints its PATH
```

`demo/setup.sh` writes the mess to `~/which-copy-demo` (nothing else on the
machine is touched). Both scripts share `demo/guard.sh`, which refuses to delete
`/`, your home directory, this repository, or any non-empty directory that is not
the demo — a typo in `DEMO_ROOT` cannot turn the demo into data loss. The stubs in
the demo only lie about `--version`; every other argument is handed to the real
interpreter.

What it shows, in the order to record it:

1. *"Which python3 will you use?"* → the report above: Hermes's own 3.14.9, the
   newer Homebrew 3.15.2 that never gets the chance, and a terminal that picks the
   other one.
2. *"Check my whole environment."* → the sweep above.
3. *"Which copy wins in this PATH? …/bin-2021:…/bin-2025:…/bin-broken:/usr/local/bin:/usr/bin:/bin"*
   → the copies in that PATH, in slot order, with the dead entry named:

```text
python3 — wins in the PATH you supplied: ~/which-copy-demo/bin-2021/python3

version not checked · a standalone copy in bin-2021 · PATH slot 1 of 6

! There are 3 separate copies of python3, and nothing here establishes that they are the same version: the winning copy has no version; 1 was not run.
    ~/which-copy-demo/bin-2021/python3 — version not checked
    ~/which-copy-demo/bin-2025/python3 — version not checked
    /usr/bin/python3 — 3.9.6

Copies found (3):
  1. ~/which-copy-demo/bin-2021/python3 — version not checked · a standalone copy in bin-2021  ← wins here
  2. ~/which-copy-demo/bin-2025/python3 — version not checked · a standalone copy in bin-2025  ← never reached
  3. /usr/bin/python3 — 3.9.6 · a macOS system copy  ← never reached

Not run (2): a copy is executed only when Hermes's PATH, your login shell's PATH or a known install directory put it there. A file you name, a copy found only in a PATH you pass in, and a copy behind a relative PATH entry are described here and left alone.

Scope: this is the PATH you supplied, not the one Hermes runs with. A command run through Hermes's terminal tool gets a login shell plus the directories Hermes adds, so neither PATH decides what that shell picks.

Separately: this is not the PATH Hermes's process runs with. For python3, Hermes's own PATH resolves to /opt/homebrew/bin/python3 (3.15.2).
```

Two things to say out loud about that report. It answers the question — which
copy wins in that PATH, and that the 2025 copy never gets there — without
pretending to have measured the other PATHs. And it **does not run the two copies
the PATH pointed at**: they came from a string in the conversation, and a string
in the conversation is not the machine. `/usr/bin/python3` does report a version,
because the machine's own PATH already contains it. That distinction is the whole
security story: a repository that tells an agent *"check this PATH for me"* cannot
get its own script executed.

The line that reframes everything is the last one: Hermes's own PATH is not your
shell's PATH. It is built when Hermes starts, which is why "which python?" has
three different correct answers on one machine — and why the tool names the one it
measured instead of calling it *"the PATH"*.

## What the verdicts mean

| Verdict | Severity | Meaning |
| --- | --- | --- |
| `shadowed_by_older` | trap | The copy that wins is older than another copy on this machine. The newer one never runs. |
| `winner_cannot_run` | trap | The winning file cannot execute here — an Intel-only binary on Apple silicon, for instance. |
| `skipped_dead_entries` | warning | A broken symlink or non-executable file sits earlier in PATH. The shell silently skips it, but `which` and your expectations do not. |
| `version_unknown` | warning | The winner answered the version check with nothing usable, so it may not even be the tool you think it is. |
| `hermes_vs_terminal` | warning / note | Your login shell resolves the name to a different file. Warning when both versions are known and differ, note otherwise. |
| `multiple_copies` | note / warning | Several separate copies are installed. The report says exactly which case it measured: every copy reports the same version (note), the winner is the newest (note), versions that cannot honestly be ordered (warning), copies that reported no version (warning), copies the sweep did not ask (warning), or copies this check refused to run (warning). |
| `hermes_managed_winner` | note | Hermes's own PATH picks its bundled copy, not yours. Deliberate on Hermes's part — worth knowing. |
| `installed_not_on_path` | note | Copies exist, but nothing on PATH can reach them. |
| `not_installed` | note / warning | Nothing usable on PATH — a warning when something *looks* installed but cannot run. |
| `ok_aliases` | note | Several PATH names, one file. Nothing to shadow. |
| `ok_single` | ok | One usable copy, nothing behind it. |

## How it decides

**Two PATHs read, a third named.** A GUI-launched app has a useless inherited
PATH and Hermes builds its own at startup, so "the PATH" is not a single fact.
Which Copy reads:

- **Hermes's process PATH** — `os.environ["PATH"]` of the running process. This
  is what a subprocess spawned with that environment resolves. It is *not* what
  a command typed into Hermes's terminal tool necessarily gets.
- **Your login shell's PATH** — captured by running your real login shell
  (`-l -i`) and reading an `env -0` dump between sentinels, bounded to 3 seconds.
  The shell is started with the **system default PATH**
  (`/usr/bin:/bin:/usr/sbin:/sbin`), not Hermes's, so every entry beyond that
  came from your own startup files; the report states the seed it used. Output is
  captured only; your shell's startup files are never sourced into Hermes. If it
  fails or times out, the report says so instead of inventing a PATH.

In both cases the winner is the first *usable* entry. A broken symlink or a file
without execute permission earlier in PATH is what the shell skips, so the
report calls it a dead entry in front of the winner — never "the copy your
terminal runs".

**Copy inspection is done with `lstat` + `stat`,** so a broken symlink is
reported as broken rather than skipped, a directory named like the tool is
reported as a directory, and a file without execute permission is reported as
one. The first bytes of the target decide `script` / `arm64` / `x86_64` /
`universal` / `elf`, because an Intel-only tool on Apple silicon is its own trap.

**Provenance is path evidence, not a guess.** Each copy is classified from what
its path actually says: a Homebrew `Cellar` directory names the formula,
`Caskroom` the cask, a `lib/node_modules` tree the npm package (including the
`@scope`), pyenv's `versions/`, uv's `tools/`, pipx's `venvs/`, nvm's
`versions/node/`, a `.app/Contents/`, a `$HERMES_HOME` subdirectory. Anything
that matches no known layout is called a **standalone copy in <directory>** and
marked unverified — because "I do not know" is the honest answer.

**Two names for one file are one copy.** Symlinks that resolve to the same file
are grouped as aliases ("also named: …") instead of being counted as duplicates.

**Versions are asked, not inferred — and only asked of copies the machine put
there.** Each discovered binary is run with its version flag — argv only, never a
shell — with:

- a 3-second deadline per probe, a shared budget for a sweep, and a cap on how
  many copies a sweep asks (copies it did not ask are reported as not probed);
- its own process group, killed as a group on timeout;
- output capped at 8 KB and truncated rather than buffered;
- a **stripped environment**: PATH, `HOME`, a locale, `TERM=dumb`, and
  color/pager settings. The probed program never sees `OPENAI_API_KEY` or
  anything else from Hermes's environment. The PATH it is given is the one it
  would run under — Hermes's for a copy found there, the shell's for a copy
  found in the login shell;
- `cwd=/`, so a tool that writes "next to itself" fails instead of littering
  your project.

**Only the machine gets to decide what runs.** A copy is executed only when the
directory that holds it is one of: an absolute entry on Hermes's process PATH, an
absolute entry on your login shell's PATH, or one of the fixed install
directories this plugin knows about (`~/.local/bin`, Homebrew's prefixes,
`$HERMES_HOME/bin`, the uv/pipx/pyenv/nvm trees, the macOS system). Nothing in a
tool call takes part in that decision, and a relative or empty PATH entry — `""`
or `.` in PATH, which resolves against whatever directory you happen to be in —
is never searched for a probe. So a repository that talks an agent into passing
`path: .` gets a report about its files, not an execution of them. The cost is
honest: copies that exist only in a PATH you paste in are reported with their
version unchecked.

**And it refuses to overstate.** Two version strings that were never meant to be
compared (a date version against a semantic one, or schemes with different
depths) are reported as *"cannot be ordered"* rather than sorted by whichever
number looks bigger. A copy that printed no version is "reported no version"; a
copy the sweep did not ask is "not asked"; a copy this check will not execute is
"not run", with the reason. None of them is presented as matching the winner.

## Safety and privacy

- **No network calls.** No API key, no telemetry, no update check.
- **No writes by this plugin.** It creates, edits, deletes, moves and relinks
  nothing — not your files, not PATH, not the copies it inspects. The test suite
  asserts this against a directory tree before and after every tool call.
- **What does run.** Your login shell (to read its PATH), and the version probe of
  a copy that the machine's own PATH, your login shell's PATH or a known install
  directory put there. A probed program is free to write its own files — CPython
  on macOS makes one under `~/Library/Caches` — that is the program's doing, not
  this plugin's.
- **What never runs: anything named in a tool call.** A path passed as `tool` is
  described, never executed — the report says so and prints the command you can
  run yourself. The same goes for a copy found only in a `path` string you pass
  in, and for a copy behind a relative or empty PATH entry. Naming a file, or
  pasting a PATH, is not consent to run what is in it; only the machine's own
  configuration grants that. Every copy that was left alone is listed under
  *"Not run"*, with the reason, and carries a `not_run` field in the JSON.
- **No credentials.** It never reads `.env`, `auth.json`, a keychain, or another
  tool's login, and it strips the environment it hands to a probed binary.
- **No shell strings.** Every subprocess is an argv list; `shell=True` does not
  appear anywhere in the source, and neither does `eval`/`exec`.
- **Nothing is fixed for you.** No `brew uninstall`, no PATH advice with commands
  baked in. The report tells you what is true and leaves the decision to you.

## Limits, stated plainly

- **macOS and Linux.** The login-shell probe is POSIX; on Windows the plugin
  would need a different environment source and is untested there.
- **The terminal tool's PATH is not measured.** Hermes's terminal tool runs a
  command in a login shell and appends directories it manages. Which Copy reads
  the two PATHs it can read exactly and says in every report that the third can
  differ — it does not guess at the composition.
- **Your login shell is started fresh.** A terminal opened from an already
  configured environment (a shell inside another shell, an IDE) may carry more
  entries than the captured PATH shows.
- **A pasted PATH is reported, not run.** Copies that exist only in a PATH you
  pass in come back with "version not checked" — that is deliberate, and no flag
  turns it off. If you want their versions, put that directory on your own PATH
  and ask again, or run the copy yourself. For an answer that starts no process at
  all, pass `probe_versions: false` and `check_login_shell: false`.
- **A name and its target are two facts, not one.** "The name lives in
  `/opt/homebrew/bin`" and "the file is a Homebrew formula in `Cellar`" are both
  true and people ask about each, so Which Copy reports the name, the resolution,
  and the evidence rather than collapsing them.
- **Version ordering is textual and conservative.** `3.9.2` < `3.13.1` is
  arithmetic on version components, not a claim about which release is better.

## Development

```bash
pytest                     # works from the repo root; `pytest tests` too
hermes plugins doctor . --ci     # real loader, real contracts
hermes plugins validate .        # the catalog admission gate
```

The suite covers symlinked, broken, looped, non-executable and directory
candidates; PATH parsing including empty and repeated slots; login-shell capture,
its seeding with the system default PATH, and its timeout/error paths;
provenance for every manager layout; version parsing against real banner strings
and the cases where comparison must be refused; every verdict including the ones
that only appear when Hermes's own copy wins, and the cases where a copy was not
asked, reported nothing, or was not run; the **security boundary** — a directory
passed as `path`, a file passed as `tool`, and a copy behind a relative or empty
PATH entry each get a tripwire script that would leave a file behind if it ever
executed, and the test fails if it does; the read-only guarantee; the demo
scripts' refusal to delete a directory that is not the demo; and a static audit of
the source for network imports, shell strings, writes and deletes.

## License

MIT © Hazem Samak
