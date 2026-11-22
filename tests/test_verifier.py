"""Tests for deterministic BriefCheck report verification."""

from __future__ import annotations

from pathlib import Path
import unittest

from briefcheck.verifier import extract_log_revision, revisions_match, verify_report

REPO_ROOT = Path(__file__).resolve().parents[1]


class VerifierTests(unittest.TestCase):
    def test_csv_export_fixture_passes_cleanly(self) -> None:
        base = REPO_ROOT / "examples" / "csv-export"
        result = verify_report(
            (base / "expected.md").read_text(encoding="utf-8"),
            (base / "change.diff").read_text(encoding="utf-8"),
            test_log=(base / "test-run.log").read_text(encoding="utf-8"),
        )
        self.assertTrue(result.is_valid(strict_warnings=True))
        self.assertEqual(result.row_count, 3)
        self.assertEqual(result.citation_count, 3)
        self.assertEqual(
            result.judgment_counts,
            {
                "supported": 1,
                "contradicted": 1,
                "insufficient_evidence": 1,
                "invalid": 0,
            },
        )
        self.assertTrue(result.test_log_revision_matched)
        self.assertTrue(result.gate_triggered("contradicted"))
        self.assertTrue(result.gate_triggered("insufficient"))
        self.assertTrue(result.gate_triggered("unresolved"))
        self.assertFalse(result.gate_triggered("none"))

    def test_prompt_injection_auth_fixture_passes_cleanly(self) -> None:
        base = REPO_ROOT / "examples" / "prompt-injection-auth"
        result = verify_report(
            (base / "expected.md").read_text(encoding="utf-8"),
            (base / "change.diff").read_text(encoding="utf-8"),
        )
        self.assertTrue(result.is_valid(strict_warnings=True))
        self.assertEqual(result.row_count, 2)
        self.assertEqual(result.citation_count, 2)
        self.assertEqual(result.judgment_counts["contradicted"], 1)
        self.assertEqual(result.judgment_counts["supported"], 1)

    def test_retry_backoff_fixture_flags_stale_log_warning_and_strict_error(self) -> None:
        base = REPO_ROOT / "examples" / "retry-backoff"
        report_text = (base / "expected.md").read_text(encoding="utf-8")
        diff_text = (base / "change.diff").read_text(encoding="utf-8")
        log_text = (base / "test-run.log").read_text(encoding="utf-8")

        result = verify_report(report_text, diff_text, test_log=log_text)
        self.assertTrue(result.is_valid())
        self.assertFalse(result.test_log_revision_matched)
        self.assertEqual([w.code for w in result.warnings], ["test_log_revision_mismatch"])

        strict_result = verify_report(
            report_text, diff_text, test_log=log_text, strict_log_revision=True
        )
        self.assertFalse(strict_result.is_valid())
        self.assertEqual([e.code for e in strict_result.errors], ["test_log_revision_mismatch"])

    def test_detects_deleted_line_cited_without_base_label(self) -> None:
        del_diff = """\
diff --git a/auth.py b/auth.py
--- a/auth.py
+++ b/auth.py
@@ -1,4 +1,2 @@
 def guard(user):
-    if not user.is_admin:
-        raise PermissionError()
     return True
"""
        bad_report = """\
| Acceptance requirement | Judgment | Evidence | Follow-up |
| --- | --- | --- | --- |
| Reject non-admins | Contradicted | `auth.py:3` deleted the guard. | Restore guard. |
"""
        result = verify_report(bad_report, del_diff)
        self.assertFalse(result.is_valid())
        self.assertEqual([e.code for e in result.errors], ["deleted_line_cited_as_new"])

        fixed_report = bad_report.replace("`auth.py:3`", "`auth.py:3` (base)")
        fixed_result = verify_report(fixed_report, del_diff)
        self.assertTrue(fixed_result.is_valid(strict_warnings=True))

    def test_detects_unknown_file_out_of_hunk_and_invalid_judgment(self) -> None:
        diff = (REPO_ROOT / "examples" / "csv-export" / "change.diff").read_text(
            encoding="utf-8"
        )
        bad_report = """\
| Acceptance requirement | Judgment | Evidence | Follow-up |
| --- | --- | --- | --- |
| Req A | Partially supported | `ghost.py:1–3` and `export.py:99` | — |
| Req B | Supported | `export.py:8–5` | |
"""
        result = verify_report(bad_report, diff)
        self.assertFalse(result.is_valid())
        codes = {e.code for e in result.errors}
        self.assertIn("invalid_judgment", codes)
        self.assertIn("unknown_file", codes)
        self.assertIn("line_out_of_hunk", codes)
        self.assertIn("invalid_line_range", codes)
        self.assertIn("empty_follow_up", codes)

    def test_allow_external_files_downgrades_unknown_file_to_warning(self) -> None:
        diff = (REPO_ROOT / "examples" / "csv-export" / "change.diff").read_text(
            encoding="utf-8"
        )
        report = """\
| Acceptance requirement | Judgment | Evidence | Follow-up |
| --- | --- | --- | --- |
| Keep auth check | Supported | `routes.py:12` enforces middleware. | — |
"""
        result = verify_report(report, diff, allow_external_files=True)
        self.assertTrue(result.is_valid())
        self.assertEqual([w.code for w in result.warnings], ["external_file_citation"])

    def test_malformed_row_unescaped_pipe(self) -> None:
        diff = (REPO_ROOT / "examples" / "csv-export" / "change.diff").read_text(
            encoding="utf-8"
        )
        report = """\
| Acceptance requirement | Judgment | Evidence | Follow-up |
| --- | --- | --- | --- |
| Handle a | b | Supported | `export.py:5` | — |
"""
        result = verify_report(report, diff)
        self.assertFalse(result.is_valid())
        self.assertTrue(any(e.code == "malformed_row" for e in result.errors))

    def test_revision_helpers(self) -> None:
        self.assertEqual(
            extract_log_revision("Revision (fixture head): dcd899c57675bee1b\n"),
            "dcd899c57675bee1b",
        )
        self.assertIsNone(extract_log_revision("Ran 3 tests in 0.01s\nOK\n"))
        self.assertTrue(revisions_match("dcd899c57675bee1b", "dcd899c"))
        self.assertFalse(revisions_match("dcd899c57675bee1b", "1111111"))


if __name__ == "__main__":
    unittest.main()
