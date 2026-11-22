"""Unified diff parser and line-number annotator."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable, Literal

_FORMAT_PATCH_REV_RE = re.compile(r"^From ([0-9a-f]{7,40})(?:\s|$)", re.IGNORECASE)
_COMMIT_REV_RE = re.compile(r"^(?:commit|#\s*revision:)\s*([0-9a-f]{7,40})\b", re.IGNORECASE)
_HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$"
)
_DIFF_GIT_RE = re.compile(r"^diff --git\s+(.+)$")


def normalize_path(path: str) -> str:
    """Normalize a repository-relative path for lookup and comparison."""
    cleaned = path.strip().replace("\\", "/")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if cleaned.startswith(("a/", "b/")):
        cleaned = cleaned[2:]
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _unquote_git_path(raw: str) -> str:
    """Decode git's C-style quoted path escapes, including UTF-8 octal bytes."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        inner = raw[1:-1]
        buf = bytearray()
        i = 0
        escapes = {
            "a": 0x07,
            "b": 0x08,
            "f": 0x0C,
            "n": 0x0A,
            "r": 0x0D,
            "t": 0x09,
            "v": 0x0B,
            "\\": ord("\\"),
            '"': ord('"'),
        }
        while i < len(inner):
            ch = inner[i]
            if ch == "\\" and i + 1 < len(inner):
                nxt = inner[i + 1]
                if nxt in "01234567" and i + 3 < len(inner) and all(
                    c in "01234567" for c in inner[i + 1 : i + 4]
                ):
                    buf.append(int(inner[i + 1 : i + 4], 8))
                    i += 4
                    continue
                if nxt in escapes:
                    buf.append(escapes[nxt])
                    i += 2
                    continue
            buf.extend(ch.encode("utf-8"))
            i += 1
        return buf.decode("utf-8", errors="replace")
    return raw


def _parse_header_path(line: str, prefix: str) -> str | None:
    """Parse a `--- ` or `+++ ` path line, returning None for /dev/null."""
    payload = line[len(prefix) :]
    # Strip optional timestamp separated by tab.
    if "\t" in payload:
        payload = payload.split("\t", 1)[0]
    payload = _unquote_git_path(payload.strip())
    if payload in ("", "/dev/null"):
        return None
    if payload.startswith(("a/", "b/")):
        return payload[2:]
    return payload


