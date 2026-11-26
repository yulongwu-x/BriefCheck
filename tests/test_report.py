"""Tests for Markdown review-table and citation parsing."""

from __future__ import annotations

import unittest

from briefcheck.report import (
    Citation,
    extract_citations,
    normalize_judgment,
    parse_report,
    split_markdown_row,
)


class ReportParserTests(unittest.TestCase):
    def test_split_markdown_row_respects_escaped_pipes(self) -> None:
        row = r"| Accept `a \| b` input | Supported | `parser.py:10–12` handles `a \| b`. | — |"
        cells = split_markdown_row(row)
        self.assertEqual(len(cells), 4)
        self.assertEqual(cells[0], "Accept `a | b` input")
        self.assertEqual(cells[1], "Supported")
        self.assertEqual(cells[2], "`parser.py:10–12` handles `a | b`.")
        self.assertEqual(cells[3], "—")

    def test_normalize_judgments_en_and_zh(self) -> None:
        self.assertEqual(normalize_judgment("Supported"), "supported")
        self.assertEqual(normalize_judgment("**有证据支持**"), "supported")
        self.assertEqual(normalize_judgment("Contradicted"), "contradicted")
        self.assertEqual(normalize_judgment("明确不符"), "contradicted")
        self.assertEqual(normalize_judgment("Insufficient evidence"), "insufficient_evidence")
        self.assertEqual(normalize_judgment("证据不足"), "insufficient_evidence")
        self.assertIsNone(normalize_judgment("Partially supported"))

    def test_extract_citations_sides_and_filters(self) -> None:
        text = (
            "See `export.py:5–7`, `tests/test_export.py:9-14`, "
            "`api/reports.py:11–12` (base), `base:legacy.py:3`, "
            "`src/auth.py:20`（旧侧）, and `Dockerfile:8`. "
            "Ignore https://github.com/org/repo, 127.0.0.1:9222, 12:34:56, and Note: 42."
        )
        citations = extract_citations(text)
        expected = [
            Citation(path="export.py", start=5, end=7, side="new", raw="export.py:5–7"),
            Citation(
                path="tests/test_export.py",
                start=9,
                end=14,
                side="new",
                raw="tests/test_export.py:9-14",
            ),
            Citation(path="api/reports.py", start=11, end=12, side="old", raw="api/reports.py:11–12"),
            Citation(path="legacy.py", start=3, end=3, side="old", raw="base:legacy.py:3"),
            Citation(path="src/auth.py", start=20, end=20, side="old", raw="src/auth.py:20"),
            Citation(path="Dockerfile", start=8, end=8, side="new", raw="Dockerfile:8"),
        ]
        self.assertEqual(citations, expected)

    def test_extract_citations_github_anchors_and_line_column_and_url_filtering(self) -> None:
        text = (
            "Check `src/auth.py#L12`, [src/auth.py#L14-L18](https://github.com/org/repo/blob/main/src/auth.py#L14-L18), "
            "`api/views.py:42:7`, `base:old_auth.py#L3`, and `src/guard.py#L5-L6` (base). "
            "Ignore raw URL https://github.com/org/repo/blob/abc123/src/ignored.py#L99 and timestamp 12:34:56."
        )
        citations = extract_citations(text)
        expected = [
            Citation(path="src/auth.py", start=12, end=12, side="new", raw="src/auth.py#L12"),
            Citation(path="src/auth.py", start=14, end=18, side="new", raw="src/auth.py#L14-L18"),
            Citation(path="api/views.py", start=42, end=42, side="new", raw="api/views.py:42:7"),
            Citation(path="old_auth.py", start=3, end=3, side="old", raw="base:old_auth.py#L3"),
            Citation(path="src/guard.py", start=5, end=6, side="old", raw="src/guard.py#L5-L6"),
        ]
        self.assertEqual(citations, expected)

    def test_parse_report_ignores_fenced_tables_and_selects_report_table(self) -> None:
        md = """\
Here is a legend:

| Judgment | Meaning |
| --- | --- |
| Supported | Evidence backs requirement |

```markdown
| Acceptance requirement | Judgment | Evidence | Follow-up |
| --- | --- | --- | --- |
| Fake example inside fence | Supported | `fake.py:999` | — |
```

Actual review:

| Acceptance requirement | Judgment | Evidence | Follow-up |
| --- | --- | --- | --- |
| Keep filename | Supported | `export.py:5–7` keeps `path`. | — |
"""
        parsed = parse_report(md)
        self.assertTrue(parsed.found_table)
        self.assertEqual(len(parsed.rows), 1)
        self.assertEqual(parsed.rows[0].requirement, "Keep filename")
        self.assertEqual(parsed.rows[0].judgment, "supported")
        self.assertEqual(len(parsed.rows[0].citations), 1)
        self.assertEqual(parsed.rows[0].citations[0].path, "export.py")


if __name__ == "__main__":
    unittest.main()
