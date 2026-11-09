# Recording Which Copy in under 90 seconds

Everything here runs on your own machine. No network, no accounts, nothing to
sign up for. Total setup for the recording: one terminal window, one Hermes
window, and this repository cloned.

The whole demo comes down to one uncomfortable fact: **Hermes does not use your
terminal's PATH.** It builds its own at startup, so on a Mac with more than one
copy of a tool installed, the copy you think you are using and the copy Hermes
runs are two different things — and nothing warns you.

The second beat is newer, and worth the ten seconds it takes: hand it a messy
PATH and it answers *without running a copy that exists only there*. A PATH in a
chat message is not permission to execute a file.

## Before you hit record

```bash
hermes plugins install Hazem-Samak/hermes-which-copy --yes-deps --enable
# if the tools do not appear in the current Hermes session:
hermes gateway restart      # run this from a terminal OUTSIDE Hermes
```

Check the tools are live by asking Hermes once: *"which python3 will you use?"*
If it answers, you are ready. The demo sandbox is built by the script, so there
is nothing else to prepare.

## The shot list

| Time | On screen | What you say |
| --- | --- | --- |
| 0:00 | Terminal: `bash demo/setup.sh` | "Every Mac has this problem and almost nobody can see it. I just made three copies of Python — oldest first — plus a broken one." |
| 0:12 | The script prints the sandbox PATH | "In a shell with that PATH, `python3` is 3.9.2. There is a 3.13.1 sitting right behind it and that shell will never reach it." |
| 0:25 | Hermes: *"Which python3 will you use?"* | "Now let me ask the agent that actually runs my code." |
| 0:35 | The report | Read the verdict: "It runs its own 3.14.9 — and Homebrew's 3.15.2 is newer and never gets the chance." |
| 0:50 | Scroll to *"Your terminal and Hermes disagree…"* | "Same machine, same command, three different answers." |
| 1:00 | Hermes: *"check my whole environment"* | "One question sweeps the usual AI tools." |
| 1:15 | The table, `python3` and `node` at the top with ⚠ | "Two traps, the rest clean, and it names the ones my terminal and Hermes disagree about." |
| 1:25 | Hermes: paste the sandbox PATH question | "And when I hand it someone else's PATH, it reads it — and it will not run anything that exists only in there." |

Stop at 90 seconds. Do not cut away while a report is on screen: the whole point
is that the answer arrives finished and readable, with the paths in it.

## The two lines worth saying out loud

1. **"It tells me which one wins, where it came from, and what version it is —
   and when it cannot tell, it says that too."**
2. **"It fixes nothing. It only tells me the truth, and I decide."**

## What to point at in the last report

The pasted-PATH report has a `Not run (2)` line: those are the two sandbox copies.
That is not a failure — the sandbox directories are not on Hermes's own PATH and
not in a known install directory, so the copies there are described, ordered, and
left alone. The copies that *do* report a version are the ones the machine put in
a directory this check trusts on its own: `/usr/bin/python3` (3.9.6), Homebrew's
3.15.2, Hermes's own 3.14.9, and the uv tool. Say it in one sentence — *"a PATH you
paste in is read, not run, so a repository can't talk it into executing a file"* —
and move on.

The report's **last** line is the one to end on: `Separately: Hermes's own process
PATH resolves python3 to …(3.14.9)`. That is the punchline of the whole demo — the
PATH you pasted is not the PATH Hermes runs with.

If you want a version comparison on camera, use the real question in beat 1: that
report compares copies the machine actually has, and it is the one people
recognise.

## Copy-paste prompts

```
Which python3 will you use?
```

```
Check my whole environment for the usual AI tools, and tell me what is actually wrong.
```

```
Which copy wins in this PATH? $HOME/which-copy-demo/bin-2021:$HOME/which-copy-demo/bin-2025:$HOME/which-copy-demo/bin-broken:/usr/local/bin:/usr/bin:/bin
```

## Cleanup

```bash
bash demo/cleanup.sh
```

Nothing else on the machine was touched — the demo writes only inside
`~/which-copy-demo`.
