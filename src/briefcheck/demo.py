"""Run a small, offline example through the real report verifier."""

from __future__ import annotations

import sys

from .verifier import verify_report

_DIFF = """\
diff --git a/auth.py b/auth.py
--- a/auth.py
+++ b/auth.py
@@ -1,4 +1,2 @@
 def guard(user):
-    if not user.is_admin:
-        raise PermissionError()
     return True
"""

_REPORT = """\
| Acceptance requirement | Judgment | Evidence | Follow-up |
| --- | --- | --- | --- |
| Reject non-admins | Contradicted | `auth.py:3` is the removed error and `auth.py:99` returns True. | Restore the guard. |
"""


def run_demo() -> int:
    """Show the errors and verify the corrected citations."""
    rejected = verify_report(_REPORT, _DIFF)
    corrected = _REPORT.replace("`auth.py:3`", "`auth.py:3` (base)").replace(
        "`auth.py:99`", "`auth.py:2`"
    )
    accepted = verify_report(corrected, _DIFF)

    print("Before correcting citations")
    print(rejected.format_text())
    print()
    print("After marking auth.py:3 as base and replacing auth.py:99 with auth.py:2")
    print(accepted.format_text())

    expected_errors = {"deleted_line_cited_as_new", "line_out_of_hunk"}
    if {finding.code for finding in rejected.errors} != expected_errors or not accepted.is_valid():
        print("Demo did not reproduce the expected verification results.", file=sys.stderr)
        return 1
    return 0
