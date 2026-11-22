"""BriefCheck: evidence-backed PR review against issue acceptance criteria."""

from .diff import DiffHunk, DiffLine, FileDiff, ParsedDiff, annotate_diff, parse_unified_diff
from .report import Citation, ParsedReport, ReportRow, parse_report
from .verifier import Finding, VerificationResult, verify_report

__version__ = "0.3.1"

__all__ = [
    "__version__",
    "Citation",
    "DiffHunk",
    "DiffLine",
    "FileDiff",
    "Finding",
    "ParsedDiff",
    "ParsedReport",
    "ReportRow",
    "VerificationResult",
    "annotate_diff",
    "parse_report",
    "parse_unified_diff",
    "verify_report",
]
