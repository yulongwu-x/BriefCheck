"""Deterministic verification of BriefCheck review reports against unified diffs."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Literal

from .diff import ParsedDiff, format_line_ranges, parse_unified_diff
from .report import ParsedReport, parse_report

Severity = Literal["error", "warning"]
FailGate = Literal["none", "contradicted", "insufficient", "unresolved"]

_LOG_REVISION_RE = re.compile(
    r"(?:revision(?:\s*\([^)]*\))?|commit(?:\s+sha)?|head(?:\s+is\s+now\s+at)?|sha)\s*[:=]?\s*([0-9a-f]{7,40})\b",
    re.IGNORECASE,
)


def extract_log_revision(test_log: str) -> str | None:
    """Extract the first commit/revision SHA declared in a test log."""
    for line in test_log.splitlines()[:40]:
        match = _LOG_REVISION_RE.search(line)
        if match:
            return match.group(1).lower()
    return None


def revisions_match(rev_a: str, rev_b: str) -> bool:
    """Return True if two full or abbreviated hex commit SHAs match."""
    a = rev_a.strip().lower()
    b = rev_b.strip().lower()
    if not a or not b:
        return False
    if len(a) < 7 or len(b) < 7:
        return a == b
    return a.startswith(b) or b.startswith(a)


@dataclass(frozen=True)
class Finding:
    """A single verification error or warning."""

    severity: Severity
    code: str
    message: str
    row: int | None = None
    line: int | None = None
    citation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.row is not None:
            data["row"] = self.row
        if self.line is not None:
            data["line"] = self.line
        if self.citation is not None:
            data["citation"] = self.citation
        return data


@dataclass
class VerificationResult:
    """Aggregate outcome of verifying a BriefCheck report."""

    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    row_count: int = 0
    citation_count: int = 0
    judgment_counts: dict[str, int] = field(
        default_factory=lambda: {
            "supported": 0,
            "contradicted": 0,
            "insufficient_evidence": 0,
            "invalid": 0,
        }
    )
    diff_revision: str | None = None
    test_log_revision: str | None = None
    test_log_revision_matched: bool | None = None

    def is_valid(self, strict_warnings: bool = False) -> bool:
        """Return True if verification passed without blocking findings."""
        if self.errors:
            return False
        if strict_warnings and self.warnings:
            return False
        return True

    def gate_triggered(self, fail_on: FailGate) -> bool:
        """Return True if the report's judgments trip the requested CI gate."""
        if fail_on == "none":
            return False
        if fail_on == "contradicted":
            return self.judgment_counts["contradicted"] > 0
        if fail_on == "insufficient":
            return self.judgment_counts["insufficient_evidence"] > 0
        if fail_on == "unresolved":
            return (
                self.judgment_counts["contradicted"]
                + self.judgment_counts["insufficient_evidence"]
            ) > 0
        return False

    def to_dict(self, strict_warnings: bool = False) -> dict[str, Any]:
        return {
            "valid": self.is_valid(strict_warnings=strict_warnings),
            "row_count": self.row_count,
            "citation_count": self.citation_count,
            "judgments": dict(self.judgment_counts),
            "diff_revision": self.diff_revision,
            "test_log_revision": self.test_log_revision,
            "test_log_revision_matched": self.test_log_revision_matched,
            "errors": [f.to_dict() for f in self.errors],
            "warnings": [f.to_dict() for f in self.warnings],
        }

    def format_text(self, strict_warnings: bool = False) -> str:
        status = "PASS" if self.is_valid(strict_warnings=strict_warnings) else "FAIL"
        lines = [
            f"BriefCheck Verify: {status}",
            (
                f"Rows: {self.row_count} "
                f"(supported={self.judgment_counts['supported']}, "
                f"contradicted={self.judgment_counts['contradicted']}, "
                f"insufficient={self.judgment_counts['insufficient_evidence']}, "
                f"invalid={self.judgment_counts['invalid']})"
            ),
            f"Citations checked: {self.citation_count}",
        ]
        if self.diff_revision or self.test_log_revision:
            rev_bits: list[str] = []
            if self.diff_revision:
                rev_bits.append(f"diff={self.diff_revision[:12]}")
            if self.test_log_revision:
                rev_bits.append(f"test_log={self.test_log_revision[:12]}")
            if self.test_log_revision_matched is not None:
                rev_bits.append(
                    "match=yes" if self.test_log_revision_matched else "match=no"
                )
            lines.append("Revisions: " + ", ".join(rev_bits))

        if self.errors:
            lines.append("")
            lines.append(f"Errors ({len(self.errors)}):")
            for finding in self.errors:
                loc = _format_finding_loc(finding)
                lines.append(f"  - [{finding.code}]{loc} {finding.message}")

        if self.warnings:
            lines.append("")
            lines.append(f"Warnings ({len(self.warnings)}):")
            for finding in self.warnings:
                loc = _format_finding_loc(finding)
                lines.append(f"  - [{finding.code}]{loc} {finding.message}")

        return "\n".join(lines)


