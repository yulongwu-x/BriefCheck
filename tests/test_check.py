"""Tests for free-form Markdown citation checking (`verify_citations` / `briefcheck check`)."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from briefcheck.cli import main
from briefcheck.verifier import verify_citations

REPO_ROOT = Path(__file__).resolve().parents[1]

_SAMPLE_DIFF = """\
From abcdef1234567890abcdef1234567890abcdef12 Mon Sep 17 00:00:00 2001
diff --git a/auth.py b/auth.py
--- a/auth.py
+++ b/auth.py
@@ -1,4 +1,2 @@
 def guard(user):
-    if not user.is_admin:
-        raise PermissionError()
     return True
"""


class FreeformCheckTests(unittest.TestCase):
    def _run_cli(self, argv: list[str], stdin_text: str = "") -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("sys.stdin", io.StringIO(stdin_text)),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_verify_citations_passes_on_valid_freeform_markdown_and_ignores_fences(self) -> None:
        review = """\
### Review summary

- `auth.py:2–3` (base) removes the admin check before returning.
- `auth.py:2` now unconditionally returns `True`.

```text
Example bogus citation inside a code block should be ignored:
ghost.py:999 and auth.py:42
```
"""
        result = verify_citations(review, _SAMPLE_DIFF)
        self.assertEqual(result.mode, "citations")
        self.assertTrue(result.is_valid(strict_warnings=True))
        self.assertEqual(result.citation_count, 2)
        self.assertIn("BriefCheck Check: PASS", result.format_text())
        self.assertNotIn("Rows:", result.format_text())

    def test_verify_citations_catches_deleted_out_of_hunk_and_unknown_files(self) -> None:
        review = """\
Looks risky:
1. Deleted check at `auth.py:3` is missing.
2. Unrelated bug at `auth.py:99` and `missing.py:10`.
"""
        result = verify_citations(review, _SAMPLE_DIFF)
        self.assertFalse(result.is_valid())
        self.assertEqual(result.citation_count, 3)
        codes = [e.code for e in result.errors]
        self.assertEqual(codes, ["deleted_line_cited_as_new", "line_out_of_hunk", "unknown_file"])
        self.assertEqual([e.line for e in result.errors], [2, 3, 3])
        self.assertTrue(all(e.row is None for e in result.errors))

    def test_no_citations_warning_and_require_citations_error(self) -> None:
        review = "LGTM, clean refactor!"
        warn_result = verify_citations(review, _SAMPLE_DIFF)
        self.assertTrue(warn_result.is_valid())
        self.assertEqual([w.code for w in warn_result.warnings], ["no_citations_found"])

        err_result = verify_citations(review, _SAMPLE_DIFF, require_citations=True)
        self.assertFalse(err_result.is_valid())
        self.assertEqual([e.code for e in err_result.errors], ["no_citations_found"])

    def test_cli_check_reads_stdin_by_default_and_outputs_json(self) -> None:
        with TemporaryDirectory() as tmp:
            diff_path = Path(tmp) / "change.diff"
            diff_path.write_text(_SAMPLE_DIFF, encoding="utf-8")

            bad_review = "- Found issue at `auth.py:3` and `auth.py:99`.\n"
            code, out, err = self._run_cli(
                ["check", "--diff", str(diff_path), "--format", "json"],
                stdin_text=bad_review,
            )
            self.assertEqual(code, 1)
            self.assertEqual(err, "")
            payload = json.loads(out)
            self.assertEqual(payload["mode"], "citations")
            self.assertFalse(payload["valid"])
            self.assertEqual(payload["citation_count"], 2)
            self.assertEqual(
                [e["code"] for e in payload["errors"]],
                ["deleted_line_cited_as_new", "line_out_of_hunk"],
            )

            good_review = "- Deleted guard at `auth.py:3` (base); returns at `auth.py:2`.\n"
            code2, out2, err2 = self._run_cli(
                ["check", "--diff", str(diff_path)],
                stdin_text=good_review,
            )
            self.assertEqual((code2, err2), (0, ""))
            self.assertIn("BriefCheck Check: PASS", out2)

    def test_cli_check_supports_git_base_staged_and_pr_sources(self) -> None:
        review = "See `auth.py:2`.\n"
        with patch("briefcheck.cli.run_git_diff", return_value=(_SAMPLE_DIFF, "abcdef1234567")) as m_git:
            code, out, err = self._run_cli(["check", "--git-base", "origin/main"], stdin_text=review)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("BriefCheck Check: PASS", out)
        m_git.assert_called_once()

        with patch("briefcheck.cli.run_git_staged_diff", return_value=(_SAMPLE_DIFF, "abcdef1234567")) as m_staged:
            code, out, err = self._run_cli(["check", "--staged"], stdin_text=review)
        self.assertEqual((code, err), (0, ""))
        m_staged.assert_called_once()

        with patch("briefcheck.cli.fetch_github_pr_diff", return_value=(_SAMPLE_DIFF, "abcdef1234567")) as m_pr:
            code, out, err = self._run_cli(["check", "--pr", "org/repo#12"], stdin_text=review)
        self.assertEqual((code, err), (0, ""))
        m_pr.assert_called_once()

    def test_cli_check_rejects_missing_or_multiple_diff_sources(self) -> None:
        code, _, err = self._run_cli(["check"], stdin_text="See `auth.py:2`.")
        self.assertEqual(code, 1)
        self.assertIn("Specify one diff source", err)

        code2, _, err2 = self._run_cli(
            ["check", "--staged", "--git-base", "origin/main"],
            stdin_text="See `auth.py:2`.",
        )
        self.assertEqual(code2, 1)
        self.assertIn("Specify only one diff source", err2)


if __name__ == "__main__":
    unittest.main()
