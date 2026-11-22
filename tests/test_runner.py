"""Tests for the model request, verification, and repair loop."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from briefcheck.packer import ReviewBundle
from briefcheck.runner import RunError, run_review


FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "csv-export"
REPORT = (FIXTURE / "expected.md").read_text(encoding="utf-8").strip() + "\n"
BAD_REPORT = REPORT.replace("export.py:5–7", "export.py:99999")
ENVIRONMENT = {
    "OPENAI_API_KEY": "test-key",
    "OPENAI_BASE_URL": "https://model.example/v1/",
    "OPENAI_MODEL": "fixture-model",
}


def chat_response(report: str) -> io.BytesIO:
    payload = {"choices": [{"message": {"content": report}, "finish_reason": "stop"}]}
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.bundle = ReviewBundle(
            issue_text=(FIXTURE / "issue.md").read_text(encoding="utf-8"),
            diff_text=(FIXTURE / "change.diff").read_text(encoding="utf-8"),
            test_log_text=(FIXTURE / "test-run.log").read_text(encoding="utf-8"),
        )
        self.stack.enter_context(patch.dict(os.environ, ENVIRONMENT))
        self.urlopen = self.stack.enter_context(patch("briefcheck.runner.urlopen"))

    def test_chat_retries_an_invalid_citation_with_specific_feedback(self) -> None:
        self.urlopen.side_effect = [chat_response(BAD_REPORT), chat_response(REPORT)]

        result = run_review(self.bundle)

        self.assertTrue(result.verification.is_valid())
        self.assertEqual(result.report, REPORT)
        self.assertEqual(result.attempts, 2)
        initial, repair = [call.args[0] for call in self.urlopen.call_args_list]
        self.assertEqual(initial.full_url, "https://model.example/v1/chat/completions")
        self.assertEqual(initial.get_header("Authorization"), "Bearer test-key")
        payload = json.loads(initial.data)
        self.assertEqual(payload["model"], "fixture-model")
        self.assertIn("Annotated Diff Line Map", payload["messages"][1]["content"])
        self.assertIn("<untrusted_artifact", payload["messages"][1]["content"])
        self.assertNotIn("test-key", initial.data.decode("utf-8"))
        feedback = json.loads(repair.data)["messages"][-1]["content"]
        self.assertIn("line_out_of_hunk", feedback)
        self.assertIn("export.py:99999", feedback)

    def test_large_out_of_hunk_range_returns_a_finding(self) -> None:
        oversized = REPORT.replace("export.py:5–7", "export.py:1–1000000000")
        self.urlopen.return_value = chat_response(oversized)

        result = run_review(self.bundle, max_retries=0)

        self.assertEqual(result.verification.errors[0].code, "line_out_of_hunk")

    def test_report_format_failure_obeys_max_retries(self) -> None:
        self.urlopen.return_value = chat_response("No table")

        result = run_review(self.bundle, max_retries=0)

        self.assertFalse(result.verification.is_valid())
        self.assertEqual(result.verification.errors[0].code, "missing_table")
        self.assertEqual(result.attempts, 1)
        self.urlopen.assert_called_once()

    def test_stale_log_is_an_input_error_and_does_not_trigger_repair(self) -> None:
        self.urlopen.return_value = chat_response(REPORT)
        stale = replace(self.bundle, test_log_text="Revision: 1111111222222\nOK\n")

        result = run_review(stale, strict_log_revision=True)

        self.assertEqual(result.verification.errors[0].code, "test_log_revision_mismatch")
        self.assertEqual(result.attempts, 1)
        self.urlopen.assert_called_once()

    def test_responses_parses_message_parts_without_tools(self) -> None:
        self.urlopen.return_value = io.BytesIO(
            json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {"type": "reasoning"},
                        {"type": "message", "content": [{"type": "output_text", "text": REPORT}]},
                    ],
                }
            ).encode("utf-8")
        )

        result = run_review(self.bundle, api="responses", model="explicit-model")

        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://model.example/v1/responses")
        self.assertEqual(result.report, REPORT)
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "explicit-model")
        self.assertIn("Return only the review table", payload["instructions"])
        self.assertEqual(payload["input"][0]["role"], "user")
        self.assertNotIn("tools", payload)
        self.assertFalse(payload["store"])

    def test_http_error_is_reported_without_the_provider_body_or_retry(self) -> None:
        self.urlopen.side_effect = HTTPError(
            "https://model.example/v1/chat/completions", 429, "Limited", None,
            io.BytesIO(b"error payload from the provider"),
        )
        with self.assertRaisesRegex(RunError, "HTTP 429") as raised:
            run_review(self.bundle)

        self.assertNotIn("error payload", str(raised.exception))
        self.urlopen.assert_called_once()

    def test_missing_key_fails_without_network(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": " "}):
            with self.assertRaisesRegex(RunError, "OPENAI_API_KEY"):
                run_review(self.bundle)
        self.urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
