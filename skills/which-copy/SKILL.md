---
name: which-copy
description: "Report which copy of a command Hermes runs, without overstating it."
version: 1.0.0
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
   *"Hermes runs its own Python 3.14.9, not the one in your PATH."*
3. **Then stop.** One or two sentences total. If the person wants the full
   picture they will ask for it.

## Say this, not that

- **"Hermes runs X"** — correct for the default check, which reads the PATH the
  Hermes process actually has.
- **"Your terminal runs Y"** — only when the report's `terminal` block is
  available. That is read from the login shell, which is what a terminal gets.
- **"In the PATH you gave me, X wins"** — when the call passed `path`. Never
  slide from that into claiming it is what Hermes uses; the report says
  otherwise in its last line.
- **"An older copy is shadowing a newer one"** — only when `verdict` is
  `shadowed_by_older`. The report refuses to order versions that were never
  meant to be compared, and so should you.

## Never do this

- **Never say you fixed, cleaned, or repaired PATH.** These tools only read. They
  do not move, relink, install, uninstall or unset anything, and claiming
  otherwise makes the user think a problem is gone when it is not.
- **Never invent a version.** If `version` is null, say the copy did not report
  one; do not guess from the file name.
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