def _parse_diff_git_paths(rest: str) -> tuple[str | None, str | None]:
    """Parse old/new paths from the tail of a `diff --git ...` header."""
    tokens: list[str] = []
    i = 0
    n = len(rest)
    while i < n and len(tokens) < 2:
        while i < n and rest[i] == " ":
            i += 1
        if i >= n:
            break
        if rest[i] == '"':
            j = i + 1
            while j < n:
                if rest[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if rest[j] == '"':
                    j += 1
                    break
                j += 1
            tokens.append(_unquote_git_path(rest[i:j]))
            i = j
        else:
            j = rest.find(" ", i)
            if j == -1:
                j = n
            tokens.append(rest[i:j])
            i = j
    if len(tokens) != 2:
        return None, None
    old_p = tokens[0][2:] if tokens[0].startswith("a/") else tokens[0]
    new_p = tokens[1][2:] if tokens[1].startswith("b/") else tokens[1]
    return old_p or None, new_p or None


def format_line_ranges(line_numbers: Iterable[int]) -> str:
    """Format a set of line numbers as compact human-readable ranges."""
    sorted_nums = sorted(set(line_numbers))
    if not sorted_nums:
        return "none"
    ranges: list[str] = []
    start = prev = sorted_nums[0]
    for num in sorted_nums[1:]:
        if num == prev + 1:
            prev = num
        else:
            ranges.append(f"{start}" if start == prev else f"{start}\u2013{prev}")
            start = prev = num
    ranges.append(f"{start}" if start == prev else f"{start}\u2013{prev}")
    return ", ".join(ranges)


@dataclass(frozen=True)
class DiffLine:
    """A single line inside a unified diff hunk."""

    kind: Literal["context", "add", "del"]
    old_line: int | None
    new_line: int | None
    text: str


@dataclass
class DiffHunk:
    """A single hunk within a file diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    context_heading: str = ""
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    """Parsed diff information for a single file."""

    old_path: str | None
    new_path: str | None
    status: Literal["modified", "added", "deleted", "renamed"] = "modified"
    is_binary: bool = False
    hunks: list[DiffHunk] = field(default_factory=list)

    @property
    def canonical_path(self) -> str:
        """Primary path representing this file (new path, or old path if deleted)."""
        return self.new_path or self.old_path or ""

    def new_line_map(self) -> dict[int, DiffLine]:
        """Map new-side line numbers (additions + context) to DiffLine objects."""
        result: dict[int, DiffLine] = {}
        for hunk in self.hunks:
            for dl in hunk.lines:
                if dl.new_line is not None:
                    result[dl.new_line] = dl
        return result

    def old_line_map(self) -> dict[int, DiffLine]:
        """Map old-side (base) line numbers (deletions + context) to DiffLine objects."""
        result: dict[int, DiffLine] = {}
        for hunk in self.hunks:
            for dl in hunk.lines:
                if dl.old_line is not None:
                    result[dl.old_line] = dl
        return result

    def has_range(
        self, start: int, end: int, side: Literal["new", "old"] = "new"
    ) -> tuple[bool, list[int]]:
        """Check whether every line in [start, end] is visible on `side`."""
        line_map = self.new_line_map() if side == "new" else self.old_line_map()
        missing = [ln for ln in range(start, end + 1) if ln not in line_map]
        return (len(missing) == 0, missing)


@dataclass
class ParsedDiff:
    """Complete parsed unified diff."""

    files: list[FileDiff] = field(default_factory=list)
    revision: str | None = None

    def find_file(self, path: str) -> FileDiff | None:
        """Find a FileDiff matching `path` (normalized against new or old path)."""
        target = normalize_path(path)
        for fdiff in self.files:
            if fdiff.new_path and normalize_path(fdiff.new_path) == target:
                return fdiff
            if fdiff.old_path and normalize_path(fdiff.old_path) == target:
                return fdiff
        return None

    def file_paths(self) -> list[str]:
        """Return canonical paths of all files in the diff."""
        return [f.canonical_path for f in self.files if f.canonical_path]


def parse_unified_diff(text: str) -> ParsedDiff:
    """Parse a git or plain unified diff into structured files, hunks, and line maps."""
    raw_lines = text.splitlines()
    files: list[FileDiff] = []
    revision: str | None = None
    seen_any_diff = False

    current_file: FileDiff | None = None
    current_hunk: DiffHunk | None = None
    old_cur = 0
    new_cur = 0
    old_seen = 0
    new_seen = 0

    def _finalize_file(fdiff: FileDiff | None) -> None:
        if fdiff is None:
            return
        if fdiff.old_path is None and fdiff.new_path is not None:
            fdiff.status = "added"
        elif fdiff.new_path is None and fdiff.old_path is not None:
            fdiff.status = "deleted"
        elif (
            fdiff.old_path is not None
            and fdiff.new_path is not None
            and fdiff.old_path != fdiff.new_path
        ):
            fdiff.status = "renamed"
        files.append(fdiff)

    i = 0
    total = len(raw_lines)
    while i < total:
        line = raw_lines[i]

        # Extract optional revision SHA from preamble (e.g., git format-patch header).
        if not seen_any_diff and revision is None:
            m_rev = _FORMAT_PATCH_REV_RE.match(line) or _COMMIT_REV_RE.match(line)
            if m_rev:
                revision = m_rev.group(1).lower()

        # Are we actively consuming lines inside a hunk?
        in_hunk_body = current_hunk is not None and (
            old_seen < current_hunk.old_count or new_seen < current_hunk.new_count
        )

        # Always break out on a new file header `diff --git ...` or new hunk header `@@ ... @@`.
        if line.startswith("diff --git "):
            seen_any_diff = True
            _finalize_file(current_file)
            current_hunk = None
            m_git = _DIFF_GIT_RE.match(line)
            old_p, new_p = _parse_diff_git_paths(m_git.group(1)) if m_git else (None, None)
            current_file = FileDiff(old_path=old_p, new_path=new_p)
            i += 1
            continue

        if line.startswith("@@ "):
            m_hunk = _HUNK_HEADER_RE.match(line)
            if m_hunk:
                seen_any_diff = True
                if current_file is None:
                    current_file = FileDiff(old_path=None, new_path=None)
                old_start = int(m_hunk.group(1))
                old_count = int(m_hunk.group(2)) if m_hunk.group(2) is not None else 1
                new_start = int(m_hunk.group(3))
                new_count = int(m_hunk.group(4)) if m_hunk.group(4) is not None else 1
                heading = m_hunk.group(5).strip()
                current_hunk = DiffHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    header=line,
                    context_heading=heading,
                )
                current_file.hunks.append(current_hunk)
                old_cur = old_start
                new_cur = new_start
                old_seen = 0
                new_seen = 0
                i += 1
                continue

        if in_hunk_body and current_hunk is not None:
            if line.startswith("\\ No newline at end of file"):
                i += 1
                continue
            if line.startswith(" "):
                current_hunk.lines.append(
                    DiffLine(kind="context", old_line=old_cur, new_line=new_cur, text=line[1:])
                )
                old_cur += 1
                new_cur += 1
                old_seen += 1
                new_seen += 1
                i += 1
                continue
            if line == "" and old_seen < current_hunk.old_count and new_seen < current_hunk.new_count:
                # Some pasted diffs drop the leading space on blank context lines.
                current_hunk.lines.append(
                    DiffLine(kind="context", old_line=old_cur, new_line=new_cur, text="")
                )
                old_cur += 1
                new_cur += 1
                old_seen += 1
                new_seen += 1
                i += 1
                continue
            if line.startswith("-") and old_seen < current_hunk.old_count:
                current_hunk.lines.append(
                    DiffLine(kind="del", old_line=old_cur, new_line=None, text=line[1:])
                )
                old_cur += 1
                old_seen += 1
                i += 1
                continue
            if line.startswith("+") and new_seen < current_hunk.new_count:
                current_hunk.lines.append(
                    DiffLine(kind="add", old_line=None, new_line=new_cur, text=line[1:])
                )
                new_cur += 1
                new_seen += 1
                i += 1
                continue

        # Handle `\ No newline at end of file` immediately after a hunk completes.
        if current_hunk is not None and line.startswith("\\ No newline at end of file"):
            i += 1
            continue

        # Outside active hunk body: parse file metadata headers.
        if line.startswith("--- ") and i + 1 < total and raw_lines[i + 1].startswith("+++ "):
            seen_any_diff = True
            current_hunk = None
            old_p = _parse_header_path(line, "--- ")
            new_p = _parse_header_path(raw_lines[i + 1], "+++ ")
            # If this is a plain unified diff without `diff --git` headers, start a new FileDiff.
            if current_file is None or current_file.hunks:
                _finalize_file(current_file)
                current_file = FileDiff(old_path=old_p, new_path=new_p)
            else:
                current_file.old_path = old_p
                current_file.new_path = new_p
            i += 2
            continue

        if current_file is not None:
            if line.startswith("new file mode "):
                current_file.status = "added"
            elif line.startswith("deleted file mode "):
                current_file.status = "deleted"
            elif line.startswith("rename from "):
                current_file.old_path = _unquote_git_path(line[len("rename from ") :])
                current_file.status = "renamed"
            elif line.startswith("rename to "):
                current_file.new_path = _unquote_git_path(line[len("rename to ") :])
                current_file.status = "renamed"
            elif line.startswith("Binary files ") or line == "GIT binary patch":
                current_file.is_binary = True

        i += 1

    _finalize_file(current_file)
    return ParsedDiff(files=files, revision=revision)


def annotate_diff(parsed: ParsedDiff) -> str:
    """Render a parsed diff with explicit old-side (base) and new-side line numbers."""
    out: list[str] = []
    if parsed.revision:
        out.append(f"# Revision: {parsed.revision}")
        out.append("")

    for idx, fdiff in enumerate(parsed.files):
        if idx > 0:
            out.append("")
        path_label = fdiff.canonical_path
        if fdiff.status == "renamed" and fdiff.old_path and fdiff.new_path:
            path_label = f"{fdiff.old_path} -> {fdiff.new_path}"
        out.append(f"=== {path_label} ({fdiff.status}) ===")
        if fdiff.is_binary:
            out.append("(binary file)")
            continue
        if not fdiff.hunks:
            out.append("(no hunks)")
            continue
        for hunk in fdiff.hunks:
            out.append(hunk.header)
            for dl in hunk.lines:
                old_col = f"{dl.old_line:>5}" if dl.old_line is not None else "    -"
                new_col = f"{dl.new_line:>5}" if dl.new_line is not None else "    -"
                marker = {"context": " ", "add": "+", "del": "-"}[dl.kind]
                out.append(f"base {old_col} | new {new_col} | {marker} {dl.text}")
    return "\n".join(out)
