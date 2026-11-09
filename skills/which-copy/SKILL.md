---
name: which-copy
description: "Report which copy of a command Hermes runs, without overstating it."
version: 1.2.3
author: Hazem Samak
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [diagnostics, path, environment, tools]
---

# Reporting a Which Copy result

`which_copy` and `which_copy_scan` return JSON that already contains the answer
as finished prose in a `summary` field. Your job is to hand that over intact and
add one useful sentence — not to rewrite it.

## Do this

1. **Paste `summary` verbatim inside a fenced code block.** It is already aligned,
   already names paths and versions, already says what is wrong. Retyping it in
   your own words loses the paths, which are the whole point.
2. **Lead with one line of your own**: the answer to the question that was asked.
   *"Hermes's own PATH picks Python 3.14.9, not the Homebrew 3.15.2 your terminal
   runs."*
3. **Then stop.** One or two sentences total. If the person wants the full
   picture they will ask for it.

## Say this, not that

- **"Hermes's own PATH picks X"** — correct for the default check, which reads
  the `PATH` in the environment of the running Hermes process. It is what a
  subprocess spawned with that environment resolves, not necessarily what a
  command typed into Hermes's terminal tool gets.
- **"Your terminal runs Y"** — only when the report's `terminal` block has a
  winner. That shell was started from the system default PATH and then ran the
  user's startup files, so the entries are theirs; the report says so.
- **"In the PATH you gave me, X wins"** — when the call passed `path`. Never
  slide from that into claiming it is what Hermes uses; the report says
  otherwise in its own last lines. And if the copies there came back "version not
  checked", say that: a pasted PATH is read, never run.
- **"An older copy is shadowing a newer one"** — only when `verdict` is
  `shadowed_by_older`. The report refuses to order versions that were never
  meant to be compared, and so should you.

## Never do this

- **Never merge the three PATHs into one claim.** Hermes's process PATH, the
  user's login shell, and the PATH Hermes's terminal tool builds for a command
  are different things. The report measures the first two and explicitly says
  the third can differ; do not "tidy" that sentence away.
- **Never say a copy matches another because nothing said otherwise.** "not
  probed" and "reported no version" are not "same version".
- **Never say you fixed, cleaned, or repaired PATH.** These tools only read. They
  do not move, relink, install, uninstall or unset anything, and claiming
  otherwise makes the user think a problem is gone when it is not.
- **Never say a file was run when it was not.** A path passed as `tool`, and a
  copy found only in a `path` string, are described and **not executed** — the
  JSON carries a `not_run` reason and the summary has a "Not run" line. Keep that
  line. If the person wants the version of the file they named, tell them the
  command to run themselves (the report prints it); do not imply the tool did it.
- **Never read the copies list as "what is in that PATH".** A supplied-PATH report
  also lists copies found elsewhere on the machine, each marked "not in the PATH
  you supplied", and the count line splits them: "3 in the PATH you supplied, 5
  elsewhere on this machine".
- **Never invent a version.** If `version` is null, say the copy did not report
  one; do not guess from the file name. "version not checked" and "not run" are
  answers, not gaps to fill in.
- **Never treat "Hermes-managed" as a fault.** Hermes ships its own Python, Node
  and ripgrep on purpose. It is context, not damage.
- **Never paste the whole JSON** unless asked for it. The summary is for the
  person; the JSON is for you.

## Offering a next step

If the report has a `trap`, the honest next step is a *choice*, not a command:
which copy they want to win, and whether that is worth changing. Ask before
proposing anything that edits their shell files, and remember that a PATH change
in `~/.zshrc` reaches Hermes only after Hermes is restarted, because Hermes
rebuilds its own PATH at startup.

## Which tool to reach for

| The question | The tool |
| --- | --- |
| "which python / node / claude will you use?" | `which_copy` with `tool` |
| "is anything broken or duplicated on my PATH?" | `which_copy_scan` |
| "what about this PATH from my cron job / script?" | `which_copy` with `tool` and `path` |
| "is this specific file the one that runs?" | `which_copy` with an absolute path as `tool` |

Two of those are read-only answers, and it matters which:

- **An absolute path as `tool`** is described and **never executed** — the report
  says "Version check: not run" and prints the command the person can run
  themselves. Say that plainly if they asked for a version: they get the facts
  about the file, and the command, not a version you made the tool fetch.
- **A `path` you pass in** is read, not run. Copies that exist only there come
  back "version not checked"; copies that the machine's own PATHs already reach
  still report their versions, and those probes use Hermes's own process PATH —
  never the raw string you passed. Do not present the missing versions as a
  failure — it is the boundary that stops a prompt-injected repository from
  getting its own script executed, including through a trusted script's
  `#!/usr/bin/env` interpreter. If the person wants the versions, the honest next
  step is to put that directory on their own PATH and ask again, or to run the copy
  themselves.
