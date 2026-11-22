"""Command-line interface for BriefCheck."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .diff import annotate_diff, parse_unified_diff
from .packer import (
    PackError,
    ReviewBundle,
    fetch_github_bundle,
    parse_pr_ref,
    render_bundle,
    run_git_diff,
    write_bundle_dir,
)
from .verifier import FailGate, verify_report


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
    p_verify.add_argument(
        "--allow-external-files",
        action="store_true",
        help="Downgrade citations to files absent from the diff from error to warning.",
    )
    p_verify.add_argument(
        "--strict-log-revision",
        action="store_true",
        help="Treat a mismatched test-log revision as an error instead of a warning.",
    )
    p_verify.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Fail verification (exit 1) when any warning is emitted.",
    )
    p_verify.add_argument(
        "--fail-on",
        choices=["none", "contradicted", "insufficient", "unresolved"],
        default="none",
        help="Return exit code 2 when a valid report triggers the specified judgment gate.",
    )
    p_verify.add_argument(
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
    p_pack.add_argument(
        "--pr",
        default=None,
        help="GitHub PR reference (`owner/repo#123` or full PR URL).",
    )
    p_pack.add_argument(
        "--issue-number",
        type=int,
        default=None,
        help="Explicit GitHub issue number when using `--pr` (auto-detected from PR body otherwise).",
    )
    p_pack.add_argument(
        "--issue",
        default=None,
        help="Path to a local issue Markdown file.",
    )
    p_pack.add_argument(
        "--diff",
        default=None,
        help="Path to a local unified diff file.",
    )
    p_pack.add_argument(
        "--git-base",
        default=None,
        help="Generate diff locally from `<git-base>...<git-head>` using git.",
    )
    p_pack.add_argument(
        "--git-head",
        default="HEAD",
        help="Head git ref when using `--git-base` (default: HEAD).",
    )
    p_pack.add_argument(
        "--repo-dir",
        default=None,
        help="Repository directory when using `--git-base` (default: current directory).",
    )
    p_pack.add_argument(
        "--test-log",
        default=None,
        help="Optional local test log file to include.",
    )
    p_pack.add_argument(
        "--include-comments",
        action="store_true",
        help="When fetching from GitHub, include issue comments.",
    )
    p_pack.add_argument(
        "--include-checks",
        action="store_true",
        help="When fetching from GitHub, include head-commit Check Runs summary.",
    )
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
    p_pack.add_argument(
        "--token",
        default=None,
        help="Optional GitHub API token (defaults to `GITHUB_TOKEN` or `GH_TOKEN`).",
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


def _cmd_annotate(args: argparse.Namespace) -> int:
    diff_text = _read_text_arg(args.diff)
    parsed = parse_unified_diff(diff_text)
    rendered = annotate_diff(parsed) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


def _cmd_pack(args: argparse.Namespace) -> int:
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


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the `briefcheck` console script."""
    _configure_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "verify":
            return _cmd_verify(args)
        if args.command == "annotate":
            return _cmd_annotate(args)
        if args.command == "pack":
            return _cmd_pack(args)
        parser.error(f"Unknown command: {args.command}")
    except (FileNotFoundError, PackError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
