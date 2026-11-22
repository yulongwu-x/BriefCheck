"""Command-line interface for BriefCheck."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .demo import run_demo
from .diff import annotate_diff, parse_unified_diff
from .packer import (
    PackError,
    ReviewBundle,
    fetch_github_bundle,
    fetch_github_pr_diff,
    parse_pr_ref,
    render_bundle,
    run_git_diff,
    run_git_staged_diff,
    write_bundle_dir,
)
from .runner import RunError, nonnegative_int, run_review
from .verifier import FailGate, verify_citations, verify_report


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _read_text_arg(path_str: str) -> str:
    if path_str == "-":
        return sys.stdin.read()
    path = Path(path_str)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


def _add_verification_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-external-files",
        action="store_true",
        help="Downgrade citations to files absent from the diff from error to warning.",
    )
    parser.add_argument(
        "--strict-log-revision",
        action="store_true",
        help="Treat a mismatched test-log revision as an error instead of a warning.",
    )
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Fail verification (exit 1) when any warning is emitted.",
    )
    parser.add_argument(
        "--fail-on",
        choices=["none", "contradicted", "insufficient", "unresolved"],
        default="none",
        help="Return exit code 2 when a valid report triggers the specified judgment gate.",
    )


def _add_source_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pr",
        default=None,
        help="GitHub PR reference (`owner/repo#123` or full PR URL).",
    )
    parser.add_argument(
        "--issue-number",
        type=int,
        default=None,
        help="Explicit GitHub issue number when using `--pr` (auto-detected from PR body otherwise).",
    )
    parser.add_argument(
        "--issue",
        default=None,
        help="Path to a local issue Markdown file.",
    )
    parser.add_argument(
        "--diff",
        default=None,
        help="Path to a local unified diff file.",
    )
    parser.add_argument(
        "--git-base",
        default=None,
        help="Generate diff locally from `<git-base>...<git-head>` using git.",
    )
    parser.add_argument(
        "--git-head",
        default="HEAD",
        help="Head git ref when using `--git-base` (default: HEAD).",
    )
    parser.add_argument(
        "--repo-dir",
        default=None,
        help="Repository directory when using `--git-base` (default: current directory).",
    )
    parser.add_argument(
        "--test-log",
        default=None,
        help="Optional local test log file to include.",
    )
    parser.add_argument(
        "--include-comments",
        action="store_true",
        help="When fetching from GitHub, include issue comments.",
    )
    parser.add_argument(
        "--include-checks",
        action="store_true",
        help="When fetching from GitHub, include head-commit Check Runs summary.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional GitHub API token (defaults to `GITHUB_TOKEN` or `GH_TOKEN`).",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="briefcheck",
        description=(
            "BriefCheck: verify PR review tables against unified diffs and pack "
            "issue/PR artifacts for evidence-backed acceptance review."
        ),
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"briefcheck {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("demo", help="Run an offline example of diff citation verification.")

    # --- verify ---
    p_verify = subparsers.add_parser(
        "verify",
        help="Deterministically verify a BriefCheck Markdown table against a unified diff.",
    )
    p_verify.add_argument(
        "--report",
        required=True,
        help="Path to the Markdown review report (or `-` to read from stdin).",
    )
    p_verify.add_argument(
        "--diff",
        required=True,
        help="Path to the unified diff file.",
    )
    p_verify.add_argument(
        "--test-log",
        default=None,
        help="Optional test log file to check commit/revision alignment.",
    )
    p_verify.add_argument(
        "--revision",
        default=None,
        help="Optional reviewed commit SHA override (defaults to diff preamble revision).",
    )
    _add_verification_options(p_verify)
    p_verify.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )

    # --- check ---
    p_check = subparsers.add_parser(
        "check",
        help="Verify all `path:line` diff citations in ANY Markdown review (free-form or table).",
    )
    p_check.add_argument(
        "--input",
        default="-",
        help="Path to Markdown review text (defaults to `-` for stdin).",
    )
    p_check.add_argument(
        "--diff",
        default=None,
        help="Path to a local unified diff file.",
    )
    p_check.add_argument(
        "--git-base",
        default=None,
        help="Generate diff locally from `<git-base>...<git-head>` using git.",
    )
    p_check.add_argument(
        "--git-head",
        default="HEAD",
        help="Head git ref when using `--git-base` (default: HEAD).",
    )
    p_check.add_argument(
        "--staged",
        action="store_true",
        help="Verify citations against staged git changes (`git diff --cached`).",
    )
    p_check.add_argument(
        "--repo-dir",
        default=None,
        help="Repository directory when using `--git-base` or `--staged` (default: current directory).",
    )
    p_check.add_argument(
        "--pr",
        default=None,
        help="Fetch the diff directly from a GitHub PR (`owner/repo#123` or URL).",
    )
    p_check.add_argument(
        "--token",
        default=None,
        help="Optional GitHub API token when using `--pr` (defaults to `GITHUB_TOKEN` or `GH_TOKEN`).",
    )
    p_check.add_argument(
        "--test-log",
        default=None,
        help="Optional test log file to check commit/revision alignment.",
    )
    p_check.add_argument(
        "--revision",
        default=None,
        help="Optional reviewed commit SHA override (defaults to diff revision).",
    )
    p_check.add_argument(
        "--allow-external-files",
        action="store_true",
        help="Downgrade citations to files absent from the diff from error to warning.",
    )
    p_check.add_argument(
        "--strict-log-revision",
        action="store_true",
        help="Treat a mismatched test-log revision as an error instead of a warning.",
    )
    p_check.add_argument(
        "--require-citations",
        action="store_true",
        help="Fail (exit 1) when the input contains zero `path:line` citations.",
    )
    p_check.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Fail check (exit 1) when any warning is emitted.",
    )
    p_check.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )

    # --- annotate ---
    p_annotate = subparsers.add_parser(
        "annotate",
        help="Print a unified diff with explicit base (old) and new line numbers.",
    )
    p_annotate.add_argument(
        "diff",
        help="Path to the unified diff file (or `-` to read from stdin).",
    )
    p_annotate.add_argument(
        "-o",
        "--output",
        default=None,
        help="Optional output file path (defaults to stdout).",
    )

    # --- pack ---
    p_pack = subparsers.add_parser(
        "pack",
        help="Assemble issue, diff, and optional test logs into a framed review bundle.",
    )
    _add_source_options(p_pack)
    p_pack.add_argument(
        "--annotate",
        action="store_true",
        help="Append an exact base|new line-numbered diff map to the bundle.",
    )
    p_pack.add_argument(
        "--include-skill",
        action="store_true",
        help="Prepend BriefCheck review instructions for standalone pasting into any LLM.",
    )
    p_pack.add_argument(
        "-o",
        "--output",
        default=None,
        help="Write rendered Markdown bundle to this file (defaults to stdout).",
    )
    p_pack.add_argument(
        "--out-dir",
        default=None,
        help="Write individual files (`issue.md`, `change.diff`, `bundle.md`, `metadata.json`) into this directory.",
    )

    p_run = subparsers.add_parser(
        "run",
        help="Generate and verify an acceptance review with an OpenAI-compatible API.",
    )
    _add_source_options(p_run)
    _add_verification_options(p_run)
    p_run.add_argument("--model", help="Model name (defaults to OPENAI_MODEL).")
    p_run.add_argument(
        "--api", choices=["chat", "responses"], default="chat", help="Model API format."
    )
    p_run.add_argument(
        "--max-retries",
        type=nonnegative_int,
        default=1,
        help="Maximum retries for repairable report errors (default: 1).",
    )
    p_run.add_argument(
        "-o", "--output", help="Write the generated Markdown report to this file."
    )
    p_run.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Write Markdown or the report with verification results as JSON to stdout.",
    )
    return parser


def _cmd_verify(args: argparse.Namespace) -> int:
    report_text = _read_text_arg(args.report)
    diff_text = _read_text_arg(args.diff)
    test_log_text = _read_text_arg(args.test_log) if args.test_log else None

    result = verify_report(
        report_text,
        diff_text,
        test_log=test_log_text,
        revision=args.revision,
        allow_external_files=args.allow_external_files,
        strict_log_revision=args.strict_log_revision,
    )

    if args.format == "json":
        payload = result.to_dict(strict_warnings=args.strict_warnings)
        fail_on: FailGate = args.fail_on
        payload["gate"] = {
            "fail_on": fail_on,
            "triggered": result.gate_triggered(fail_on),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(result.format_text(strict_warnings=args.strict_warnings))

    if not result.is_valid(strict_warnings=args.strict_warnings):
        return 1
    if result.gate_triggered(args.fail_on):
        return 2
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    sources = sum(bool(x) for x in (args.diff, args.git_base, args.staged, args.pr))
    if sources == 0:
        raise PackError(
            "Specify one diff source: `--diff <file>`, `--git-base <ref>`, `--staged`, or `--pr <ref>`."
        )
    if sources > 1:
        raise PackError(
            "Specify only one diff source among `--diff`, `--git-base`, `--staged`, and `--pr`."
        )

    review_text = _read_text_arg(args.input)
    test_log_text = _read_text_arg(args.test_log) if args.test_log else None
    revision = args.revision

    if args.diff:
        diff_text = _read_text_arg(args.diff)
    elif args.git_base:
        cwd = Path(args.repo_dir) if args.repo_dir else None
        diff_text, git_rev = run_git_diff(args.git_base, args.git_head, cwd=cwd)
        revision = revision or git_rev
    elif args.staged:
        cwd = Path(args.repo_dir) if args.repo_dir else None
        diff_text, git_rev = run_git_staged_diff(cwd=cwd)
        revision = revision or git_rev
    else:
        pr_ref = parse_pr_ref(args.pr)
        diff_text, pr_rev = fetch_github_pr_diff(pr_ref, token=args.token)
        revision = revision or pr_rev

    result = verify_citations(
        review_text,
        diff_text,
        test_log=test_log_text,
        revision=revision,
        allow_external_files=args.allow_external_files,
        strict_log_revision=args.strict_log_revision,
        require_citations=args.require_citations,
    )

    if args.format == "json":
        print(
            json.dumps(
                result.to_dict(strict_warnings=args.strict_warnings),
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(result.format_text(strict_warnings=args.strict_warnings))

    return 0 if result.is_valid(strict_warnings=args.strict_warnings) else 1


def _cmd_annotate(args: argparse.Namespace) -> int:
    diff_text = _read_text_arg(args.diff)
    parsed = parse_unified_diff(diff_text)
    rendered = annotate_diff(parsed) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


def _build_review_bundle(args: argparse.Namespace) -> ReviewBundle:
    test_log_text = _read_text_arg(args.test_log) if args.test_log else None
    test_log_source = args.test_log if args.test_log else None

    if args.pr:
        pr_ref = parse_pr_ref(args.pr)
        issue_override = _read_text_arg(args.issue) if args.issue else None
        bundle = fetch_github_bundle(
            pr_ref,
            issue_number=args.issue_number,
            issue_override_text=issue_override,
            issue_override_source=args.issue,
            test_log_text=test_log_text,
            test_log_source=test_log_source,
            include_comments=args.include_comments,
            include_checks=args.include_checks,
            token=args.token,
        )
    else:
        if not args.issue:
            raise PackError("Specify `--issue <file>` or `--pr <owner/repo#num>`.")
        issue_text = _read_text_arg(args.issue)

        if args.diff:
            diff_text = _read_text_arg(args.diff)
            diff_source = args.diff
            revision = parse_unified_diff(diff_text).revision
        elif args.git_base:
            cwd = Path(args.repo_dir) if args.repo_dir else None
            diff_text, revision = run_git_diff(args.git_base, args.git_head, cwd=cwd)
            if revision and not diff_text.startswith("From "):
                diff_text = f"# Revision: {revision}\n" + diff_text
            diff_source = f"git:{args.git_base}...{args.git_head}"
        else:
            raise PackError("Specify `--diff <file>` or `--git-base <ref>` when packing locally.")

        bundle = ReviewBundle(
            issue_text=issue_text,
            diff_text=diff_text,
            test_log_text=test_log_text,
            revision=revision,
            issue_source=args.issue,
            diff_source=diff_source,
            test_log_source=test_log_source,
        )

    return bundle


def _cmd_pack(args: argparse.Namespace) -> int:
    bundle = _build_review_bundle(args)
    if args.out_dir:
        bundle_path = write_bundle_dir(
            bundle,
            Path(args.out_dir),
            include_skill=args.include_skill,
            annotate=args.annotate,
        )
        print(f"Wrote review bundle to {bundle_path}")
        return 0

    rendered = render_bundle(
        bundle,
        include_skill=args.include_skill,
        annotate=args.annotate,
    )
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    review = run_review(
        _build_review_bundle(args),
        model=args.model,
        api=args.api,
        max_retries=args.max_retries,
        allow_external_files=args.allow_external_files,
        strict_log_revision=args.strict_log_revision,
        strict_warnings=args.strict_warnings,
    )
    result = review.verification
    valid = result.is_valid(strict_warnings=args.strict_warnings)
    gate_triggered = valid and result.gate_triggered(args.fail_on)

    if args.output:
        Path(args.output).write_text(review.report, encoding="utf-8")
    if args.format == "json":
        payload = result.to_dict(strict_warnings=args.strict_warnings)
        payload.update(
            report=review.report,
            attempts=review.attempts,
            gate={"fail_on": args.fail_on, "triggered": gate_triggered},
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        if not args.output:
            sys.stdout.write(review.report)
        if not valid:
            print(result.format_text(strict_warnings=args.strict_warnings), file=sys.stderr)

    if not valid:
        return 1
    return 2 if gate_triggered else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the `briefcheck` console script."""
    _configure_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "demo":
            return run_demo()
        if args.command == "verify":
            return _cmd_verify(args)
        if args.command == "check":
            return _cmd_check(args)
        if args.command == "annotate":
            return _cmd_annotate(args)
        if args.command == "pack":
            return _cmd_pack(args)
        if args.command == "run":
            return _cmd_run(args)
        parser.error(f"Unknown command: {args.command}")
    except (OSError, PackError, RunError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
