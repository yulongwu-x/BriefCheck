"""End-to-end tests for the BriefCheck CLI."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from briefcheck.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_demo_shows_rejected_and_corrected_citations(self) -> None:
        code, out, err = self._run_cli(["demo"])
        self.assertEqual((code, err), (0, ""))
        failed, passed = out.split("After marking", 1)
        self.assertIn("BriefCheck Verify: FAIL", failed)
        self.assertIn("[deleted_line_cited_as_new]", failed)
        self.assertIn("[line_out_of_hunk]", failed)
        self.assertIn("BriefCheck Verify: PASS", passed)
        self.assertIn("contradicted=1", passed)

    def test_verify_json_and_fail_on_gate(self) -> None:
        base = REPO_ROOT / "examples" / "csv-export"
        code, out, err = self._run_cli(
            [
                "verify",
                "--report",
                str(base / "expected.md"),
                "--diff",
                str(base / "change.diff"),
                "--test-log",
                str(base / "test-run.log"),
                "--format",
                "json",
                "--fail-on",
                "contradicted",
            ]
        )
        self.assertEqual(err, "")
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertTrue(payload["valid"])
        self.assertTrue(payload["gate"]["triggered"])
        self.assertEqual(payload["judgments"]["contradicted"], 1)

    def test_annotate_writes_output_file(self) -> None:
        diff_path = REPO_ROOT / "examples" / "csv-export" / "change.diff"
        with TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "annotated.txt"
            code, _, err = self._run_cli(["annotate", str(diff_path), "-o", str(out_path)])
            self.assertEqual(code, 0)
            self.assertEqual(err, "")
            content = out_path.read_text(encoding="utf-8")
            self.assertIn("=== export.py (modified) ===", content)
            self.assertIn("base     6 | new     - | -", content)

    def test_pack_local_to_out_dir(self) -> None:
        base = REPO_ROOT / "examples" / "csv-export"
        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "packed"
            code, out, err = self._run_cli(
                [
                    "pack",
                    "--issue",
                    str(base / "issue.md"),
                    "--diff",
                    str(base / "change.diff"),
                    "--test-log",
                    str(base / "test-run.log"),
                    "--annotate",
                    "--include-skill",
                    "--out-dir",
                    str(out_dir),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(err, "")
            self.assertIn("Wrote review bundle", out)
            bundle_text = (out_dir / "bundle.md").read_text(encoding="utf-8")
            self.assertIn("<untrusted_artifact kind=\"issue\"", bundle_text)
            self.assertIn("## Annotated Diff Line Map (base | new)", bundle_text)

    def _run_arguments(self) -> list[str]:
        fixture = REPO_ROOT / "examples" / "csv-export"
        return [
            "run", "--issue", str(fixture / "issue.md"), "--diff", str(fixture / "change.diff"),
            "--test-log", str(fixture / "test-run.log"), "--model", "test-model",
        ]

    def test_run_writes_markdown_and_json_before_returning_gate_code(self) -> None:
        report = (REPO_ROOT / "examples" / "csv-export" / "expected.md").read_text(encoding="utf-8")
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": report}}]}).encode("utf-8"))
        with TemporaryDirectory() as directory:
            target = Path(directory) / "review.md"
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
                with patch("briefcheck.runner.urlopen", return_value=response) as request:
                    code, out, err = self._run_cli(
                        self._run_arguments()
                        + ["--output", str(target), "--format", "json", "--fail-on", "contradicted"]
                    )

            self.assertEqual(code, 2)
            self.assertEqual(err, "")
            payload = json.loads(out)
            self.assertTrue(payload["valid"])
            self.assertTrue(payload["gate"]["triggered"])
            self.assertEqual(payload["attempts"], 1)
            self.assertEqual(target.read_text(encoding="utf-8"), payload["report"])
            request.assert_called_once()

    def test_run_invalid_report_returns_json_error_after_repair_limit(self) -> None:
        content = json.dumps({"choices": [{"message": {"content": "No table here."}}]}).encode("utf-8")
        responses = [io.BytesIO(content), io.BytesIO(content)]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch("briefcheck.runner.urlopen", side_effect=responses) as request:
                code, out, err = self._run_cli(self._run_arguments() + ["--format", "json"])

        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["attempts"], 2)
        self.assertEqual(payload["errors"][0]["code"], "missing_table")
        self.assertEqual(request.call_count, 2)

    def test_run_api_failure_returns_exit_code_1(self) -> None:
        error = HTTPError("https://model.example/v1/chat/completions", 401, "Unauthorized", None, None)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch("briefcheck.runner.urlopen", side_effect=error) as request:
                code, out, err = self._run_cli(self._run_arguments())

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("HTTP 401", err)
        self.assertNotIn("test-key", err)
        request.assert_called_once()

    def test_missing_file_returns_exit_code_1(self) -> None:
        code, _, err = self._run_cli(["annotate", "does-not-exist.diff"])
        self.assertEqual(code, 1)
        self.assertIn("File not found", err)


if __name__ == "__main__":
    unittest.main()