def _format_finding_loc(finding: Finding) -> str:
    parts: list[str] = []
    if finding.row is not None:
        parts.append(f"row {finding.row}")
    if finding.line is not None:
        parts.append(f"line {finding.line}")
    if finding.citation:
        parts.append(finding.citation)
    return f" ({', '.join(parts)})" if parts else ""


def verify_report(
    report: str | ParsedReport,
    diff: str | ParsedDiff,
    *,
    test_log: str | None = None,
    revision: str | None = None,
    allow_external_files: bool = False,
    strict_log_revision: bool = False,
) -> VerificationResult:
    """Deterministically verify a BriefCheck report against a diff and optional test log."""
    parsed_report = parse_report(report) if isinstance(report, str) else report
    parsed_diff = parse_unified_diff(diff) if isinstance(diff, str) else diff

    target_revision = revision.strip().lower() if revision else parsed_diff.revision
    result = VerificationResult(diff_revision=target_revision)

    if not parsed_diff.files:
        result.warnings.append(
            Finding(
                severity="warning",
                code="empty_diff",
                message="Unified diff contains no parsed file entries.",
            )
        )

    if not parsed_report.found_table:
        result.errors.append(
            Finding(
                severity="error",
                code="missing_table",
                message="No 4-column BriefCheck Markdown table found in report.",
            )
        )
        return result

    if not parsed_report.rows:
        result.errors.append(
            Finding(
                severity="error",
                code="empty_table",
                message="BriefCheck table has a header but no requirement rows.",
                line=parsed_report.header_line,
            )
        )
        return result

    result.row_count = len(parsed_report.rows)
    available_files = parsed_diff.file_paths()

    for row in parsed_report.rows:
        if row.cell_count != 4:
            result.errors.append(
                Finding(
                    severity="error",
                    code="malformed_row",
                    message=(
                        f"Expected 4 table columns, got {row.cell_count}. "
                        "Escape literal `|` characters inside cells as `\\|`."
                    ),
                    row=row.row_index,
                    line=row.line_number,
                )
            )

        if not row.requirement:
            result.errors.append(
                Finding(
                    severity="error",
                    code="empty_requirement",
                    message="Acceptance requirement cell is empty.",
                    row=row.row_index,
                    line=row.line_number,
                )
            )
        if not row.evidence:
            result.errors.append(
                Finding(
                    severity="error",
                    code="empty_evidence",
                    message="Evidence cell is empty.",
                    row=row.row_index,
                    line=row.line_number,
                )
            )
        if not row.follow_up:
            result.errors.append(
                Finding(
                    severity="error",
                    code="empty_follow_up",
                    message="Follow-up cell is empty (use an em dash `—` when no further check is needed).",
                    row=row.row_index,
                    line=row.line_number,
                )
            )

        if row.judgment is None:
            result.judgment_counts["invalid"] += 1
            result.errors.append(
                Finding(
                    severity="error",
                    code="invalid_judgment",
                    message=(
                        f"Unrecognized judgment {row.judgment_raw!r}. Expected one of: "
                        "Supported / 有证据支持, Contradicted / 明确不符, "
                        "Insufficient evidence / 证据不足."
                    ),
                    row=row.row_index,
                    line=row.line_number,
                )
            )
        else:
            result.judgment_counts[row.judgment] += 1

        if row.judgment in ("supported", "contradicted") and not row.citations and test_log is None:
            result.warnings.append(
                Finding(
                    severity="warning",
                    code="missing_citation",
                    message=(
                        f"Row judged `{row.judgment_raw}` has no `path:line` citation "
                        "and no test log was provided."
                    ),
                    row=row.row_index,
                    line=row.line_number,
                )
            )

        for citation in row.citations:
            result.citation_count += 1
            if citation.start <= 0 or citation.end < citation.start:
                result.errors.append(
                    Finding(
                        severity="error",
                        code="invalid_line_range",
                        message=(
                            f"Invalid line range {citation.start}\u2013{citation.end} "
                            "(lines must be positive and end >= start)."
                        ),
                        row=row.row_index,
                        line=row.line_number,
                        citation=citation.label(),
                    )
                )
                continue

            fdiff = parsed_diff.find_file(citation.path)
            if fdiff is None:
                severity: Severity = "warning" if allow_external_files else "error"
                files_hint = ", ".join(available_files[:6]) if available_files else "none"
                finding = Finding(
                    severity=severity,
                    code="external_file_citation" if allow_external_files else "unknown_file",
                    message=(
                        f"File `{citation.path}` is not present in the diff "
                        f"(diff files: {files_hint})."
                    ),
                    row=row.row_index,
                    line=row.line_number,
                    citation=citation.label(),
                )
                if severity == "error":
                    result.errors.append(finding)
                else:
                    result.warnings.append(finding)
                continue

            if fdiff.is_binary:
                result.errors.append(
                    Finding(
                        severity="error",
                        code="binary_file_citation",
                        message=f"File `{citation.path}` is a binary diff and has no text line numbers.",
                        row=row.row_index,
                        line=row.line_number,
                        citation=citation.label(),
                    )
                )
                continue

            ok, missing = fdiff.has_range(citation.start, citation.end, side=citation.side)
            if not ok:
                if citation.side == "new":
                    old_ok, _ = fdiff.has_range(citation.start, citation.end, side="old")
                    if old_ok:
                        result.errors.append(
                            Finding(
                                severity="error",
                                code="deleted_line_cited_as_new",
                                message=(
                                    f"Line(s) {format_line_ranges(missing)} of `{fdiff.canonical_path}` "
                                    "were deleted and exist only on the base (old) side; "
                                    "label the citation as `base` or cite visible new-side lines."
                                ),
                                row=row.row_index,
                                line=row.line_number,
                                citation=citation.label(),
                            )
                        )
                        continue

                side_label = "new" if citation.side == "new" else "base (old)"
                visible_map = (
                    fdiff.new_line_map() if citation.side == "new" else fdiff.old_line_map()
                )
                visible_str = format_line_ranges(visible_map.keys())
                result.errors.append(
                    Finding(
                        severity="error",
                        code="line_out_of_hunk",
                        message=(
                            f"Line(s) {format_line_ranges(missing)} of `{fdiff.canonical_path}` "
                            f"are not visible in diff hunks on the {side_label} side "
                            f"(visible {side_label} lines: {visible_str})."
                        ),
                        row=row.row_index,
                        line=row.line_number,
                        citation=citation.label(),
                    )
                )

    if test_log is not None:
        log_rev = extract_log_revision(test_log)
        result.test_log_revision = log_rev
        if log_rev is None:
            result.warnings.append(
                Finding(
                    severity="warning",
                    code="test_log_missing_revision",
                    message=(
                        "Supplied test log declares no commit/revision SHA; "
                        "test execution cannot be verified against the reviewed revision."
                    ),
                )
            )
        elif target_revision is not None:
            matched = revisions_match(target_revision, log_rev)
            result.test_log_revision_matched = matched
            if not matched:
                severity = "error" if strict_log_revision else "warning"
                finding = Finding(
                    severity=severity,
                    code="test_log_revision_mismatch",
                    message=(
                        f"Test log revision `{log_rev[:12]}` does not match "
                        f"diff revision `{target_revision[:12]}`."
                    ),
                )
                if severity == "error":
                    result.errors.append(finding)
                else:
                    result.warnings.append(finding)

    return result
