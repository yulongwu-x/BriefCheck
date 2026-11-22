"""End-to-end tests for the BriefCheck CLI."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from briefcheck.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

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

    def test_missing_file_returns_exit_code_1(self) -> None:
        code, _, err = self._run_cli(["annotate", "does-not-exist.diff"])
        self.assertEqual(code, 1)
        self.assertIn("File not found", err)


if __name__ == "__main__":
    unittest.main()
