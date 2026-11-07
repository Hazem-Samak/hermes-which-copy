# Recording Which Copy in under 90 seconds

Everything here runs on your own machine. No network, no accounts, nothing to
sign up for. Total setup for the recording: one terminal window, one Hermes
window, and this repository cloned.

The whole demo comes down to one uncomfortable fact: **Hermes does not use your
terminal's PATH.** It builds its own at startup, so on a Mac with more than one
copy of a tool installed, the copy you think you are using and the copy Hermes
runs are two different things — and nothing warns you.

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
| 0:00 | Terminal: `bash demo/run-demo.sh` | "Every Mac has this problem and almost nobody can see it. I just made three copies of Python — oldest first — plus a broken one." |
| 0:12 | The script prints `which python3` → `3.9.2` | "My terminal says 3.9.2. There is a 3.13.1 sitting right behind it, and my shell will never reach it." |
| 0:25 | Hermes window receives the question | "Let me ask the agent that actually runs my code." |
| 0:35 | The report appears | Read the verdict out loud: "An older copy wins — 3.9.2 — and the 3.13.1 copy never gets the chance." |
| 0:50 | Scroll to the last line: *"Separately: this is not the PATH Hermes runs with…"* | "And here is the part I did not expect: Hermes doesn't use my shell's PATH at all. It runs its own Python 3.14.9." |
| 1:05 | Hermes: *check my whole environment* | "One command sweeps the usual AI tools — python, node, npm, the coding CLIs." |
| 1:18 | The table, `python3` at the top with ⚠ | "One trap, the rest clean, and it tells me which ones my terminal and Hermes disagree about." |
| 1:30 | Hermes: *and which claude?* | "Same question for anything else — and notice that when it can't tell, it says so instead of guessing." |

Stop at 90 seconds. Do not cut away while a report is on screen: the whole point
is that the answer arrives finished and readable, with the paths in it.

## The two lines worth saying out loud

1. **"It tells me which one wins, where it came from, and what version it is —
   and when it cannot tell, it says that too."**
2. **"It fixes nothing. It only tells me the truth, and I decide."**

## If you want the trap to be about a name Hermes owns nothing of

`python3` is the honest case: Hermes ships its own Python, so the report ends up
comparing your copies with Hermes's. For a report where every line is about the
copies you made, ask *"which claude?"* — the sandbox has 0.9.1 and 2.0.4 and
Hermes has no copy of its own.

## Copy-paste prompts

```
Which python3 will you use? Then check the same name against this messy PATH
and tell me which copy wins in it: $HOME/which-copy-demo/bin-2021:$HOME/which-copy-demo/bin-2025:$HOME/which-copy-demo/bin-broken:/usr/local/bin:/usr/bin:/bin
```

```
Check my whole environment for the usual AI tools, and tell me what is actually wrong.
```

```
And which claude will you run? Use the same messy PATH.
```

## Cleanup

```bash
bash demo/cleanup.sh
```

Nothing else on the machine was touched — the demo writes only inside
`~/which-copy-demo`.
