"""Tests for the zero-dependency BriefCheck MCP stdio server."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from briefcheck import __version__
from briefcheck.mcp_server import handle_jsonrpc_message, serve_stdio

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

_SAMPLE_REPORT = """\
| Acceptance requirement | Judgment | Evidence | Follow-up |
| --- | --- | --- | --- |
| Reject non-admins | Contradicted | `auth.py:2–3` (base) removed guard; `auth.py:2` returns True. | Restore guard. |
"""


class McpServerTests(unittest.TestCase):
    def test_initialize_negotiates_protocol_and_reports_capabilities(self) -> None:
        resp = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            }
        )
        assert resp is not None
        self.assertEqual(resp["id"], 1)
        result = resp["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"], {"name": "briefcheck", "version": __version__})
        self.assertIn("tools", result["capabilities"])

    def test_notifications_return_none_and_ping_succeeds(self) -> None:
        self.assertIsNone(
            handle_jsonrpc_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )
        ping = handle_jsonrpc_message({"jsonrpc": "2.0", "id": "p1", "method": "ping"})
        self.assertEqual(ping, {"jsonrpc": "2.0", "id": "p1", "result": {}})

    def test_tools_list_exposes_all_four_briefcheck_tools(self) -> None:
        resp = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert resp is not None
        names = [tool["name"] for tool in resp["result"]["tools"]]
        self.assertEqual(
            names,
            [
                "briefcheck_annotate_diff",
                "briefcheck_check_citations",
                "briefcheck_verify_report",
                "briefcheck_pack_review",
            ],
        )

    def test_call_annotate_check_verify_and_pack(self) -> None:
        ann = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "briefcheck_annotate_diff", "arguments": {"diff": _SAMPLE_DIFF}},
            }
        )
        assert ann is not None
        self.assertFalse(ann["result"]["isError"])
        ann_text = ann["result"]["content"][0]["text"]
        self.assertIn("base     3 | new     - | -", ann_text)

        bad_check = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "briefcheck_check_citations",
                    "arguments": {
                        "review_text": "Look at `auth.py:3` and `auth.py#L99`.",
                        "diff": _SAMPLE_DIFF,
                    },
                },
            }
        )
        assert bad_check is not None
        self.assertFalse(bad_check["result"]["isError"])
        bad_payload = json.loads(bad_check["result"]["content"][0]["text"])
        self.assertFalse(bad_payload["valid"])
        self.assertEqual(
            [e["code"] for e in bad_payload["errors"]],
            ["deleted_line_cited_as_new", "line_out_of_hunk"],
        )

        verified = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "briefcheck_verify_report",
                    "arguments": {
                        "report_text": _SAMPLE_REPORT,
                        "diff": _SAMPLE_DIFF,
                        "fail_on": "contradicted",
                    },
                },
            }
        )
        assert verified is not None
        ver_payload = json.loads(verified["result"]["content"][0]["text"])
        self.assertTrue(ver_payload["valid"])
        self.assertTrue(ver_payload["gate"]["triggered"])

        packed = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "briefcheck_pack_review",
                    "arguments": {
                        "issue_text": "- Reject non-admins",
                        "diff": _SAMPLE_DIFF,
                        "annotate": True,
                    },
                },
            }
        )
        assert packed is not None
        packed_text = packed["result"]["content"][0]["text"]
        self.assertIn('<untrusted_artifact kind="issue"', packed_text)
        self.assertIn("## Annotated Diff Line Map (base | new)", packed_text)

    def test_call_check_citations_with_pr_comments(self) -> None:
        with (
            patch("briefcheck.mcp_server.fetch_github_pr_diff", return_value=(_SAMPLE_DIFF, "abcdef1234567")),
            patch(
                "briefcheck.mcp_server.fetch_github_pr_comments",
                return_value=("### PR review by @bot\n\nBug at `auth.py:3`.\n", 1),
            ),
        ):
            resp = handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {
                        "name": "briefcheck_check_citations",
                        "arguments": {
                            "pr": "org/repo#9",
                            "pr_comments": True,
                            "author": "bot",
                        },
                    },
                }
            )
        assert resp is not None
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["pr_comments_checked"], 1)
        self.assertEqual(payload["errors"][0]["code"], "deleted_line_cited_as_new")

    def test_unknown_tool_and_tool_error_and_stdio_loop(self) -> None:
        unknown = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {"name": "no_such_tool", "arguments": {}},
            }
        )
        assert unknown is not None
        self.assertEqual(unknown["error"]["code"], -32602)

        bad_args = handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "briefcheck_annotate_diff", "arguments": {}},
            }
        )
        assert bad_args is not None
        self.assertTrue(bad_args["result"]["isError"])
        self.assertIn("Specify one diff source", bad_args["result"]["content"][0]["text"])

        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            "{broken json",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
        ]
        in_buf = io.StringIO("\n".join(lines) + "\n")
        out_buf = io.StringIO()
        code = serve_stdio(in_buf, out_buf)
        self.assertEqual(code, 0)
        responses = [json.loads(line) for line in out_buf.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[1]["error"]["code"], -32700)
        self.assertEqual(responses[2], {"jsonrpc": "2.0", "id": 2, "result": {}})


if __name__ == "__main__":
    unittest.main()
