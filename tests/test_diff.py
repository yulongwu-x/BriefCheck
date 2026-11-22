"""Tests for unified diff parsing and line-number annotation."""

from __future__ import annotations

from pathlib import Path
import unittest

from briefcheck.diff import annotate_diff, format_line_ranges, parse_unified_diff

REPO_ROOT = Path(__file__).resolve().parents[1]


class UnifiedDiffTests(unittest.TestCase):
    def test_parses_csv_export_fixture(self) -> None:
        diff_text = (REPO_ROOT / "examples" / "csv-export" / "change.diff").read_text(
            encoding="utf-8"
        )
        parsed = parse_unified_diff(diff_text)

        self.assertEqual(parsed.revision, "dcd899c57675bee1b345c6973d6a8a6b171c2242")
        self.assertEqual(parsed.file_paths(), ["export.py", "tests/test_export.py"])

        export_diff = parsed.find_file("export.py")
        self.assertIsNotNone(export_diff)
        assert export_diff is not None
        self.assertEqual(export_diff.status, "modified")
        self.assertEqual(export_diff.has_range(5, 7, side="new"), (True, []))
        self.assertEqual(export_diff.has_range(9, 11, side="new"), (True, []))
        self.assertEqual(export_diff.has_range(14, 15, side="new"), (False, [14, 15]))

        test_diff = parsed.find_file("tests/test_export.py")
        self.assertIsNotNone(test_diff)
        assert test_diff is not None
        self.assertEqual(test_diff.status, "added")
        self.assertEqual(test_diff.has_range(1, 14, side="new"), (True, []))
        self.assertEqual(test_diff.old_line_map(), {})

    def test_parses_multi_hunk_and_gap_lines(self) -> None:
        diff_text = (REPO_ROOT / "examples" / "retry-backoff" / "change.diff").read_text(
            encoding="utf-8"
        )
        parsed = parse_unified_diff(diff_text)
        http_diff = parsed.find_file("client/http.py")
        self.assertIsNotNone(http_diff)
        assert http_diff is not None

        self.assertEqual(len(http_diff.hunks), 2)
        self.assertEqual(http_diff.has_range(4, 9, side="new"), (True, []))
        self.assertEqual(http_diff.has_range(43, 53, side="new"), (True, []))
        # Lines between hunks are not visible in the diff.
        ok, missing = http_diff.has_range(20, 22, side="new")
        self.assertFalse(ok)
        self.assertEqual(missing, [20, 21, 22])

    def test_deleted_and_renamed_and_binary_files(self) -> None:
        raw = """\
diff --git a/old_name.py b/new_name.py
similarity index 100%
rename from old_name.py
rename to new_name.py
diff --git a/legacy.py b/legacy.py
deleted file mode 100644
--- a/legacy.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def legacy():
-    return 1
diff --git a/logo.png b/logo.png
Binary files a/logo.png and b/logo.png differ
"""
        parsed = parse_unified_diff(raw)
        self.assertEqual(len(parsed.files), 3)

        renamed = parsed.find_file("new_name.py")
        self.assertIsNotNone(renamed)
        assert renamed is not None
        self.assertEqual(renamed.status, "renamed")
        self.assertIs(parsed.find_file("old_name.py"), renamed)

        deleted = parsed.find_file("legacy.py")
        self.assertIsNotNone(deleted)
        assert deleted is not None
        self.assertEqual(deleted.status, "deleted")
        self.assertEqual(deleted.has_range(1, 2, side="old"), (True, []))
        self.assertEqual(deleted.new_line_map(), {})

        binary = parsed.find_file("logo.png")
        self.assertIsNotNone(binary)
        assert binary is not None
        self.assertTrue(binary.is_binary)

    def test_plain_diff_no_newline_and_stripped_blank_context(self) -> None:
        raw = (
            "--- a/app.py\t2026-01-01 00:00:00\n"
            "+++ b/app.py\t2026-01-01 00:00:01\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "\n"
            "-old3\n"
            "\\ No newline at end of file\n"
            "+new3\n"
            "\\ No newline at end of file\n"
        )
        parsed = parse_unified_diff(raw)
        app = parsed.find_file("app.py")
        self.assertIsNotNone(app)
        assert app is not None
        self.assertEqual(sorted(app.old_line_map().keys()), [1, 2, 3])
        self.assertEqual(sorted(app.new_line_map().keys()), [1, 2, 3])
        self.assertEqual(app.new_line_map()[2].text, "")
        self.assertEqual(app.new_line_map()[3].text, "new3")

    def test_quoted_utf8_octal_git_paths(self) -> None:
        # "统计.csv" in UTF-8 octal escapes
        raw = (
            'diff --git "a/\\347\\273\\237\\350\\256\\241.csv" '
            '"b/\\347\\273\\237\\350\\256\\241.csv"\n'
            '--- "a/\\347\\273\\237\\350\\256\\241.csv"\n'
            '+++ "b/\\347\\273\\237\\350\\256\\241.csv"\n'
            "@@ -1 +1 @@\n"
            "-a,1\n"
            "+a,2\n"
        )
        parsed = parse_unified_diff(raw)
        fdiff = parsed.find_file("统计.csv")
        self.assertIsNotNone(fdiff)
        assert fdiff is not None
        self.assertEqual(fdiff.canonical_path, "统计.csv")
        self.assertEqual(fdiff.has_range(1, 1, side="new"), (True, []))

    def test_annotate_and_format_ranges(self) -> None:
        self.assertEqual(format_line_ranges([1, 2, 3, 5, 8, 9]), "1\u20133, 5, 8\u20139")
        self.assertEqual(format_line_ranges([]), "none")

        diff_text = (REPO_ROOT / "examples" / "prompt-injection-auth" / "change.diff").read_text(
            encoding="utf-8"
        )
        annotated = annotate_diff(parse_unified_diff(diff_text))
        self.assertIn("=== api/reports.py (modified) ===", annotated)
        self.assertIn("base    11 | new     - | -     if not user.is_admin:", annotated)
        self.assertIn("base     - | new    12 | +     audit.log(", annotated)


if __name__ == "__main__":
    unittest.main()
