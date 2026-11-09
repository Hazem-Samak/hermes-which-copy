"""Tool handlers for Which Copy.

Both handlers return a JSON string — success and failure alike — and never raise.
The only work they do is reading the filesystem, reading PATH out of a login
shell, and asking a discovered binary for its version. Nothing is written,
nothing is installed, nothing is repaired.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Sequence

from . import known_tools, origin as origin_module, pathmodel, verdicts, versions
from .pathmodel import InvalidToolName, PathSource
from .versions import Probe

__all__ = ["which_copy", "which_copy_scan"]

# Probe budget: a single check gets a generous slice, a sweep shares one.
SINGLE_PROBE_BUDGET_S = 6.0
SINGLE_PROBE_TIMEOUT_S = 3.0
SCAN_PROBE_BUDGET_S = 15.0
SCAN_PROBE_TIMEOUT_S = 2.0
MAX_PROBES_PER_TOOL = 3
MAX_PROBES_PER_SCAN = 60
MAX_WORKERS = 12


# --------------------------------------------------------------------------- #
# Plumbing


def _fail(status: str, message: str, **extra) -> str:
    payload = {"status": status, "message": message}
    payload.update(extra)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _flag(args: dict, key: str, default: bool) -> bool:
    value = args.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off", "")
    return bool(value)


def _clean_name(raw) -> str:
    text = str(raw or "").strip()
    if not text:
        raise InvalidToolName(
            "No tool name was given. Pass the name of a command, for example "
            '"python3" or "claude".'
        )
    if len(text) > 200:
        raise InvalidToolName("That tool name is too long to look up (over 200 characters).")
    if any(character in text for character in ("\x00", "\n", "\r", "\t")):
        raise InvalidToolName("A tool name cannot contain control characters.")
    return text


def _looks_like_path(text: str) -> bool:
    if os.sep in text:
        return True
    on_windows = "\\" in text
    return on_windows


def _finding(candidate: pathmodel.Candidate, trust: pathmodel.ProbeTrust) -> verdicts.Finding:
    origin = origin_module.classify(candidate.entry_path, candidate.canonical)
    arch = "unknown"
    if candidate.is_live:
        arch = origin_module.binary_arch(candidate.canonical or candidate.entry_path)
    # A copy this check will not execute says so from the start, so no later
    # stage can decide to run it by accident.
    not_run = pathmodel.refusal(candidate, trust) if candidate.is_live else ""
    return verdicts.Finding(candidate=candidate, origin=origin, probe=None, arch=arch, not_run=not_run)


def _probeable(findings: Sequence[verdicts.Finding], limit: int | None = None) -> list[verdicts.Finding]:
    """The copies in ``findings`` this check is allowed to execute."""
    chosen = [item for item in findings if item.candidate.is_live and not item.not_run]
    return chosen[:limit] if limit is not None else chosen


def _probe_all(
    targets: Sequence[tuple[str, str, str]],
    *,
    budget: float,
    per_probe: float,
) -> dict[tuple[str, str], Probe]:
    """Probe each ``(entry, tool)`` once, in parallel, inside a shared deadline.

    Each target carries the PATH that copy would see, so a copy found through
    the login shell is asked its version with the shell's PATH — not with
    Hermes's, which would make "it could not find a command it needs" a lie.
    Targets built from a supplied PATH carry Hermes's own process PATH instead:
    a supplied PATH may choose candidates, never their interpreters.
    """
    unique = []
    seen = set()
    for entry, tool, path_value in targets:
        key = (entry, tool)
        if key in seen:
            continue
        seen.add(key)
        unique.append((entry, tool, path_value))
    if not unique:
        return {}

    deadline = time.monotonic() + budget
    results: dict[tuple[str, str], Probe] = {}

    def work(entry_path: str, tool: str, path_value: str) -> Probe:
        remaining = deadline - time.monotonic()
        if remaining <= 0.05:
            return Probe(argv=(), error="not_probed")
        return versions.probe(
            entry_path,
            tool=tool,
            timeout=max(0.2, min(per_probe, remaining)),
            path_value=path_value,
        )

    workers = max(1, min(MAX_WORKERS, len(unique)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, entry, tool, path): (entry, tool) for entry, tool, path in unique}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as exc:  # noqa: BLE001 - a probe must never take the tool down
                results[key] = Probe(argv=(), error="probe_error: %s" % exc)
    return results


def _sources(check_login_shell: bool) -> tuple[PathSource, PathSource | None]:
    source = pathmodel.hermes_source()
    shell = pathmodel.login_shell_source() if check_login_shell else None
    return source, shell


def _version_probe_path(source: PathSource) -> str:
    """The child PATH for probing a copy found in ``source``.

    A supplied PATH describes candidates but must never select the interpreter
    a trusted script's ``#!`` line resolves. Custom-source probes therefore run
    with Hermes's own process PATH, never the raw supplied string.
    """
    if source.kind == pathmodel.CUSTOM_SOURCE:
        return pathmodel.hermes_source().raw
    return source.raw


def _collect(
    tool: str,
    source: PathSource,
    *,
    include_off_path: bool,
    trust: pathmodel.ProbeTrust,
    roots: Sequence[str] | None = None,
) -> tuple[list[verdicts.Finding], list[verdicts.Finding]]:
    on_path = [
        _finding(candidate, trust) for candidate in pathmodel.candidates_on_path(tool, source)
    ]
    off_path: list[verdicts.Finding] = []
    if include_off_path:
        searched = roots if roots is not None else pathmodel.extra_roots()
        off_path = [
            _finding(candidate, trust)
            for candidate in pathmodel.candidates_off_path(
                tool,
                searched,
                already=[item.candidate.entry_path for item in on_path],
            )
        ]
    return on_path, off_path


def _probe_report(
    tool: str,
    source: PathSource,
    on_path: Sequence[verdicts.Finding],
    off_path: Sequence[verdicts.Finding],
    shell: PathSource | None,
    login_findings: Sequence[verdicts.Finding],
    *,
    probe_versions: bool,
    budget: float,
    per_probe: float,
    probed_note: str = "",
) -> dict:
    if not probe_versions:
        return _analyze(
            tool, source, on_path, off_path, shell, login_findings, probed=False, probed_note=probed_note
        )

    targets: list[tuple[str, str, str]] = []
    probe_path = _version_probe_path(source)
    for item in _probeable(on_path):
        targets.append((item.candidate.entry_path, tool, probe_path))
    for item in _probeable(off_path, 4):
        targets.append((item.candidate.entry_path, tool, probe_path))
    if login_findings:
        shell_path = shell.raw if shell is not None else source.raw
        live = _probeable(login_findings)
        if live:
            targets.append((live[0].candidate.entry_path, tool, shell_path))

    probes = _probe_all(targets, budget=budget, per_probe=per_probe)
    return _analyze(
        tool,
        source,
        _swap(on_path, probes, tool),
        _swap(off_path, probes, tool),
        shell,
        _swap(login_findings, probes, tool),
        probed=True,
        probed_note=probed_note,
    )


def _swap(
    findings: Sequence[verdicts.Finding],
    probes: dict[tuple[str, str], Probe],
    tool: str,
) -> list[verdicts.Finding]:
    """Attach the probe for each copy, leaving unprobed copies without one.

    A copy that carries a probe was, by definition, run — so it loses any
    "not run" mark it was given. (That happens when a relative PATH entry and a
    trusted one resolve to the same file: the file is run because the trusted
    directory has it, and saying otherwise would contradict the version shown.)
    """
    result: list[verdicts.Finding] = []
    for finding in findings:
        probe = probes.get((finding.candidate.entry_path, tool))
        if probe:
            result.append(dataclasses.replace(finding, probe=probe, not_run=""))
        else:
            result.append(finding)
    return result


def _analyze(
    tool: str,
    source: PathSource,
    on_path: Sequence[verdicts.Finding],
    off_path: Sequence[verdicts.Finding],
    shell: PathSource | None,
    login_findings: Sequence[verdicts.Finding],
    *,
    probed: bool,
    probed_note: str = "",
) -> dict:
    notes = []
    if probed_note:
        notes.append(probed_note)
    return verdicts.analyze(
        tool,
        source,
        on_path,
        off_path,
        login_shell=shell,
        login_findings=login_findings,
        probed=probed,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Tool 1 — one name


def which_copy(args: dict = None, **kwargs) -> str:
    args = args or {}
    started = time.monotonic()
    try:
        raw_name = _clean_name(args.get("tool") or args.get("name") or args.get("command"))
        check_shell = _flag(args, "check_login_shell", True)
        probe_versions = _flag(args, "probe_versions", True)
        include_off_path = _flag(args, "include_off_path", True)

        if _looks_like_path(raw_name):
            return _path_mode(raw_name, started=started, check_shell=check_shell)

        custom_path = str(args.get("path") or "").strip()
        if custom_path:
            source = pathmodel.custom_source(custom_path)
            shell = None
        else:
            source, shell = _sources(check_shell)
        if not source.available:
            return _fail("no_path", source.note, tool=raw_name)

        trust = pathmodel.probe_trust(
            shell=shell if shell is not None and shell.available else None
        )
        on_path, off_path = _collect(
            raw_name, source, include_off_path=include_off_path, trust=trust
        )
        login_findings: list[verdicts.Finding] = []
        login_source: PathSource | None = None
        if shell is not None and shell.available:
            login_source = shell
            login_findings = [
                _finding(candidate, trust)
                for candidate in pathmodel.candidates_on_path(raw_name, shell)
            ]

        report = _probe_report(
            raw_name,
            source,
            on_path,
            off_path,
            login_source,
            login_findings,
            probe_versions=probe_versions,
            budget=SINGLE_PROBE_BUDGET_S,
            per_probe=SINGLE_PROBE_TIMEOUT_S,
        )
        report["status"] = "ok"
        report["mode"] = "custom-path" if custom_path else "name"
        if custom_path:
            truth = _hermes_truth(raw_name, probe_versions)
            if truth:
                report["summary"] = report["summary"].rstrip() + "\n\n" + truth + "\n"
                report["hermes_truth"] = truth
        report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        report["how_to_read"] = (
            "Path is the copy the Hermes process resolves for this name (its os.environ PATH). "
            "'PATH n of N' is the slot it won. The copies list is in PATH order; anything after "
            "the winner never runs. Commands run through Hermes's terminal tool use a login shell "
            "plus directories Hermes adds, so that shell can resolve a different copy."
        )
        return json.dumps(report, indent=2, ensure_ascii=False)
    except InvalidToolName as exc:
        return _fail("bad_request", str(exc))
    except Exception as exc:  # noqa: BLE001 - the tool reports, it does not crash
        return _fail(
            "error",
            "Which Copy could not finish the check (%s: %s). Nothing was changed."
            % (type(exc).__name__, exc),
        )


def _hermes_truth(tool: str, probe_versions: bool = True) -> str:
    """One sentence about what Hermes's own process PATH resolves, for a supplied-PATH report."""
    real = pathmodel.hermes_source()
    if not real.available:
        return ""
    try:
        candidates = pathmodel.candidates_on_path(tool, real)
    except OSError:
        return ""
    live = [candidate for candidate in candidates if candidate.is_live]
    if not live:
        return (
            "Separately: this is not the PATH Hermes's process runs with, and Hermes's own PATH "
            "has no %s." % tool
        )
    winner = live[0]
    trust = pathmodel.probe_trust()
    if not probe_versions or not trust.allows(winner.entry_path):
        # probe_versions: false means no process is started, for this line too;
        # and a copy this check will not execute gets no version either.
        return (
            "Separately: this is not the PATH Hermes's process runs with. For %s, Hermes's own "
            "PATH resolves to %s (version not checked)." % (tool, pathmodel.tidy(winner.entry_path))
        )
    probe = versions.probe(
        winner.entry_path,
        tool=tool,
        timeout=SINGLE_PROBE_TIMEOUT_S,
        path_value=real.raw,
    )
    version = " (%s)" % probe.version if probe.version else ""
    return (
        "Separately: this is not the PATH Hermes's process runs with. For %s, Hermes's own "
        "PATH resolves to %s%s." % (tool, pathmodel.tidy(winner.entry_path), version)
    )


