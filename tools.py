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


def _finding(candidate: pathmodel.Candidate) -> verdicts.Finding:
    origin = origin_module.classify(candidate.entry_path, candidate.canonical)
    arch = "unknown"
    if candidate.is_live:
        arch = origin_module.binary_arch(candidate.canonical or candidate.entry_path)
    return verdicts.Finding(candidate=candidate, origin=origin, probe=None, arch=arch)


def _probe_all(
    targets: Sequence[tuple[str, str]],
    *,
    budget: float,
    per_probe: float,
    path_value: str,
) -> dict[tuple[str, str], Probe]:
    """Probe each ``(entry, tool)`` once, in parallel, inside a shared deadline."""
    unique = []
    seen = set()
    for target in targets:
        if target in seen:
            continue
        seen.add(target)
        unique.append(target)
    if not unique:
        return {}

    deadline = time.monotonic() + budget
    results: dict[tuple[str, str], Probe] = {}

    def work(entry_path: str, tool: str) -> Probe:
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
        futures = {pool.submit(work, entry, tool): (entry, tool) for entry, tool in unique}
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


def _collect(
    tool: str,
    source: PathSource,
    *,
    include_off_path: bool,
    roots: Sequence[str] | None = None,
) -> tuple[list[verdicts.Finding], list[verdicts.Finding]]:
    on_path = [_finding(candidate) for candidate in pathmodel.candidates_on_path(tool, source)]
    off_path: list[verdicts.Finding] = []
    if include_off_path:
        searched = roots if roots is not None else pathmodel.extra_roots()
        off_path = [
            _finding(candidate)
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

    targets: list[tuple[str, str]] = []
    for item in on_path:
        if item.candidate.is_live:
            targets.append((item.candidate.entry_path, tool))
    for item in off_path[:4]:
        targets.append((item.candidate.entry_path, tool))
    if login_findings:
        targets.append((login_findings[0].candidate.entry_path, tool))

    probes = _probe_all(targets, budget=budget, per_probe=per_probe, path_value=source.raw)
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
    """Attach the probe for each copy, leaving unprobed copies without one."""
    result: list[verdicts.Finding] = []
    for finding in findings:
        probe = probes.get((finding.candidate.entry_path, tool))
        result.append(dataclasses.replace(finding, probe=probe) if probe else finding)
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
            return _path_mode(raw_name, started=started, probe_versions=probe_versions,
                              check_shell=check_shell)

        custom_path = str(args.get("path") or "").strip()
        if custom_path:
            source = pathmodel.custom_source(custom_path)
            shell = None
        else:
            source, shell = _sources(check_shell)
        if not source.available:
            return _fail("no_path", source.note, tool=raw_name)

        on_path, off_path = _collect(raw_name, source, include_off_path=include_off_path)
        login_findings: list[verdicts.Finding] = []
        login_source: PathSource | None = None
        if shell is not None and shell.available:
            login_source = shell
            login_findings = [
                _finding(candidate) for candidate in pathmodel.candidates_on_path(raw_name, shell)
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
            truth = _hermes_truth(raw_name)
            if truth:
                report["summary"] = report["summary"].rstrip() + "\n\n" + truth + "\n"
                report["hermes_truth"] = truth
        report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        report["how_to_read"] = (
            "Path is what Hermes would execute for this name. 'PATH n of N' is the slot it "
            "won. The copies list is in PATH order; anything after the winner never runs."
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


def _hermes_truth(tool: str) -> str:
    """One sentence about what Hermes itself would run, for a supplied PATH report."""
    real = pathmodel.hermes_source()
    if not real.available:
        return ""
    try:
        candidates = pathmodel.candidates_on_path(tool, real)
    except OSError:
        return ""
    live = [candidate for candidate in candidates if candidate.is_live]
    if not live:
        return "Separately: this is not the PATH Hermes runs with, and Hermes has no %s on its own PATH." % tool
    winner = live[0]
    probe = versions.probe(
        winner.entry_path,
        tool=tool,
        timeout=SINGLE_PROBE_TIMEOUT_S,
        path_value=real.raw,
    )
    version = " (%s)" % probe.version if probe.version else ""
    return (
        "Separately: this is not the PATH Hermes runs with. For %s, Hermes itself would "
        "run %s%s." % (tool, pathmodel.tidy(winner.entry_path), version)
    )


def _path_mode(raw_path: str, *, started: float, probe_versions: bool, check_shell: bool) -> str:
    """``which_copy("/usr/bin/python3")`` — facts about one file on disk."""
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

    finding = _finding(candidate)
    if probe_versions and candidate.is_live:
        probe = versions.probe(
            candidate.entry_path,
            tool=name,
            timeout=SINGLE_PROBE_TIMEOUT_S,
            path_value=os.environ.get("PATH", ""),
        )
        finding = dataclasses.replace(finding, probe=probe)

    source, shell = _sources(check_shell)
    on_path = [
        _finding(item) for item in pathmodel.candidates_on_path(name, source)
    ] if source.available else []
    winning = next((item for item in on_path if item.candidate.is_live), None)

    is_winner = bool(
        winning
        and candidate.is_live
        and winning.candidate.canonical == candidate.canonical
    )

    lines = [
        "%s — %s" % (expanded, "a copy Hermes would run" if is_winner else "not the copy Hermes runs"),
        "",
        " · ".join(
            part
            for part in (
                finding.version or "version unknown",
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
        lines.append("This is %s, so nothing can execute it." % candidate.kind_label)
    elif winning is not None and not is_winner:
        lines.append("")
        lines.append(
            "For the name %s, Hermes runs %s instead — this file is never reached."
            % (name, pathmodel.tidy(winning.candidate.entry_path))
        )
    elif winning is None:
        lines.append("")
        lines.append("No copy of %s is on Hermes's PATH at all." % name)

    payload = {
        "status": "ok",
        "mode": "path",
        "tool": name,
        "path": expanded,
        "summary": "\n".join(lines).strip() + "\n",
        "verdict": "ok_single" if is_winner else ("not_installed" if winning is None else "shadowed_by_other"),
        "severity": "ok" if is_winner else "note",
        "headline": "%s: %s" % (expanded, "this is the copy Hermes runs" if is_winner else "not the copy Hermes runs"),
        "file": finding.candidate.as_dict(),
        "version": finding.version,
        "origin": finding.origin.as_dict(),
        "arch": finding.arch,
        "is_path_winner": is_winner,
        "path_winner": verdicts._finding_dict(winning),
        "path": source.as_dict(),
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

        roots = pathmodel.extra_roots() if include_off_path else []

        collected: list[tuple[str, list[verdicts.Finding], list[verdicts.Finding]]] = []
        for name in names:
            on_path, off_path = _collect(
                name, source, include_off_path=include_off_path, roots=roots
            )
            collected.append((name, on_path, off_path))

        login_map: dict[str, list[verdicts.Finding]] = {}
        login_source: PathSource | None = None
        if shell is not None and shell.available:
            login_source = shell
            for name in names:
                login_map[name] = [
                    _finding(candidate)
                    for candidate in pathmodel.candidates_on_path(name, shell)
                ]

        probes: dict[tuple[str, str], Probe] = {}
        if probe_versions:
            targets: list[tuple[str, str]] = []
            for name, on_path, off_path in collected:
                live = [item for item in on_path if item.candidate.is_live]
                for item in live[:MAX_PROBES_PER_TOOL]:
                    targets.append((item.candidate.entry_path, name))
                for item in off_path[:1]:
                    targets.append((item.candidate.entry_path, name))
                if login_map.get(name):
                    targets.append((login_map[name][0].candidate.entry_path, name))
            threshold = MAX_PROBES_PER_SCAN
            probes = _probe_all(
                targets[:threshold],
                budget=SCAN_PROBE_BUDGET_S,
                per_probe=SCAN_PROBE_TIMEOUT_S,
                path_value=source.raw,
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
                "Each line is one tool: the copy Hermes runs for that name, and the single "
                "most useful thing to know about it. Use which_copy on a name for the full "
                "picture."
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
            "winner_path": terminal_winner.get("path"),
            "winner_path_raw": terminal_winner.get("path_raw"),
            "winner_version": terminal_winner.get("version"),
        },
        "verdicts": [
            {"code": item["code"], "severity": item["severity"], "text": item["text"]}
            for item in report.get("verdicts", [])
        ],
    }
