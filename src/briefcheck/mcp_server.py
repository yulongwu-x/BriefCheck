"""Zero-dependency Model Context Protocol (MCP) stdio server for BriefCheck."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, TextIO

from . import __version__
from .diff import annotate_diff, parse_unified_diff
from .packer import (
    PackError,
    ReviewBundle,
    fetch_github_bundle,
    fetch_github_pr_comments,
    fetch_github_pr_diff,
    parse_pr_ref,
    render_bundle,
    run_git_diff,
    run_git_staged_diff,
)
from .verifier import FailGate, verify_citations, verify_report

_SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
_DEFAULT_PROTOCOL_VERSION = "2025-03-26"

_DIFF_SOURCE_PROPERTIES: dict[str, Any] = {
    "diff": {
        "type": "string",
        "description": "Raw unified diff text.",
    },
    "git_base": {
        "type": "string",
        "description": "Local git base ref (e.g. `origin/main`) to diff against `git_head`.",
    },
    "git_head": {
        "type": "string",
        "description": "Local git head ref when using `git_base` (defaults to `HEAD`).",
    },
    "staged": {
        "type": "boolean",
        "description": "When true, read staged git changes (`git diff --cached`).",
    },
    "repo_dir": {
        "type": "string",
        "description": "Optional local repository path for `git_base` or `staged`.",
    },
    "pr": {
        "type": "string",
        "description": "GitHub PR reference (`owner/repo#123` or full PR URL).",
    },
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "briefcheck_annotate_diff",
        "description": (
            "Render a unified diff (or local git diff / staged changes / GitHub PR) with "
            "explicit `base | new` line numbers for every hunk line so citations never drift."
        ),
        "inputSchema": {
            "type": "object",
            "properties": dict(_DIFF_SOURCE_PROPERTIES),
            "additionalProperties": False,
        },
    },
    {
        "name": "briefcheck_check_citations",
        "description": (
            "Deterministically verify every `path:line`, `path:start-end`, `path:line:col`, "
            "and `path#Lline` diff citation in any free-form Markdown PR review (or existing "
            "GitHub PR comments when `pr_comments` is true)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "review_text": {
                    "type": "string",
                    "description": "Markdown review text whose citations should be verified.",
                },
                **_DIFF_SOURCE_PROPERTIES,
                "pr_comments": {
                    "type": "boolean",
                    "description": "When true with `pr`, fetch and audit existing comments/reviews on that PR.",
                },
                "author": {
                    "type": "string",
                    "description": "Optional GitHub login filter when `pr_comments` is true (e.g. `coderabbitai[bot]`).",
                },
                "test_log": {
                    "type": "string",
                    "description": "Optional test log text to verify commit revision alignment.",
                },
                "revision": {
                    "type": "string",
                    "description": "Optional reviewed commit SHA override.",
                },
                "allow_external_files": {
                    "type": "boolean",
                    "description": "Downgrade citations to files absent from the diff from error to warning.",
                },
                "strict_log_revision": {
                    "type": "boolean",
                    "description": "Treat mismatched test-log revisions as errors instead of warnings.",
                },
                "require_citations": {
                    "type": "boolean",
                    "description": "Fail when zero diff citations are found in the review text.",
                },
                "strict_warnings": {
                    "type": "boolean",
                    "description": "Fail when any warning is emitted.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "briefcheck_verify_report",
        "description": (
            "Deterministically verify a 4-column BriefCheck acceptance-criteria Markdown table "
            "(structure, canonical English/Chinese judgments, exact base/new diff hunk citations, "
            "and optional test-log commit alignment)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_text": {
                    "type": "string",
                    "description": "Markdown report containing a 4-column BriefCheck review table.",
                },
                **_DIFF_SOURCE_PROPERTIES,
                "test_log": {
                    "type": "string",
                    "description": "Optional test log text to check revision alignment.",
                },
                "revision": {
                    "type": "string",
                    "description": "Optional reviewed commit SHA override.",
                },
                "allow_external_files": {
                    "type": "boolean",
                    "description": "Downgrade citations to files absent from the diff from error to warning.",
                },
                "strict_log_revision": {
                    "type": "boolean",
                    "description": "Treat mismatched test-log revisions as errors instead of warnings.",
                },
                "strict_warnings": {
                    "type": "boolean",
                    "description": "Fail when any warning is emitted.",
                },
                "fail_on": {
                    "type": "string",
                    "enum": ["none", "contradicted", "insufficient", "unresolved"],
                    "description": "Optional CI judgment gate policy (default: `none`).",
                },
            },
            "required": ["report_text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "briefcheck_pack_review",
        "description": (
            "Assemble an issue, unified diff, and optional test log from local inputs or a "
            "GitHub PR (with auto-discovered linked issues) into a prompt-injection-framed "
            "review bundle with optional `base | new` annotated line map."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pr": {
                    "type": "string",
                    "description": "GitHub PR reference (`owner/repo#123` or URL).",
                },
                "issue_number": {
                    "type": "integer",
                    "description": "Explicit GitHub issue number when using `pr`.",
                },
                "include_comments": {
                    "type": "boolean",
                    "description": "Include issue comments when fetching from GitHub.",
                },
                "include_checks": {
                    "type": "boolean",
                    "description": "Include head-commit Check Runs summary when fetching from GitHub.",
                },
                "issue_text": {
                    "type": "string",
                    "description": "Issue Markdown text (required when not using `pr`, or overrides GitHub issue).",
                },
                "diff": {
                    "type": "string",
                    "description": "Raw unified diff text when packing locally.",
                },
                "git_base": {
                    "type": "string",
                    "description": "Local git base ref when packing locally.",
                },
                "git_head": {
                    "type": "string",
                    "description": "Local git head ref (default: `HEAD`).",
                },
                "repo_dir": {
                    "type": "string",
                    "description": "Optional local repository path for `git_base`.",
                },
                "test_log": {
                    "type": "string",
                    "description": "Optional test log text to include.",
                },
                "annotate": {
                    "type": "boolean",
                    "description": "Append an explicit `base | new` annotated diff map (default: true).",
                },
                "include_skill": {
                    "type": "boolean",
                    "description": "Prepend BriefCheck review instructions (default: false).",
                },
            },
            "additionalProperties": False,
        },
    },
]


def _resolve_diff_source(args: dict[str, Any]) -> tuple[str, str | None]:
    diff_text = args.get("diff")
    git_base = args.get("git_base")
    staged = bool(args.get("staged", False))
    pr = args.get("pr")

    sources = sum(bool(x) for x in (diff_text is not None and diff_text != "", git_base, staged, pr))
    if sources == 0:
        raise PackError(
            "Specify one diff source: `diff`, `git_base`, `staged: true`, or `pr`."
        )
    if sources > 1:
        raise PackError(
            "Specify only one diff source among `diff`, `git_base`, `staged`, and `pr`."
        )

    repo_dir = Path(str(args["repo_dir"])) if args.get("repo_dir") else None
    if diff_text is not None and diff_text != "":
        if not isinstance(diff_text, str):
            raise PackError("`diff` must be a string.")
        return diff_text, parse_unified_diff(diff_text).revision
    if git_base:
        git_head = str(args.get("git_head") or "HEAD")
        return run_git_diff(str(git_base), git_head, cwd=repo_dir)
    if staged:
        return run_git_staged_diff(cwd=repo_dir)
    pr_ref = parse_pr_ref(str(pr))
    return fetch_github_pr_diff(pr_ref)


def _call_tool(name: str, args: dict[str, Any]) -> tuple[str, bool]:
    if name == "briefcheck_annotate_diff":
        diff_text, revision = _resolve_diff_source(args)
        parsed = parse_unified_diff(diff_text)
        if revision and not parsed.revision:
            parsed.revision = revision
        return annotate_diff(parsed), False

    if name == "briefcheck_check_citations":
        pr_comments = bool(args.get("pr_comments", False))
        author = args.get("author")
        review_text = args.get("review_text")
        comments_checked: int | None = None

        if pr_comments:
            if not args.get("pr"):
                raise PackError("`pr_comments: true` requires `pr` (`owner/repo#123` or URL).")
            if review_text:
                raise PackError("Pass either `review_text` or `pr_comments: true`, not both.")
            pr_ref = parse_pr_ref(str(args["pr"]))
            review_text, comments_checked = fetch_github_pr_comments(
                pr_ref,
                author=str(author) if author else None,
            )
        elif not isinstance(review_text, str):
            raise PackError("`review_text` must be a string (or set `pr_comments: true` with `pr`).")

        diff_text, resolved_rev = _resolve_diff_source(args)
        revision = str(args["revision"]) if args.get("revision") else resolved_rev
        strict_warnings = bool(args.get("strict_warnings", False))
        result = verify_citations(
            review_text,
            diff_text,
            test_log=str(args["test_log"]) if args.get("test_log") is not None else None,
            revision=revision,
            allow_external_files=bool(args.get("allow_external_files", False)),
            strict_log_revision=bool(args.get("strict_log_revision", False)),
            require_citations=bool(args.get("require_citations", False)),
        )
        payload = result.to_dict(strict_warnings=strict_warnings)
        if comments_checked is not None:
            payload["pr_comments_checked"] = comments_checked
        payload["summary"] = result.format_text(strict_warnings=strict_warnings)
        return json.dumps(payload, indent=2, ensure_ascii=False), False

    if name == "briefcheck_verify_report":
        report_text = args.get("report_text")
        if not isinstance(report_text, str):
            raise PackError("`report_text` must be a string.")
        diff_text, resolved_rev = _resolve_diff_source(args)
        revision = str(args["revision"]) if args.get("revision") else resolved_rev
        strict_warnings = bool(args.get("strict_warnings", False))
        fail_on = str(args.get("fail_on") or "none")
        if fail_on not in ("none", "contradicted", "insufficient", "unresolved"):
            raise PackError("`fail_on` must be one of none, contradicted, insufficient, unresolved.")
        result = verify_report(
            report_text,
            diff_text,
            test_log=str(args["test_log"]) if args.get("test_log") is not None else None,
            revision=revision,
            allow_external_files=bool(args.get("allow_external_files", False)),
            strict_log_revision=bool(args.get("strict_log_revision", False)),
        )
        payload = result.to_dict(strict_warnings=strict_warnings)
        gate_policy: FailGate = fail_on  # type: ignore[assignment]
        payload["gate"] = {
            "fail_on": gate_policy,
            "triggered": result.gate_triggered(gate_policy),
        }
        payload["summary"] = result.format_text(strict_warnings=strict_warnings)
        return json.dumps(payload, indent=2, ensure_ascii=False), False

    if name == "briefcheck_pack_review":
        annotate = bool(args.get("annotate", True))
        include_skill = bool(args.get("include_skill", False))
        test_log = str(args["test_log"]) if args.get("test_log") is not None else None
        if args.get("pr"):
            pr_ref = parse_pr_ref(str(args["pr"]))
            issue_num = args.get("issue_number")
            if issue_num is not None and (type(issue_num) is not int or issue_num < 1):
                raise PackError("`issue_number` must be a positive integer.")
            issue_override = str(args["issue_text"]) if args.get("issue_text") is not None else None
            bundle = fetch_github_bundle(
                pr_ref,
                issue_number=issue_num,
                issue_override_text=issue_override,
                issue_override_source="mcp:issue_text" if issue_override is not None else None,
                test_log_text=test_log,
                test_log_source="mcp:test_log" if test_log is not None else None,
                include_comments=bool(args.get("include_comments", False)),
                include_checks=bool(args.get("include_checks", False)),
            )
        else:
            issue_text = args.get("issue_text")
            if not isinstance(issue_text, str) or not issue_text.strip():
                raise PackError("Specify `issue_text` or `pr`.")
            diff_text, revision = _resolve_diff_source(args)
            if revision and not diff_text.startswith("From "):
                diff_text = f"# Revision: {revision}\n" + diff_text
            diff_source = (
                f"git:{args['git_base']}...{args.get('git_head') or 'HEAD'}"
                if args.get("git_base")
                else "git:staged"
                if args.get("staged")
                else "mcp:diff"
            )
            bundle = ReviewBundle(
                issue_text=issue_text,
                diff_text=diff_text,
                test_log_text=test_log,
                revision=revision,
                issue_source="mcp:issue_text",
                diff_source=diff_source,
                test_log_source="mcp:test_log" if test_log is not None else None,
            )
        return render_bundle(bundle, include_skill=include_skill, annotate=annotate), False

    raise KeyError(name)


def _error_response(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }


def handle_jsonrpc_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Process one parsed JSON-RPC 2.0 request/notification and return an optional reply."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error_response(None, -32600, "Invalid Request: expected JSON-RPC 2.0 object.")

    method = message.get("method")
    msg_id = message.get("id")
    is_notification = "id" not in message

    if not isinstance(method, str):
        if is_notification:
            return None
        return _error_response(msg_id, -32600, "Invalid Request: missing string `method`.")

    if method.startswith("notifications/"):
        return None

    params = message.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        if is_notification:
            return None
        return _error_response(msg_id, -32602, "Invalid params: expected JSON object.")

    if method == "initialize":
        requested = params.get("protocolVersion")
        protocol_version = (
            requested if isinstance(requested, str) and requested in _SUPPORTED_PROTOCOL_VERSIONS
            else _DEFAULT_PROTOCOL_VERSION
        )
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "briefcheck", "version": __version__},
                "instructions": (
                    "Use BriefCheck tools to annotate unified diffs with exact base|new line "
                    "numbers before citing lines, and deterministically verify citations or "
                    "acceptance tables against the real diff before posting a review."
                ),
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOL_DEFINITIONS}}

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments")
        if not isinstance(tool_name, str):
            return _error_response(msg_id, -32602, "Invalid params: `name` must be a string.")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _error_response(msg_id, -32602, "Invalid params: `arguments` must be an object.")
        try:
            text, is_error = _call_tool(tool_name, arguments)
        except KeyError:
            return _error_response(msg_id, -32602, f"Unknown tool: {tool_name}")
        except (PackError, OSError, ValueError) as exc:
            text, is_error = f"error: {exc}", True
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_error,
            },
        }

    if is_notification:
        return None
    return _error_response(msg_id, -32601, f"Method not found: {method}")


def serve_stdio(
    in_stream: TextIO | None = None,
    out_stream: TextIO | None = None,
) -> int:
    """Run the BriefCheck MCP server over newline-delimited JSON-RPC 2.0 stdio."""
    reader = in_stream if in_stream is not None else sys.stdin
    writer = out_stream if out_stream is not None else sys.stdout

    for raw_line in reader:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response: dict[str, Any] | None = _error_response(
                None, -32700, f"Parse error: {exc.msg}"
            )
        else:
            response = handle_jsonrpc_message(message)

        if response is not None:
            writer.write(json.dumps(response, ensure_ascii=False) + "\n")
            writer.flush()
    return 0
