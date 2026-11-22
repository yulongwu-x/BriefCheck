"""Markdown review table and evidence citation parser."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Literal

JudgmentKind = Literal["supported", "contradicted", "insufficient_evidence"]

_JUDGMENT_MAP: dict[str, JudgmentKind] = {
    "supported": "supported",
    "有证据支持": "supported",
    "contradicted": "contradicted",
    "明确不符": "contradicted",
    "insufficient evidence": "insufficient_evidence",
    "证据不足": "insufficient_evidence",
}

_HEADER_REQUIREMENT_TOKENS = {
    "acceptance requirement",
    "requirement",
    "criterion",
    "acceptance criterion",
    "验收要求",
    "验收条件",
    "要求",
}
_HEADER_JUDGMENT_TOKENS = {
    "judgment",
    "judgement",
    "verdict",
    "status",
    "判断",
    "判定",
    "结论",
}
_HEADER_EVIDENCE_TOKENS = {
    "evidence",
    "证据",
}
_HEADER_FOLLOWUP_TOKENS = {
    "follow-up",
    "follow up",
    "followup",
    "next step",
    "待补查",
    "后续",
    "待确认",
}

_DELIMITER_CELL_RE = re.compile(r"^:?-{3,}:?$")
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

# Matches `path:line` or `path:start-end` / `path:start–end` where path contains
# either a slash, a filename extension, or a common extensionless repo filename
# (avoiding plain prose like `note:12`).
_CITATION_RE = re.compile(
    r"(?<![A-Za-z0-9_./:-])"
    r"(?:(?P<prefix>base|old):)?"
    r"(?P<path>"
    r"(?:[A-Za-z0-9_.@+-]+/)+[A-Za-z0-9_.@+-]+"
    r"|[A-Za-z0-9_.@+-]+\.[A-Za-z][A-Za-z0-9_+-]*"
    r"|(?:Makefile|Dockerfile|Procfile|Justfile|Jenkinsfile|Vagrantfile|Gemfile|Rakefile|Brewfile)"
    r")"
    r":L?(?P<start>\d+)"
    r"(?:[\-\u2013\u2014]L?(?P<end>\d+))?"
    r"(?![:\d])"
)

_BASE_AFTER_RE = re.compile(
    r"^(?:\s*`?\s*)(?:"
    r"[\(\uFF08]\s*(?:base|old|old\s+side|base\s+side|deleted|before\s+deletion|旧侧|旧版|原侧|原文件|删除前|base\s*侧)\s*[\)\uFF09]"
    r"|(?:in|on)\s+(?:base|old)\b"
    r"|(?:base|old)\s+side\b"
    r")",
    re.IGNORECASE,
)

_BASE_BEFORE_RE = re.compile(
    r"(?:(?:^|[\s`(\uFF08,;，；。])(?:base|old|old\s+side|base\s+side|旧侧|旧版|原侧|原文件)\s*[:：\s]?`?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Citation:
    """A file and line/range reference extracted from an Evidence cell."""

    path: str
    start: int
    end: int
    side: Literal["new", "old"] = "new"
    raw: str = ""

    def label(self) -> str:
        """Render a concise display label for diagnostics."""
        loc = f"{self.path}:{self.start}" if self.start == self.end else f"{self.path}:{self.start}\u2013{self.end}"
        return f"{loc} (base)" if self.side == "old" else loc


@dataclass
class ReportRow:
    """One parsed row from a BriefCheck Markdown table."""

    row_index: int
    line_number: int
    requirement: str
    judgment_raw: str
    judgment: JudgmentKind | None
    evidence: str
    follow_up: str
    cell_count: int
    citations: list[Citation] = field(default_factory=list)


@dataclass
class ParsedReport:
    """Parsed BriefCheck report containing the extracted review table."""

    found_table: bool = False
    headers: list[str] = field(default_factory=list)
    header_line: int | None = None
    rows: list[ReportRow] = field(default_factory=list)
    raw_text: str = ""


def normalize_judgment(raw: str) -> JudgmentKind | None:
    """Normalize an English or Chinese judgment label to its canonical key."""
    cleaned = raw.strip()
    # Strip surrounding Markdown emphasis or inline code markers.
    cleaned = re.sub(r"^(?:\*\*|\*|__|_|`)+", "", cleaned)
    cleaned = re.sub(r"(?:\*\*|\*|__|_|`)+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return _JUDGMENT_MAP.get(cleaned)


def split_markdown_row(line: str) -> list[str]:
    """Split a Markdown table row into cells, preserving escaped pipes (`\\|`)."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]

    cells: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(stripped)
    while i < n:
        ch = stripped[i]
        if ch == "\\" and i + 1 < n and stripped[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def _is_delimiter_row(cells: list[str]) -> bool:
    if len(cells) < 2:
        return False
    return all(bool(_DELIMITER_CELL_RE.match(c.strip())) for c in cells)


def _header_score(headers: list[str]) -> int:
    """Score how strongly a table header matches BriefCheck's 4-column report schema."""
    if len(headers) != 4:
        return 0
    norm = [re.sub(r"\s+", " ", h.strip().lower()) for h in headers]
    score = 0
    if norm[0] in _HEADER_REQUIREMENT_TOKENS:
        score += 2
    if norm[1] in _HEADER_JUDGMENT_TOKENS:
        score += 3
    if norm[2] in _HEADER_EVIDENCE_TOKENS:
        score += 2
    if norm[3] in _HEADER_FOLLOWUP_TOKENS:
        score += 2
    return score


def extract_citations(text: str) -> list[Citation]:
    """Extract all file:line / file:start-end citations from an evidence string."""
    citations: list[Citation] = []
    for match in _CITATION_RE.finditer(text):
        path = match.group("path")
        # Exclude IPv4 addresses (e.g. 127.0.0.1:9222) and URL schemes (http://...).
        if _IPV4_RE.match(path):
            continue
        before_all = text[: match.start()]
        if before_all.endswith("://"):
            continue

        start = int(match.group("start"))
        end = int(match.group("end")) if match.group("end") is not None else start
        side: Literal["new", "old"] = "new"

        if match.group("prefix"):
            side = "old"
        else:
            after_slice = text[match.end() : match.end() + 32]
            before_slice = text[max(0, match.start() - 24) : match.start()]
            if _BASE_AFTER_RE.match(after_slice) or _BASE_BEFORE_RE.search(before_slice):
                side = "old"

        citations.append(
            Citation(
                path=path,
                start=start,
                end=end,
                side=side,
                raw=match.group(0),
            )
        )
    return citations


def parse_report(text: str) -> ParsedReport:
    """Extract and parse the BriefCheck Markdown table from `text`."""
    lines = text.splitlines()
    candidates: list[tuple[int, int, list[str], list[tuple[int, list[str]]]]] = []

    in_fence = False
    fence_char = ""
    fence_len = 0

    i = 0
    total = len(lines)
    while i < total:
        line = lines[i]
        stripped = line.strip()

        # Track fenced code blocks (``` or ~~~) so example snippets are ignored.
        fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_len and stripped == marker:
                in_fence = False
            i += 1
            continue

        if in_fence:
            i += 1
            continue

        if "|" in stripped and i + 1 < total and "|" in lines[i + 1]:
            header_cells = split_markdown_row(line)
            delim_cells = split_markdown_row(lines[i + 1])
            if len(header_cells) == len(delim_cells) and _is_delimiter_row(delim_cells):
                header_line_num = i + 1
                body_rows: list[tuple[int, list[str]]] = []
                j = i + 2
                while j < total:
                    row_line = lines[j].strip()
                    if not row_line or "|" not in row_line:
                        break
                    body_rows.append((j + 1, split_markdown_row(lines[j])))
                    j += 1
                score = _header_score(header_cells)
                if len(header_cells) == 4:
                    candidates.append((score, header_line_num, header_cells, body_rows))
                i = j
                continue

        i += 1

    if not candidates:
        return ParsedReport(found_table=False, raw_text=text)

    # Prefer the highest-scoring BriefCheck 4-column table (ties break by first occurrence).
    candidates.sort(key=lambda item: (-item[0], item[1]))
    _, header_line_num, headers, raw_rows = candidates[0]

    parsed_rows: list[ReportRow] = []
    for idx, (line_num, cells) in enumerate(raw_rows, start=1):
        req = cells[0] if len(cells) > 0 else ""
        judg_raw = cells[1] if len(cells) > 1 else ""
        evid = cells[2] if len(cells) > 2 else ""
        follow = cells[3] if len(cells) > 3 else ""
        parsed_rows.append(
            ReportRow(
                row_index=idx,
                line_number=line_num,
                requirement=req,
                judgment_raw=judg_raw,
                judgment=normalize_judgment(judg_raw),
                evidence=evid,
                follow_up=follow,
                cell_count=len(cells),
                citations=extract_citations(evid),
            )
        )

    return ParsedReport(
        found_table=True,
        headers=headers,
        header_line=header_line_num,
        rows=parsed_rows,
        raw_text=text,
    )