def _path_mode(raw_path: str, *, started: float, check_shell: bool) -> str:
    """``which_copy("/usr/bin/python3")`` — facts about one file on disk.

    The file is named by the caller, so nothing about it is trusted: a prompt
    injected into a repository can put any string here, and a diagnostic tool is
    not a reason to execute it. Every fact below is read from the filesystem —
    what the name points at, what it came from, what CPU it is built for, and
    whether Hermes would pick it — and the file itself is never run. The report
    says so, with the command the person can run themselves if they want its
    version, so ``probe_versions`` has nothing to switch off here.
    """
    expanded = os.path.abspath(os.path.expanduser(raw_path))
    name = os.path.basename(expanded)
    if not name:
        return _fail("bad_request", "That path does not end in a file name.")

    candidate = pathmodel.inspect(expanded, on_path=False)
    if candidate is None:
        return _fail(
            "not_found",
            "There is nothing at %s, so there is no copy to describe." % expanded,
            path=expanded,
        )

    source, shell = _sources(check_shell)
    trust = pathmodel.probe_trust(
        shell=shell if shell is not None and shell.available else None
    )
    finding = _finding(candidate, trust)
    not_run = None
    if candidate.is_live:
        # Named by the caller, so it is never executed — regardless of where it
        # lives and regardless of probe_versions.
        finding = dataclasses.replace(finding, not_run=pathmodel.NOT_RUN_NAMED)
        not_run = {
            "reason": "named_by_caller",
            "text": pathmodel.NOT_RUN_NAMED,
            "run_it_yourself": "%s --version" % expanded,
            "note": (
                "Nothing at this path was executed. Naming a file is not a request to "
                "run it, so the version is unknown here; the command above asks it "
                "yourself, in your own shell."
            ),
        }

    on_path = [
        _finding(item, trust) for item in pathmodel.candidates_on_path(name, source)
    ] if source.available else []
    winning = next((item for item in on_path if item.candidate.is_live), None)

    is_winner = bool(
        winning
        and candidate.is_live
        and winning.candidate.canonical == candidate.canonical
    )

    lines = [
        "%s — %s"
        % (
            expanded,
            "the copy Hermes's process PATH picks" if is_winner else "not the copy Hermes's process PATH picks",
        ),
        "",
        " · ".join(
            part
            for part in (
                finding.version or "version not checked",
                finding.origin.label,
                "architecture: %s" % finding.arch,
            )
            if part
        ),
    ]
    if finding.origin.evidence:
        lines.append("Evidence: %s." % finding.origin.evidence)
    if not candidate.is_live:
        lines.append("")
        lines.append("Nothing can execute this path — %s." % candidate.kind_label)
    elif winning is not None and not is_winner:
        lines.append("")
        lines.append(
            "For the name %s, Hermes's process PATH picks %s instead — this file is never reached."
            % (name, pathmodel.tidy(winning.candidate.entry_path))
        )
    elif winning is None:
        lines.append("")
        lines.append("No copy of %s is on Hermes's process PATH at all." % name)
    if not_run:
        lines.append("")
        lines.append(
            "Version check: not run — %s. To ask it yourself: %s"
            % (pathmodel.NOT_RUN_NAMED, not_run["run_it_yourself"])
        )

    payload = {
        "status": "ok",
        "mode": "path",
        "tool": name,
        # The file the caller asked about. It stays "path"; the PATH it was
        # resolved against is "path_source", so one key never means two things.
        "path": expanded,
        "path_source": source.as_dict(),
        "summary": "\n".join(lines).strip() + "\n",
        "verdict": "ok_single" if is_winner else ("not_installed" if winning is None else "shadowed_by_other"),
        "severity": "ok" if is_winner else "note",
        "headline": "%s: %s"
        % (
            expanded,
            "the copy Hermes's process PATH picks" if is_winner else "not the copy Hermes's process PATH picks",
        ),
        "file": finding.candidate.as_dict(),
        "version": finding.version,
        "origin": finding.origin.as_dict(),
        "arch": finding.arch,
        "is_path_winner": is_winner,
        # Nothing here was executed: a path named in an argument is described,
        # never run. `probe_versions` does not change that.
        "executed": None,
        "not_run": not_run,
        "path_winner": verdicts._finding_dict(winning),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Tool 2 — the environment sweep


def _names(raw) -> list[str]:
    values: list[str] = []
    if isinstance(raw, str):
        text = raw.replace(",", " ")
        values = [part for part in text.split() if part]
    elif isinstance(raw, (list, tuple)):
        values = [str(part).strip() for part in raw if str(part).strip()]
    else:
        return []

    names: list[str] = []
    seen = set()
    for value in values:
        try:
            clean = _clean_name(value)
        except InvalidToolName:
            continue
        if clean in seen or _looks_like_path(clean):
            continue
        seen.add(clean)
        names.append(clean)
    return names[: known_tools.MAX_TOOLS]


def which_copy_scan(args: dict = None, **kwargs) -> str:
    args = args or {}
    started = time.monotonic()
    try:
        requested = _names(args.get("tools") or args.get("names") or args.get("tool"))
        names = requested or list(known_tools.default_scan())
        check_shell = _flag(args, "check_login_shell", True)
        probe_versions = _flag(args, "probe_versions", True)
        include_off_path = _flag(args, "include_off_path", True)

        source, shell = _sources(check_shell)
        custom_path = str(args.get("path") or "").strip()
        if custom_path:
            source = pathmodel.custom_source(custom_path)
            shell = None
        if not source.available:
            return _fail("no_path", source.note)

        trust = pathmodel.probe_trust(
            shell=shell if shell is not None and shell.available else None
        )
        roots = pathmodel.extra_roots() if include_off_path else []

        collected: list[tuple[str, list[verdicts.Finding], list[verdicts.Finding]]] = []
        for name in names:
            on_path, off_path = _collect(
                name, source, include_off_path=include_off_path, roots=roots, trust=trust
            )
            collected.append((name, on_path, off_path))

        login_map: dict[str, list[verdicts.Finding]] = {}
        login_source: PathSource | None = None
        if shell is not None and shell.available:
            login_source = shell
            for name in names:
                login_map[name] = [
                    _finding(candidate, trust)
                    for candidate in pathmodel.candidates_on_path(name, shell)
                ]

        probes: dict[tuple[str, str], Probe] = {}
        if probe_versions:
            targets: list[tuple[str, str, str]] = []
            probe_path = _version_probe_path(source)
            for name, on_path, off_path in collected:
                for item in _probeable(on_path, MAX_PROBES_PER_TOOL):
                    targets.append((item.candidate.entry_path, name, probe_path))
                for item in _probeable(off_path, 1):
                    targets.append((item.candidate.entry_path, name, probe_path))
                login_live = _probeable(login_map.get(name, []))
                if login_live and login_source is not None:
                    targets.append((login_live[0].candidate.entry_path, name, login_source.raw))
            threshold = MAX_PROBES_PER_SCAN
            probes = _probe_all(
                targets[:threshold],
                budget=SCAN_PROBE_BUDGET_S,
                per_probe=SCAN_PROBE_TIMEOUT_S,
            )

        reports: list[dict] = []
        for name, on_path, off_path in collected:
            login_items = login_map.get(name, [])
            if probe_versions:
                on_path = _swap(on_path, probes, name)
                off_path = _swap(off_path, probes, name)
                login_items = _swap(login_items, probes, name)
            full = verdicts.analyze(
                name,
                source,
                on_path,
                off_path,
                login_shell=login_source,
                login_findings=login_items,
                probed=probe_versions,
                notes=(),
            )
            reports.append(_slim(full))

        summary = verdicts.scan_summary(reports, source, login_source)
        if custom_path:
            summary = summary.rstrip() + (
                "\n\nThis was the PATH you supplied. Hermes itself runs with its own PATH — "
                "call which_copy_scan without `path`, or which_copy on one name, to see what "
                "Hermes would actually run."
            ) + "\n"
        payload = {
            "status": "ok",
            "mode": "custom-path" if custom_path else "scan",
            "summary": summary,
            "counts": {
                "tools": len(reports),
                "traps": sum(1 for report in reports if report["severity"] == "trap"),
                "warnings": sum(1 for report in reports if report["severity"] == "warning"),
                "notes": sum(1 for report in reports if report["severity"] == "note"),
                "installed": sum(1 for report in reports if report.get("winner")),
            },
            "tools": reports,
            "path": source.as_dict(),
            "terminal": (
                {"label": login_source.label, "available": True, "entry_count": len(login_source.entries)}
                if login_source
                else {
                    "label": "your login shell",
                    "available": False,
                    "note": shell.note if shell else "Login shell check was skipped.",
                }
            ),
            "host_arch": origin_module.host_arch(),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "how_to_read": (
                "Each line is one tool: the copy the Hermes process resolves for that name, and "
                "the single most useful thing to know about it. Use which_copy on a name for the "
                "full picture. Hermes's terminal tool adds directories to its shell's PATH, so a "
                "command it runs can resolve a different copy."
            ),
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "error",
            "Which Copy could not finish the sweep (%s: %s). Nothing was changed."
            % (type(exc).__name__, exc),
        )


def _slim(report: dict) -> dict:
    """The scan keeps the facts a chat answer needs, not the whole file listing."""
    winner = report.get("winner")
    slim_winner = None
    if winner:
        slim_winner = {
            "path": winner["path"],
            "path_raw": winner["path_raw"],
            "version": winner["version"],
            "arch": winner["arch"],
            "path_slot": winner["path_slot"],
            "origin": winner["origin"],
        }
    terminal = report.get("terminal") or {}
    terminal_winner = (terminal.get("winner") or {}) if isinstance(terminal, dict) else {}
    return {
        "tool": report["tool"],
        "verdict": report["verdict"],
        "severity": report["severity"],
        "headline": report["headline"],
        "winner": slim_winner,
        "copies": len(report.get("copies") or []),
        "terminal": {
            "available": terminal.get("available"),
            "agrees_with_hermes": terminal.get("agrees_with_hermes"),
            # The shell's winner has to survive the trim: the sweep compares it
            # with the Hermes copy to name the tools where the two disagree. A
            # flat subset without "winner" made that line impossible to emit.
            "winner": (
                {
                    "path": terminal_winner.get("path"),
                    "path_raw": terminal_winner.get("path_raw"),
                    "version": terminal_winner.get("version"),
                    "arch": terminal_winner.get("arch"),
                }
                if terminal_winner
                else None
            ),
            "skipped": [
                {
                    "path": item.get("path"),
                    "path_raw": item.get("path_raw"),
                    "kind_label": item.get("kind_label"),
                }
                for item in (terminal.get("skipped") or [])
            ],
        },
        "verdicts": [
            {"code": item["code"], "severity": item["severity"], "text": item["text"]}
            for item in report.get("verdicts", [])
        ],
    }
