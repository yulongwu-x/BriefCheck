"""Tests for the pull-request workflow and comment publishing."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from briefcheck.action import COMMENT_MARKER, main
from briefcheck.packer import NoLinkedIssueError, ReviewBundle


FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "csv-export"
REVISION = "dcd899c57675bee1b345c6973d6a8a6b171c2242"
REPORT = (FIXTURE / "expected.md").read_text(encoding="utf-8")
BOT = "github-actions[bot]"


class ActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        temp = self.stack.enter_context(TemporaryDirectory())
        root = Path(temp)
        self.event = root / "event.json"
        self.summary = root / "summary.md"
        self.output = root / "output.txt"
        self.set_event("org/repo")
        self.stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "GITHUB_EVENT_NAME": "pull_request",
                    "GITHUB_EVENT_PATH": str(self.event),
                    "GITHUB_REPOSITORY": "org/repo",
                    "GITHUB_STEP_SUMMARY": str(self.summary),
                    "GITHUB_OUTPUT": str(self.output),
                    "GITHUB_TOKEN": "test-github-token",
                    "GITHUB_API_URL": "https://api.github.com",
                    "OPENAI_API_KEY": "test-model-key",
                    "OPENAI_MODEL": "fixture-model",
                    "OPENAI_BASE_URL": "https://model.example/v1",
                    "BRIEFCHECK_API": "chat",
                    "BRIEFCHECK_FAIL_ON": "none",
                    "BRIEFCHECK_ISSUE_NUMBER": "",
                    "BRIEFCHECK_MAX_RETRIES": "0",
                },
            )
        )
        self.bundle = ReviewBundle(
            issue_text=(FIXTURE / "issue.md").read_text(encoding="utf-8"),
            diff_text=(FIXTURE / "change.diff").read_text(encoding="utf-8"),
            revision=REVISION,
        )
        self.fetch = self.stack.enter_context(
            patch("briefcheck.action.fetch_github_bundle", return_value=self.bundle)
        )
        self.github = self.stack.enter_context(patch("briefcheck.action._github_request"))
        self.model = self.stack.enter_context(patch("briefcheck.runner.urlopen"))
        self.set_report(REPORT)

    def set_event(self, head_repo: str) -> None:
        self.event.write_text(
            json.dumps(
                {"pull_request": {"number": 24, "head": {"sha": REVISION, "repo": {"full_name": head_repo}}}}
            ),
            encoding="utf-8",
        )

    def set_report(self, text: str) -> None:
        self.model.return_value = io.BytesIO(
            json.dumps({"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}).encode(
                "utf-8"
            )
        )

    def run_main(self) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main()

    def test_first_review_posts_a_verified_table_and_ignores_other_authors(self) -> None:
        self.set_report(
            "This prose is outside the verified report.\n\n"
            + REPORT.replace("直接使用传入的路径。", "直接使用传入的路径。 @someone")
        )
        self.github.side_effect = [
            json.dumps(
                [{"id": 18, "user": {"login": "alice"}, "body": f"{COMMENT_MARKER}\nOther author"}]
            ),
            json.dumps({"state": "open", "head": {"sha": REVISION}}),
            "{}",
        ]

        self.assertEqual(self.run_main(), 0)

        comment = self.github.call_args
        self.assertTrue(comment.args[0].endswith("/issues/24/comments"))
        self.assertEqual(comment.kwargs["method"], "POST")
        body = comment.kwargs["payload"]["body"]
        self.assertTrue(body.startswith(COMMENT_MARKER))
        self.assertIn("export.py:5–7", body)
        self.assertIn("＠someone", body)
        self.assertNotIn("This prose", body)
        self.assertIn("status=reviewed", self.output.read_text(encoding="utf-8"))
        self.assertIn("BriefCheck review", self.summary.read_text(encoding="utf-8"))

    def test_existing_bot_comment_is_updated_even_when_the_gate_blocks(self) -> None:
        self.github.side_effect = [
            json.dumps(
                [{"id": 19, "user": {"login": BOT}, "body": f"{COMMENT_MARKER}\nPrevious report"}]
            ),
            json.dumps({"state": "open", "head": {"sha": REVISION}}),
            "{}",
        ]
        with patch.dict(os.environ, {"BRIEFCHECK_FAIL_ON": "contradicted"}):
            self.assertEqual(self.run_main(), 2)

        self.assertTrue(self.github.call_args.args[0].endswith("/issues/comments/19"))
        self.assertEqual(self.github.call_args.kwargs["method"], "PATCH")
        self.assertIn("status=blocked", self.output.read_text(encoding="utf-8"))

    def test_a_new_head_prevents_publishing_the_previous_review(self) -> None:
        self.github.side_effect = [
            "[]",
            json.dumps({"state": "open", "head": {"sha": "9" * 40}}),
        ]

        self.assertEqual(self.run_main(), 0)

        self.assertEqual(self.github.call_count, 2)
        self.assertFalse(any("method" in call.kwargs for call in self.github.call_args_list))
        self.assertIn("status=skipped", self.output.read_text(encoding="utf-8"))

    def test_unlinked_issue_skips_before_calling_the_model(self) -> None:
        self.fetch.side_effect = NoLinkedIssueError("Missing Issue")

        self.assertEqual(self.run_main(), 0)

        self.model.assert_not_called()
        self.github.assert_not_called()
        self.assertIn("Link an Issue", self.summary.read_text(encoding="utf-8"))

    def test_forks_are_skipped_before_accessing_secrets_or_api(self) -> None:
        self.set_event("someone/repo")
        with patch.dict(os.environ, {"GITHUB_TOKEN": "", "OPENAI_API_KEY": ""}):
            self.assertEqual(self.run_main(), 0)

        self.fetch.assert_not_called()
        self.model.assert_not_called()
        self.github.assert_not_called()

    def test_invalid_model_report_is_not_posted(self) -> None:
        self.set_report(REPORT.replace("export.py:5–7", "export.py:99999"))

        self.assertEqual(self.run_main(), 1)

        self.github.assert_not_called()
        self.assertIn("status=error", self.output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
