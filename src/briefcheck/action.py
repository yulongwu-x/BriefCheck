"""Run BriefCheck on a GitHub pull request and maintain one review comment."""

from __future__ import annotations

from html import escape
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, cast

from .packer import (
    NoLinkedIssueError,
    PackError,
    PRRef,
    _github_request,
    fetch_github_bundle,
    parse_pr_ref,
)
from .report import parse_report
from .runner import RunError, nonnegative_int, run_review
from .verifier import FailGate, VerificationResult, verify_report


COMMENT_MARKER = "<!-- briefcheck-review -->"
_COMMENT_AUTHOR = "github-actions[bot]"
_CELL_ENTITIES = str.maketrans({"[": "&#91;", "]": "&#93;", "|": "&#124;"})
_MENTION_RE = re.compile(r"(?<![\w./`])@(?![\w.@+/-]+:L?\d+)(?=[A-Za-z0-9])")


class ActionError(RuntimeError):
    """The workflow event or review could not be processed."""


def _append_workflow_file(variable: str, text: str) -> None:
    if path := os.environ.get(variable):
        with Path(path).open("a", encoding="utf-8") as file:
            file.write(text)


def _skip(reason: str) -> int:
    print(f"BriefCheck skipped. {reason}")
    _append_workflow_file("GITHUB_STEP_SUMMARY", f"### BriefCheck skipped\n\n{reason}\n")
    _append_workflow_file("GITHUB_OUTPUT", "status=skipped\n")
    return 0


def _comment_table(report: str) -> str:
    """Render the verified table without surrounding model text or Markdown links."""
    parsed = parse_report(report)

    def row(values: list[str]) -> str:
        cells = [
            _MENTION_RE.sub("＠", escape(value, quote=False).translate(_CELL_ENTITIES))
            for value in values
        ]
        return "| " + " | ".join(cells) + " |"

    lines = [row(parsed.headers), "| --- | --- | --- | --- |"]
    for item in parsed.rows:
        lines.append(row([item.requirement, item.judgment_raw, item.evidence, item.follow_up]))
    return "\n".join(lines) + "\n"


def _validate(result: VerificationResult) -> None:
    if not result.is_valid(strict_warnings=True):
        codes = ", ".join(dict.fromkeys(finding.code for finding in result.errors + result.warnings))
        raise ActionError(f"Report verification failed ({codes}).")


def _find_comment(issue_comments: str, token: str) -> dict[str, Any] | None:
    page = 1
    while True:
        comments = json.loads(
            _github_request(f"{issue_comments}?per_page=100&page={page}", token=token)
        )
        for comment in comments:
            author = (comment.get("user") or {}).get("login")
            body = comment.get("body") or ""
            if (
                author == _COMMENT_AUTHOR
                and body.startswith(COMMENT_MARKER + "\n")
                and type(comment.get("id")) is int
            ):
                return comment
        if len(comments) < 100:
            return None
        page += 1


def _publish_review(pr: PRRef, revision: str, body: str, api_base: str, token: str) -> bool:
    repo_api = f"{api_base}/repos/{pr.owner}/{pr.repo}"
    comments_url = f"{repo_api}/issues/{pr.number}/comments"
    existing = _find_comment(comments_url, token)
    current_pr = json.loads(_github_request(f"{repo_api}/pulls/{pr.number}", token=token))
    if current_pr.get("state") != "open" or (current_pr.get("head") or {}).get("sha") != revision:
        return False

    if existing is None:
        _github_request(comments_url, token=token, method="POST", payload={"body": body})
    elif existing["body"] != body:
        _github_request(
            f"{repo_api}/issues/comments/{existing['id']}",
            token=token,
            method="PATCH",
            payload={"body": body},
        )
    return True


def run_action() -> int:
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        raise ActionError("Use this action in a pull_request workflow.")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not event_path or not repository:
        raise ActionError("The GitHub Actions event path and repository are required.")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pull_request = event.get("pull_request") or {}
    head = pull_request.get("head") or {}
    revision = head.get("sha") or ""
    number = pull_request.get("number")
    if type(number) is not int or number < 1 or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ActionError("The pull_request event must include a PR number and a head SHA.")
    pr = parse_pr_ref(f"{repository}#{number}")
    head_repository = (head.get("repo") or {}).get("full_name") or ""
    if head_repository.casefold() != repository.casefold():
        return _skip("The pull request comes from a fork or its source repository is unavailable.")

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise ActionError("The job must provide its GITHUB_TOKEN to BriefCheck.")
    api_base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    max_retries = nonnegative_int(os.environ.get("BRIEFCHECK_MAX_RETRIES", "1"))
    fail_on = os.environ.get("BRIEFCHECK_FAIL_ON", "none")
    if fail_on not in {"none", "contradicted", "insufficient", "unresolved"}:
        raise ActionError("Use none, contradicted, insufficient, or unresolved for fail-on.")
    issue_value = os.environ.get("BRIEFCHECK_ISSUE_NUMBER", "").strip()
    issue_number = int(issue_value) if issue_value else None
    if issue_number is not None and issue_number < 1:
        raise ActionError("The issue-number input must be a positive integer.")

    # Use the same pack, run, and verify functions as the CLI.
    try:
        bundle = fetch_github_bundle(pr, issue_number=issue_number, token=token, api_base=api_base)
    except NoLinkedIssueError:
        return _skip("Link an Issue in the PR description or set the issue-number input.")
    if bundle.revision != revision:
        return _skip("The PR changed before its review could start.")

    review = run_review(
        bundle,
        api=os.environ.get("BRIEFCHECK_API", "chat"),
        max_retries=max_retries,
        strict_warnings=True,
    )
    _validate(review.verification)
    table = _comment_table(review.report)
    result = verify_report(table, bundle.diff_text, test_log=bundle.test_log_text, revision=revision)
    _validate(result)
    gated = result.gate_triggered(cast(FailGate, fail_on))
    report = f"### BriefCheck review for commit {revision[:12]}\n\n{table}"
    if not _publish_review(pr, revision, f"{COMMENT_MARKER}\n{report}", api_base, token):
        return _skip("The PR changed or closed before the report could be posted.")

    _append_workflow_file("GITHUB_STEP_SUMMARY", report)
    status = "blocked" if gated else "reviewed"
    _append_workflow_file("GITHUB_OUTPUT", f"status={status}\n")
    print(f"BriefCheck published the verified report for {revision[:12]}.")
    if gated:
        print(f"Report triggered the {fail_on} merge gate.", file=sys.stderr)
    return 2 if gated else 0


def main() -> int:
    try:
        return run_action()
    except (ActionError, PackError, RunError, OSError, ValueError) as exc:
        _append_workflow_file("GITHUB_OUTPUT", "status=error\n")
        message = " ".join(str(exc).splitlines())
        print(f"error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
