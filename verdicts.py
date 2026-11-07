"""Turning copies into a verdict — and into a sentence a person can act on.

The rule this module follows: a claim is only made when the evidence supports
it. Two copies with version strings that were never meant to be compared (a date
version against a semantic one) are reported as "I cannot order these", not
sorted by whichever number looks bigger.

The verdict vocabulary is small on purpose:

``trap``     something is being silently wasted or silently broken
``warning``  worth knowing, not necessarily wrong
``note``     context (Hermes's own copy, several aliases of one file)
``ok``       nothing to report
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from . import origin as origin_module
from . import pathmodel
from .pathmodel import Candidate, PathSource
from .versions import Probe, compare_versions, parse_version_text

SEVERITY_RANK = {"ok": 0, "note": 1, "warning": 2, "trap": 3}

#: Tie-break order when two findings carry the same severity.
PRIORITY = (
    "winner_cannot_run",
    "shadowed_by_older",
    "hermes_vs_terminal",
    "skipped_dead_entries",
    "version_unknown",
    "multiple_copies",
    "hermes_managed_winner",
    "installed_not_on_path",
    "not_installed",
    "ok_aliases",
    "ok_single",
)

MARKERS = {"trap": "⚠", "warning": "!", "note": "•", "ok": "✓"}


@dataclass(frozen=True)
class Finding:
    """One copy, with everything known about it."""

    candidate: Candidate
    origin: origin_module.Origin
    probe: Probe | None = None
    arch: str = "unknown"

    @property
    def version(self) -> str | None:
        return self.probe.version if self.probe else None

    @property
    def display(self) -> str:
        return pathmodel.tidy(self.candidate.entry_path)

    @property
    def origin_phrase(self) -> str:
        return self.origin.label


@dataclass
class Verdict:
    code: str
    severity: str
    text: str
    details: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Rendering helpers


def _copy_line(
    index: int,
    finding: Finding,
    *,
    use_word: str,
    aliases: Sequence[str] = (),
) -> str:
    candidate = finding.candidate
    line = "%d. %s" % (index, pathmodel.tidy(candidate.entry_path))
    bits: list[str] = []
    if finding.version:
        bits.append(finding.version)
    elif finding.probe is not None and finding.probe.error:
        bits.append("no version (%s)" % finding.probe.error_hint)
    bits.append(finding.origin.label)
    if bits:
        line += " — " + " · ".join(bits)
    if use_word:
        line += "  ← " + use_word
    if aliases:
        line += " (also named: %s)" % ", ".join(aliases)
    return line


def _version_or_unknown(finding: Finding | None) -> str:
    if finding is None:
        return "not installed"
    if finding.version:
        return finding.version
    if finding.probe is not None and finding.probe.error:
        return "version unknown — %s" % finding.probe.error_hint
    return "version not checked"


# --------------------------------------------------------------------------- #
# Analysis


def analyze(
    tool: str,
    source: PathSource,
    findings: Sequence[Finding],
    off_path: Sequence[Finding] = (),
    *,
    login_shell: PathSource | None = None,
    login_findings: Sequence[Finding] = (),
    host: str | None = None,
    probed: bool = True,
    notes: Sequence[str] = (),
) -> dict:
    """Build the full report for one tool name."""
    host = host or origin_module.host_arch()
    repeated = pathmodel.repeated_slot_count(source)
    on_path_live = [f for f in findings if f.candidate.is_live]
    dead_on_path = [f for f in findings if not f.candidate.is_live]
    winner = on_path_live[0] if on_path_live else None

    verdicts: list[Verdict] = []

    # ---- No usable copy on PATH ------------------------------------------ #
    where = "Hermes's PATH" if source.kind != pathmodel.CUSTOM_SOURCE else "the PATH you supplied"
    if winner is None:
        if dead_on_path:
            verdicts.append(
                Verdict(
                    "not_installed",
                    "warning" if not off_path else "note",
                    "No usable %s is on %s." % (tool, where),
                    tuple(
                        "%s → %s" % (
                            pathmodel.tidy(f.candidate.entry_path),
                            f.candidate.kind_label,
                        )
                        for f in dead_on_path
                    ),
                )
            )
        else:
            verdicts.append(
                Verdict(
                    "not_installed",
                    "note",
                    "No %s is on %s at all." % (tool, where),
                )
            )
        if off_path:
            verdicts.append(
                Verdict(
                    "installed_not_on_path",
                    "note",
                    "%d copy of %s exist outside PATH, so Hermes cannot run any of them by name."
                    % (len(off_path), tool),
                    tuple(
                        "%s — %s" % (pathmodel.tidy(f.candidate.entry_path), _version_or_unknown(f))
                        for f in off_path
                    ),
                )
            )
        return _finish(
            tool,
            source,
            winner=None,
            on_path_live=on_path_live,
            dead_on_path=dead_on_path,
            off_path=off_path,
            login_shell=login_shell,
            login_findings=login_findings,
            verdicts=verdicts,
            host=host,
            probed=probed,
            notes=notes,
            repeated_slots=repeated,
        )

    # ---- The winner ------------------------------------------------------- #
    arch_note = origin_module.arch_warning(winner.arch, host)
    cannot_run = (
        winner.probe is not None
        and winner.probe.error is not None
        and winner.probe.error.startswith("os_error")
        and bool(arch_note)
    )
    if cannot_run:
        verdicts.append(
            Verdict(
                "winner_cannot_run",
                "trap",
                "%s is the copy Hermes would run, and it cannot run on this Mac: %s."
                % (pathmodel.tidy(winner.candidate.entry_path), arch_note),
            )
        )

    slot_note = ""
    if winner.candidate.slot is not None:
        slot_note = "slot %d" % (winner.candidate.slot + 1)
    before = [f for f in dead_on_path if f.candidate.slot is not None and winner.candidate.slot is not None and f.candidate.slot < winner.candidate.slot]
    if before:
        verdicts.append(
            Verdict(
                "skipped_dead_entries",
                "warning",
                "Earlier in PATH, %s is not a usable program, so the shell silently skips it."
                % ("one entry for " + tool if len(before) == 1 else "%d entries for %s" % (len(before), tool)),
                tuple(
                    "%s → %s" % (pathmodel.tidy(f.candidate.entry_path), f.candidate.kind_label)
                    for f in before
                ),
            )
        )

    # ---- Older copy winning over a newer one ------------------------------ #
    others = [f for f in on_path_live[1:]] + list(off_path)
    newer: list[Finding] = []
    uncomparable: list[str] = []
    for other in others:
        if other.candidate.canonical and winner.candidate.canonical:
            if other.candidate.canonical == winner.candidate.canonical:
                continue
        if not winner.version or not other.version:
            if other.version or winner.version:
                uncomparable.append(pathmodel.tidy(other.candidate.entry_path))
            continue
        relation = compare_versions(winner.version, other.version)
        if relation is None:
            uncomparable.append(pathmodel.tidy(other.candidate.entry_path))
        elif relation < 0:
            newer.append(other)

    if newer:
        detail = []
        subject = "Hermes runs" if source.kind != pathmodel.CUSTOM_SOURCE else "the name resolves to"
        for other in newer[:3]:
            where = "on PATH" if other.candidate.on_path else "outside PATH"
            detail.append(
                "%s — %s, %s, %s"
                % (
                    pathmodel.tidy(other.candidate.entry_path),
                    other.version,
                    other.origin.label,
                    where,
                )
            )
        if len(newer) > 3:
            detail.append(
                "and %d more newer cop%s" % (len(newer) - 3, "y" if len(newer) - 3 == 1 else "ies")
            )
        verdicts.append(
            Verdict(
                "shadowed_by_older",
                "trap",
                "An older copy of %s wins: %s %s, and a newer copy never gets the chance."
                % (tool, subject, winner.version),
                tuple(detail),
            )
        )
    elif len({f.candidate.canonical for f in on_path_live if f.candidate.canonical}) > 1 or (uncomparable and winner.candidate.canonical):
        distinct = len({f.candidate.canonical for f in on_path_live if f.candidate.canonical}) + len(off_path)
        if distinct > 1:
            if not probed:
                verdicts.append(
                    Verdict(
                        "multiple_copies",
                        "note",
                        "%d separate copies of %s are installed. Versions were not checked, so "
                        "which one is newer is unknown." % (distinct, tool),
                        tuple(
                            pathmodel.tidy(f.candidate.entry_path)
                            for f in [winner] + list(others)
                        ),
                    )
                )
            elif uncomparable:
                verdicts.append(
                    Verdict(
                        "multiple_copies",
                        "warning",
                        "There are %d separate copies of %s, and their version numbers cannot be ordered "
                        "against each other, so I will not claim one is newer." % (distinct, tool),
                        tuple(
                            "%s — %s" % (pathmodel.tidy(f.candidate.entry_path), _version_or_unknown(f))
                            for f in [winner] + list(others)
                        ),
                    )
                )
            else:
                verdicts.append(
                    Verdict(
                        "multiple_copies",
                        "note",
                        "%d separate copies of %s are installed, all reporting the same version."
                        % (distinct, tool),
                        tuple(
                            "%s — %s" % (pathmodel.tidy(f.candidate.entry_path), _version_or_unknown(f))
                            for f in [winner] + list(others)
                        ),
                    )
                )

    # ---- Aliases of one file are not duplicates --------------------------- #
    same_target = [
        f
        for f in on_path_live[1:]
        if f.candidate.canonical and f.candidate.canonical == winner.candidate.canonical
    ]
    if same_target and not newer and not uncomparable:
        verdicts.append(
            Verdict(
                "ok_aliases",
                "note",
                "%d names on PATH all point at the same file, so there is nothing to shadow."
                % (len(same_target) + 1),
                tuple(pathmodel.tidy(f.candidate.entry_path) for f in same_target),
            )
        )

    # ---- Hermes's own copy ------------------------------------------------ #
    if winner.origin.kind == "hermes_managed":
        user_copies = [f for f in others if f.origin.kind != "hermes_managed"]
        if user_copies:
            verdicts.append(
                Verdict(
                    "hermes_managed_winner",
                    "note",
                    "Hermes runs its own copy of %s (%s). Your copy at %s is never used for this name."
                    % (tool, winner.origin.label, pathmodel.tidy(user_copies[0].candidate.entry_path)),
                )
            )
        else:
            verdicts.append(
                Verdict(
                    "hermes_managed_winner",
                    "note",
                    "Hermes runs its own copy of %s (%s), which is the only one installed."
                    % (tool, winner.origin.label),
                )
            )

    # ---- Nothing to say --------------------------------------------------- #
    if not verdicts:
        verdicts.append(
            Verdict(
                "ok_single",
                "ok",
                "One usable copy, nothing shadowing it.",
            )
        )

    # ---- What a terminal would do instead --------------------------------- #
    login_winner = login_findings[0] if login_findings else None
    if login_shell is not None and login_shell.available and login_winner is not None:
        differs = (
            login_winner.candidate.canonical is None
            or winner.candidate.canonical is None
            or login_winner.candidate.canonical != winner.candidate.canonical
        )
        if differs:
            # A different file matters most when it is a different version: two
            # copies of the same release are a curiosity, not a problem.
            changed_version = (
                bool(winner.version)
                and bool(login_winner.version)
                and compare_versions(winner.version, login_winner.version) not in (0, None)
            )
            verdicts.append(
                Verdict(
                    "hermes_vs_terminal",
                    "warning" if changed_version else "note",
                    "Your terminal and Hermes disagree: %s runs %s (%s) in a normal terminal, "
                    "but Hermes runs %s."
                    % (
                        login_shell.label.replace("your login shell", "your shell"),
                        pathmodel.tidy(login_winner.candidate.entry_path),
                        _version_or_unknown(login_winner),
                        pathmodel.tidy(winner.candidate.entry_path),
                    ),
                )
            )

    # ---- A winner with no version ----------------------------------------- #
    if probed and winner.probe is not None and not winner.probe.ok and not cannot_run:
        verdicts.append(
            Verdict(
                "version_unknown",
                "warning",
                "%s answered the version check with nothing usable (%s), so this may not even be "
                "%s." % (pathmodel.tidy(winner.candidate.entry_path), winner.probe.error_hint, tool),
            )
        )

    return _finish(
        tool,
        source,
        winner=winner,
        on_path_live=on_path_live,
        dead_on_path=dead_on_path,
        off_path=off_path,
        login_shell=login_shell,
        login_findings=login_findings,
        verdicts=verdicts,
        host=host,
        probed=probed,
        notes=notes,
        slot_note=slot_note,
        arch_note=arch_note,
        repeated_slots=repeated,
    )


# --------------------------------------------------------------------------- #
# Report assembly


def _primary(verdicts: Sequence[Verdict]) -> Verdict:
    def key(verdict: Verdict) -> tuple:
        rank = SEVERITY_RANK.get(verdict.severity, 0)
        priority = PRIORITY.index(verdict.code) if verdict.code in PRIORITY else len(PRIORITY)
        return (rank, -priority)

    return max(verdicts, key=key)


def _finish(
    tool: str,
    source: PathSource,
    *,
    winner: Finding | None,
    on_path_live: Sequence[Finding],
    dead_on_path: Sequence[Finding],
    off_path: Sequence[Finding],
    login_shell: PathSource | None,
    login_findings: Sequence[Finding],
    verdicts: Sequence[Verdict],
    host: str,
    probed: bool,
    notes: Sequence[str],
    slot_note: str = "",
    arch_note: str | None = None,
    repeated_slots: int = 0,
) -> dict:
    primary = _primary(verdicts)
    custom = source.kind == pathmodel.CUSTOM_SOURCE

    copies: list[str] = []
    index = 0
    aliases: dict[str, list[str]] = {}
    emitted: list[Finding] = []
    for finding in list(on_path_live) + list(dead_on_path) + list(off_path):
        canonical = finding.candidate.canonical
        if canonical and canonical in aliases:
            tidy_path = pathmodel.tidy(finding.candidate.entry_path)
            if tidy_path not in aliases[canonical]:
                aliases[canonical].append(tidy_path)
            continue
        if canonical:
            aliases[canonical] = []
        emitted.append(finding)

    for finding in emitted:
        index += 1
        if finding is winner:
            use_word = "wins here" if custom else "Hermes uses this copy"
        elif not finding.candidate.is_live:
            use_word = "skipped by the shell"
        elif finding.candidate.on_path:
            use_word = "never reached"
        else:
            use_word = "off PATH entirely"
        copies.append(
            _copy_line(
                index,
                finding,
                use_word=use_word,
                aliases=aliases.get(finding.candidate.canonical or "", ()),
            )
        )

    custom = source.kind == pathmodel.CUSTOM_SOURCE
    lines: list[str] = []
    if winner is not None:
        if custom:
            header = "%s — wins in %s: %s" % (
                tool,
                source.label,
                pathmodel.tidy(winner.candidate.entry_path),
            )
        else:
            header = "%s — Hermes runs %s" % (tool, pathmodel.tidy(winner.candidate.entry_path))
        lines.append(header)
        lines.append("")
        facts: list[str] = []
        facts.append(_version_or_unknown(winner))
        facts.append(winner.origin.label)
        if winner.candidate.slot is not None:
            facts.append("PATH %s of %d" % (slot_note, len(source.entries)))
        lines.append(" · ".join(facts))
        if arch_note:
            lines.append("Architecture: %s (%s)." % (winner.arch, arch_note))
        newline_after_facts = True
    else:
        lines.append("%s — not available to Hermes" % tool)
        lines.append("")
        lines.append("Nothing named %s resolves to a program on Hermes's PATH." % tool)
        newline_after_facts = False

    if newline_after_facts:
        lines.append("")

    for verdict in sorted(verdicts, key=lambda v: (-SEVERITY_RANK.get(v.severity, 0), PRIORITY.index(v.code) if v.code in PRIORITY else 99)):
        if verdict.severity == "ok":
            continue
        lines.append("%s %s" % (MARKERS.get(verdict.severity, "•"), verdict.text))
        for detail in verdict.details:
            lines.append("    " + detail)
        lines.append("")

    if copies:
        lines.append("Copies found (%d):" % len(copies))
        lines.extend("  " + line for line in copies)
        lines.append("")

    if repeated_slots:
        lines.append("")
        lines.append(
            "PATH lists %d director%s more than once — only the first position counts."
            % (repeated_slots, "y" if repeated_slots == 1 else "ies")
        )

    if login_shell is not None:
        if login_shell.available:
            login_winner = login_findings[0] if login_findings else None
            if login_winner is not None:
                lines.append(
                    "In %s: %s → %s (%s)."
                    % (
                        login_shell.label,
                        tool,
                        pathmodel.tidy(login_winner.candidate.entry_path),
                        _version_or_unknown(login_winner),
                    )
                )
            else:
                lines.append("In %s: %s is not there at all." % (login_shell.label, tool))
        else:
            lines.append(login_shell.note or "Your login shell's PATH could not be read.")

    for note in notes:
        lines.append(note)

    summary = re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip()) + "\n"

    return {
        "tool": tool,
        "verdict": primary.code,
        "severity": primary.severity,
        "headline": _headline(
            tool,
            primary,
            winner,
            _newer_than(
                winner,
                [f for f in list(on_path_live) + list(off_path) if f is not winner],
            ),
        ),
        "summary": summary,
        "winner": _finding_dict(winner) if winner else None,
        "copies": [_finding_dict(f) for f in list(on_path_live) + list(dead_on_path) + list(off_path)],
        "terminal": _login_dict(login_shell, login_findings),
        "path": source.as_dict(),
        "repeated_path_slots": repeated_slots,
        "host_arch": host,
        "probed": probed,
        "verdicts": [
            {"code": v.code, "severity": v.severity, "text": v.text, "details": list(v.details)}
            for v in verdicts
        ],
    }


def _newer_than(winner: Finding | None, others: Sequence[Finding]) -> list[str]:
    """Version strings of the copies that are newer than the winner, newest first."""
    if winner is None or not winner.version:
        return []
    versions = []
    for other in others:
        if not other.version:
            continue
        if other.candidate.canonical and other.candidate.canonical == winner.candidate.canonical:
            continue
        if compare_versions(winner.version, other.version) == -1:
            versions.append(other.version)
    versions.sort(key=lambda text: _version_sort_key(text), reverse=True)
    return versions


def _version_sort_key(text: str):
    parsed = parse_version_text(text)
    return parsed.numbers if parsed else ()


def _headline(tool: str, primary: Verdict, winner: Finding | None, newer: Sequence[str] = ()) -> str:
    if winner is None:
        return "%s: nothing usable on PATH." % tool
    where = pathmodel.tidy(winner.candidate.entry_path)
    version = winner.version or "version unknown"
    if primary.code == "shadowed_by_older":
        if newer:
            return "%s: an older copy (%s) wins over %s." % (tool, version, newer[0])
        return "%s: %s (%s) wins, and a newer copy exists." % (tool, where, version)
    if primary.code == "winner_cannot_run":
        return "%s: %s cannot run on this Mac." % (tool, where)
    if primary.code == "hermes_vs_terminal":
        return "%s: Hermes runs %s (%s); your terminal runs another copy." % (tool, where, version)
    if primary.code == "skipped_dead_entries":
        return "%s: %s (%s) wins, with a dead entry earlier in PATH." % (tool, where, version)
    if primary.code == "version_unknown":
        return "%s: %s wins but reported no version." % (tool, where)
    if primary.code == "multiple_copies":
        return "%s: %s (%s) wins, with several copies installed." % (tool, where, version)
    if primary.code == "hermes_managed_winner":
        return "%s: Hermes uses its own copy (%s)." % (tool, where)
    if primary.code == "installed_not_on_path":
        return "%s: installed, but not on Hermes's PATH." % tool
    if primary.code == "not_installed":
        return "%s: not installed on Hermes's PATH." % tool
    return "%s: %s (%s) — no conflicts." % (tool, where, version)


def _finding_dict(finding: Finding | None) -> dict | None:
    if finding is None:
        return None
    return {
        "path": pathmodel.tidy(finding.candidate.entry_path),
        "path_raw": finding.candidate.entry_path,
        "version": finding.version,
        "origin": finding.origin.as_dict(),
        "arch": finding.arch,
        "usable": finding.candidate.is_live,
        "on_path": finding.candidate.on_path,
        "path_slot": finding.candidate.slot,
        "candidate": finding.candidate.as_dict(),
        "probe": finding.probe.as_dict() if finding.probe else None,
    }


def _login_dict(
    login_shell: PathSource | None, login_findings: Sequence[Finding]
) -> dict | None:
    if login_shell is None:
        return None
    winner = login_findings[0] if login_findings else None
    return {
        "label": login_shell.label,
        "available": login_shell.available,
        "degraded": login_shell.degraded,
        "note": login_shell.note,
        "entry_count": len(login_shell.entries),
        "winner": _finding_dict(winner) if winner else None,
        "agrees_with_hermes": None,
    }


# --------------------------------------------------------------------------- #
# The environment sweep


def _elide(path: str, width: int = 34) -> str:
    """Shorten a long path by dropping its least informative middle segments."""
    if len(path) <= width:
        return path
    parts = path.split("/")
    while len("/".join(parts)) > width:
        middle = [(index, part) for index, part in enumerate(parts) if 0 < index < len(parts) - 2]
        middle = [(index, part) for index, part in middle if part not in {"…", ""}]
        if not middle:
            break
        index, _ = max(middle, key=lambda item: len(item[1]))
        parts[index] = "…"
    text = "/".join(parts)
    return text if len(text) <= width else text[: width - 1] + "…"


def scan_summary(reports: Sequence[dict], source: PathSource, login_shell: PathSource | None) -> str:
    """One screen: every tool, its winner, and the one thing worth knowing."""
    traps = sum(1 for report in reports if report["severity"] == "trap")
    warnings = sum(1 for report in reports if report["severity"] == "warning")
    notes = sum(1 for report in reports if report["severity"] == "note")
    installed = [report for report in reports if report.get("winner")]
    missing = [report["tool"] for report in reports if not report.get("winner")]

    counts = []
    for number, word in ((traps, "trap"), (warnings, "warning"), (notes, "note")):
        if number:
            counts.append("%d %s%s" % (number, word, "" if number == 1 else "s"))
    tally = " · ".join(counts) if counts else "nothing to report"

    lines = [
        "Checked %d tools against %s (%d entries)."
        % (len(reports), source.label, len(source.entries)),
        "",
        tally + ".",
        "",
    ]

    order = {"trap": 0, "warning": 1, "note": 2, "ok": 3}
    for report in sorted(reports, key=lambda r: (order.get(r["severity"], 9), r["tool"])):
        if not report.get("winner"):
            continue
        winner = report["winner"]
        version = winner.get("version") or "?"
        marker = MARKERS.get(report["severity"], "•")
        path = _elide(winner["path"])
        note = _scan_note(report)
        lines.append(
            ("%-1s %-12s %-10s %-34s %s" % (marker, report["tool"], version[:10], path, note)).rstrip()
        )

    if missing:
        shown = ", ".join(missing[:8])
        more = "" if len(missing) <= 8 else " (and %d more)" % (len(missing) - 8)
        lines.append("")
        lines.append("Not installed: %s%s" % (shown, more))

    if login_shell is not None and login_shell.available:
        disagree = [
            report["tool"]
            for report in reports
            if report.get("terminal")
            and report["terminal"].get("winner")
            and report.get("winner")
            and report["terminal"]["winner"].get("path_raw") != report["winner"].get("path_raw")
        ]
        if disagree:
            lines.append("")
            lines.append(
                "Your terminal resolves these differently: %s. Use which_copy on one of them "
                "for the detail." % ", ".join(disagree[:6])
            )
    elif login_shell is not None:
        lines.append("")
        lines.append(login_shell.note)
    return "\n".join(lines).strip() + "\n"


def _scan_note(report: dict) -> str:
    codes = {verdict["code"] for verdict in report.get("verdicts", [])}
    winner = report.get("winner") or {}
    version = winner.get("version")
    if "shadowed_by_older" in codes:
        return "older copy wins; a newer one is installed"
    if "winner_cannot_run" in codes:
        return "this copy cannot run here"
    if "hermes_vs_terminal" in codes:
        return "your terminal picks a different copy"
    if "skipped_dead_entries" in codes:
        return "a dead PATH entry sits in front of it"
    if "version_unknown" in codes:
        return "reported no version"
    if "multiple_copies" in codes:
        return "several copies, same version"
    if "ok_aliases" in codes:
        return "one file, several names"
    if "hermes_managed_winner" in codes:
        origin = winner.get("origin") or {}
        return origin.get("label") or "Hermes's own copy"
    return ""
