# Recording Which Copy in under 90 seconds

Everything here runs on your own machine. No network, no accounts, nothing to
sign up for. Total setup for the recording: one terminal window, one Hermes
window, and this repository cloned.

## Before you hit record

```bash
hermes plugins install Hazem-Samak/hermes-which-copy --yes-deps --enable
# if the tools do not appear in the current Hermes session:
hermes gateway restart      # run this from a terminal OUTSIDE Hermes
```

Check the tools are live by asking Hermes once: *"which python3 will you use?"*
If it answers, you are ready.

## The shot list

| Time | On screen | What you say |
| --- | --- | --- |
| 0:00 | Terminal. `bash demo/setup.sh` | "Every Mac has this problem and almost nobody can see it. I just made three copies of Python, oldest first." |
| 0:10 | Terminal. `export PATH=...` (the line setup printed), then `which -a python3` | "Six pythons on this machine. My shell picks the 2021 one — 3.9.2 — because it is first." |
| 0:25 | Hermes window. Type: *which python3 will you use?* | "Let me ask the agent that actually runs my code." |
| 0:35 | The report appears | Read the verdict line out loud: "An older copy wins — 3.9.2 — and a 3.13.1 copy never gets the chance." |
| 0:50 | Scroll to the last line of the report | "And here is the part I did not expect: Hermes does not use my shell's PATH at all. It runs its own Python 3.14.9." |
| 1:05 | Hermes: *check my whole environment* | "One command sweeps the usual AI tools — python, node, npm, the coding CLIs." |
| 1:20 | The table appears, python3 at the top with ⚠ | "One trap, everything else clean, and it tells me which ones my terminal and Hermes disagree about." |
| 1:30 | Back to Hermes: *and which claude?* | "Same question for anything else — and notice it says what it does not know instead of guessing." |

Stop at 90 seconds. Do not cut into the report while it is on screen — the whole
point is that the answer arrives finished and readable.

## The two lines worth saying out loud

1. **"It tells me which one wins, where it came from, and what version it is —
   and when it cannot tell, it says that too."**
2. **"It fixes nothing. It only tells me the truth, and I decide."**

## If you want the trap to be about python and not claude

The demo box's `bin-2021/python3` and `bin-2025/python3` (3.9.2 and 3.13.1) are
what the PATH-trap report is built from. To show the same thing for a name
Hermes does not manage itself, use `claude` (0.9.1 vs 2.0.4) — that one is
entirely inside the demo PATH, so every line of the report is about the copies
you made.

## Cleanup

```bash
bash demo/cleanup.sh
```

Nothing else on the machine was touched — the demo writes only inside
`~/which-copy-demo`.
