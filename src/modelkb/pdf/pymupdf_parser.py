"""PyMuPDF-based deterministic PDF parser.

Extraction strategy per feature:
* pages      — plain text per page; empty pages are flagged (possible scans).
* headings   — the PDF outline (TOC) when present; otherwise numbered-heading
               regex; otherwise font-size/bold heuristics. Detection method is
               recorded per section because downstream trust differs.
* tables     — PyMuPDF ``find_tables`` (line/geometry based) + nearest
               preceding "Table N" caption as label.
* equations  — text blocks with high math-symbol density, plus labels like
               "(3)" or "Equation 2".
* citations  — entries under a References/Bibliography heading, inline [n]
               markers, and author-year patterns.
* code refs  — configurable regex patterns (ParserSettings).

Heuristics are deliberately transparent: every record carries its detection
method, and QualityReport aggregates what could not be determined.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import pymupdf as fitz

from modelkb.core.config import ParserSettings
from modelkb.core.hashing import sha256_text
from modelkb.pdf.models import (
    CitationRecord,
    CodeRefRecord,
    EquationRecord,
    MetadataCandidates,
    PageRecord,
    ParsedDocument,
    QualityReport,
    SectionRecord,
    TableRecord,
)

_MATH_CHARS = set("=∑Σβγδσαμπλθ∂√≈≤≥±×÷^_")  # noqa: RUF001 — math glyphs are the point
_EQ_LABEL_RE = re.compile(r"(?:Equation|Eq\.?)\s*(\d+[a-z]?)", re.IGNORECASE)
_EQ_PAREN_RE = re.compile(r"\((\d+[a-z]?)\)\s*$")
_TABLE_CAPTION_RE = re.compile(r"\bTable\s+([A-Za-z0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_REF_HEADING_RE = re.compile(r"^\s*(references|bibliography)\s*$", re.IGNORECASE)
_REF_ENTRY_RE = re.compile(r"^\s*\[(\d+)\]\s+")
_INLINE_CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_AUTHOR_YEAR_RE = re.compile(
    r"\b([A-Z][a-zA-Z'-]+(?:\s+(?:and|&)\s+[A-Z][a-zA-Z'-]+)?)\s*\((\d{4})\)"
)
_VERSION_RE = re.compile(r"\b[Vv]ersion\s*:?\s*([0-9]+(?:\.[0-9A-Za-z-]+)*)")
_DATE_RE = re.compile(r"\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b")
_MODEL_LINE_RE = re.compile(r"^\s*Model\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


class PyMuPdfParser:
    name = "pymupdf"
    version = fitz.version[0]

    def __init__(self, settings: ParserSettings | None = None) -> None:
        self._settings = settings or ParserSettings()
        self._numbered_re = re.compile(self._settings.heading_numbered_pattern)
        self._code_res = {
            f"pattern_{i}": re.compile(p)
            for i, p in enumerate(self._settings.code_reference_patterns)
        }

    # ------------------------------------------------------------------ #
    def parse(self, pdf_path: Path) -> ParsedDocument:
        doc = fitz.open(pdf_path)
        try:
            pages, page_warnings = self._extract_pages(doc)
            toc = doc.get_toc()
            sections = (
                self._sections_from_toc(toc, len(pages))
                if toc
                else self._sections_from_text(doc, pages)
            )
            tables = self._extract_tables(doc)
            equations = self._extract_equations(doc)
            citations = self._extract_citations(pages)
            code_refs = self._extract_code_refs(pages)
            metadata = self._extract_metadata_candidates(doc, pages)
            quality = self._quality(
                pages, sections, tables, equations, citations, code_refs, toc, page_warnings
            )
            return ParsedDocument(
                pages=pages,
                sections=sections,
                tables=tables,
                equations=equations,
                citations=citations,
                code_references=code_refs,
                metadata_candidates=metadata,
                quality=quality,
            )
        finally:
            doc.close()

    # ------------------------------------------------------------------ #
    def _extract_pages(self, doc: fitz.Document) -> tuple[list[PageRecord], list[str]]:
        pages: list[PageRecord] = []
        warnings: list[str] = []
        for i in range(doc.page_count):
            page: Any = doc.load_page(i)
            i += 1
            text = page.get_text("text")
            page_warn: list[str] = []
            if not text.strip():
                page_warn.append("no text extracted — possible scanned/image page")
                warnings.append(f"page {i}: no text extracted (possible scan)")
            pages.append(
                PageRecord(
                    page_number=i,
                    text=text,
                    text_hash=sha256_text(text),
                    char_count=len(text),
                    warnings=page_warn,
                )
            )
        return pages, warnings

    # ------------------------------------------------------------------ #
    def _sections_from_toc(self, toc: list[list[Any]], page_count: int) -> list[SectionRecord]:
        sections: list[SectionRecord] = []
        stack: list[str] = []
        for order, (level, title, page) in enumerate(toc):
            title = title.strip()
            level = max(1, int(level))
            stack = stack[: level - 1]
            stack.append(title)
            sections.append(
                SectionRecord(
                    heading=title,
                    heading_path=list(stack),
                    level=level,
                    page_start=page if page >= 1 else None,
                    page_end=None,
                    order_index=order,
                    detection="toc",
                    confidence=1.0,
                )
            )
        self._fill_page_ends(sections, page_count)
        return sections

    def _sections_from_text(
        self, doc: fitz.Document, pages: list[PageRecord]
    ) -> list[SectionRecord]:
        spans = self._collect_spans(doc)
        if not spans:
            return []
        body_size = self._body_font_size(spans)
        headings: list[tuple[int, str, int, float, str]] = []  # page, text, level, size, how
        for page_no, text, size, flags in spans:
            text = text.strip()
            if not text or len(text) > 200:
                continue
            if self._numbered_re.match(text):
                level = text.split()[0].count(".") + 1 if text[0].isdigit() else 1
                headings.append((page_no, text, level, size, "numbered"))
            elif size >= body_size * self._settings.min_heading_font_ratio and (
                flags & 16 or size >= body_size * 1.25  # bold or much larger
            ):
                headings.append((page_no, text, 1, size, "font"))
        sections: list[SectionRecord] = []
        stack: list[tuple[int, str]] = []  # (level, heading)
        size_ranks = self._size_ranks([h[3] for h in headings if h[4] == "font"])
        for order, (page_no, text, level, size, how) in enumerate(headings):
            if how == "font":
                level = size_ranks.get(size, 1)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            sections.append(
                SectionRecord(
                    heading=text,
                    heading_path=[h for _, h in stack],
                    level=level,
                    page_start=page_no,
                    page_end=None,
                    order_index=order,
                    detection=how,
                    confidence=0.9 if how == "numbered" else 0.7,
                )
            )
        self._fill_page_ends(sections, len(pages))
        return sections

    @staticmethod
    def _collect_spans(doc: fitz.Document) -> list[tuple[int, str, float, int]]:
        out: list[tuple[int, str, float, int]] = []
        for pno in range(doc.page_count):
            page: Any = doc.load_page(pno)
            pno += 1
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    line_text = "".join(s["text"] for s in line.get("spans", []))
                    if not line_text.strip():
                        continue
                    sizes = [s["size"] for s in line["spans"]]
                    flags = max((s["flags"] for s in line["spans"]), default=0)
                    out.append((pno, line_text, max(sizes, default=0.0), flags))
        return out

    @staticmethod
    def _body_font_size(spans: list[tuple[int, str, float, int]]) -> float:
        counter: Counter[float] = Counter()
        for _, text, size, _ in spans:
            counter[round(size, 1)] += len(text)
        return counter.most_common(1)[0][0] if counter else 10.0

    @staticmethod
    def _size_ranks(sizes: list[float]) -> dict[float, int]:
        """Largest heading font → level 1, next → level 2, …"""
        unique = sorted(set(sizes), reverse=True)
        return {size: rank + 1 for rank, size in enumerate(unique)}

    @staticmethod
    def _fill_page_ends(sections: list[SectionRecord], page_count: int) -> None:
        starts = [s.page_start or 1 for s in sections]
        for i, section in enumerate(sections):
            following = [p for p in starts[i + 1 :] if p >= (section.page_start or 1)]
            section.page_end = (min(following) - 1) if following else page_count
            if section.page_end < (section.page_start or 1):
                section.page_end = section.page_start

    # ------------------------------------------------------------------ #
    def _extract_tables(self, doc: fitz.Document) -> list[TableRecord]:
        tables: list[TableRecord] = []
        for pno in range(doc.page_count):
            page: Any = doc.load_page(pno)
            pno += 1
            try:
                found = page.find_tables()
            except Exception:  # pragma: no cover - pymupdf edge cases
                continue
            captions = self._table_captions(page)
            for idx, table in enumerate(found.tables):
                rows = [[(cell or "").strip() for cell in row] for row in table.extract()]
                rows = [row for row in rows if any(row)]
                if not rows:
                    continue
                bbox = list(table.bbox)
                label = self._nearest_caption(captions, bbox)
                tables.append(
                    TableRecord(
                        table_id=f"p{pno}_t{idx}",
                        page=pno,
                        label=label,
                        bbox=bbox,
                        header=rows[0],
                        rows=rows[1:],
                        n_rows=len(rows) - 1,
                        n_cols=max(len(r) for r in rows),
                    )
                )
        return tables

    @staticmethod
    def _table_captions(page: fitz.Page) -> list[tuple[str, fitz.Rect]]:
        captions: list[tuple[str, fitz.Rect]] = []
        for block in page.get_text("dict").get("blocks", []):
            text = " ".join(
                s["text"] for line in block.get("lines", []) for s in line.get("spans", [])
            )
            match = _TABLE_CAPTION_RE.search(text)
            if match:
                captions.append((f"Table {match.group(1)}", fitz.Rect(block["bbox"])))
        return captions

    @staticmethod
    def _nearest_caption(captions: list[tuple[str, fitz.Rect]], bbox: list[float]) -> str | None:
        above = [
            (bbox[1] - rect.y1, label)
            for label, rect in captions
            if rect.y1 <= bbox[1] + 5  # caption ends at/above table top (± tolerance)
        ]
        if not above:
            return None
        above.sort(key=lambda item: item[0])
        return above[0][1]

    # ------------------------------------------------------------------ #
    def _extract_equations(self, doc: fitz.Document) -> list[EquationRecord]:
        equations: list[EquationRecord] = []
        for pno in range(doc.page_count):
            page: Any = doc.load_page(pno)
            pno += 1
            for block in page.get_text("dict").get("blocks", []):
                text = " ".join(
                    s["text"] for line in block.get("lines", []) for s in line.get("spans", [])
                ).strip()
                if len(text) < 3:
                    continue
                # Code references carry math-ish characters (underscores etc.)
                # but are never equations.
                if any(regex.search(text) for regex in self._code_res.values()):
                    continue
                math_density = sum(c in _MATH_CHARS for c in text)
                label_match = _EQ_LABEL_RE.search(text) or _EQ_PAREN_RE.search(text)
                if label_match or math_density >= self._settings.equation_min_symbols:
                    label = None
                    if label_match:
                        raw = label_match.group(1)
                        label = f"Equation {raw}" if _EQ_LABEL_RE.search(text) else f"({raw})"
                    equations.append(
                        EquationRecord(page=pno, text=text, label=label, bbox=list(block["bbox"]))
                    )
        return equations

    # ------------------------------------------------------------------ #
    def _extract_citations(self, pages: list[PageRecord]) -> list[CitationRecord]:
        citations: list[CitationRecord] = []
        in_references = False
        for page in pages:
            for line in page.text.splitlines():
                if _REF_HEADING_RE.match(line):
                    in_references = True
                    continue
                entry = _REF_ENTRY_RE.match(line)
                if in_references and entry:
                    citations.append(
                        CitationRecord(
                            page=page.page_number, raw=line.strip(), kind="reference_entry"
                        )
                    )
                    continue
                for match in _AUTHOR_YEAR_RE.finditer(line):
                    lo, hi = self._settings.citation_year_range
                    if lo <= int(match.group(2)) <= hi:
                        citations.append(
                            CitationRecord(
                                page=page.page_number,
                                raw=match.group(0),
                                kind="author_year",
                                context=line.strip()[:200],
                            )
                        )
            if in_references and not page.text.strip():
                in_references = False
            for match in _INLINE_CITE_RE.finditer(page.text):
                citations.append(
                    CitationRecord(page=page.page_number, raw=match.group(0), kind="inline_numeric")
                )
        return citations

    # ------------------------------------------------------------------ #
    def _extract_code_refs(self, pages: list[PageRecord]) -> list[CodeRefRecord]:
        refs: list[CodeRefRecord] = []
        seen: set[tuple[int, str | None, str | None]] = set()
        for page in pages:
            for pattern_name, regex in self._code_res.items():
                for match in regex.finditer(page.text):
                    path = match.groupdict().get("path")
                    symbol = match.groupdict().get("symbol")
                    # Dedupe across patterns: a backticked ref also matches the
                    # bare-path pattern — keep the first (patterns are ordered
                    # most-specific first in ParserSettings).
                    key = (page.page_number, path, symbol)
                    if key in seen:
                        continue
                    seen.add(key)
                    refs.append(
                        CodeRefRecord(
                            page=page.page_number,
                            raw=match.group(0),
                            path=path,
                            symbol=symbol,
                            pattern_name=pattern_name,
                            span=list(match.span()),
                        )
                    )
        return refs

    # ------------------------------------------------------------------ #
    def _extract_metadata_candidates(
        self, doc: fitz.Document, pages: list[PageRecord]
    ) -> MetadataCandidates:
        first_pages_text = "\n".join(p.text for p in pages[:3])
        title = (doc.metadata or {}).get("title") or (
            pages[0].text.splitlines()[0].strip() if pages and pages[0].text.strip() else None
        )
        versions = sorted(set(_VERSION_RE.findall(first_pages_text)))
        dates = sorted({"-".join(m) for m in _DATE_RE.findall(first_pages_text)})
        models = [m.strip() for m in _MODEL_LINE_RE.findall(first_pages_text)]
        return MetadataCandidates(
            title=title or None,
            version_strings=versions,
            date_strings=dates,
            model_names=models,
        )

    # ------------------------------------------------------------------ #
    def _quality(
        self,
        pages: list[PageRecord],
        sections: list[SectionRecord],
        tables: list[TableRecord],
        equations: list[EquationRecord],
        citations: list[CitationRecord],
        code_refs: list[CodeRefRecord],
        toc: list[Any],
        page_warnings: list[str],
    ) -> QualityReport:
        total = sum(p.char_count for p in pages)
        empty = [p.page_number for p in pages if not p.text.strip()]
        warnings = list(page_warnings)
        if not sections:
            warnings.append("no headings detected (no TOC, no numbered/font headings)")
        if not toc and sections:
            warnings.append("no PDF outline; headings derived heuristically")
        return QualityReport(
            page_count=len(pages),
            pages_with_text=len(pages) - len(empty),
            pages_without_text=empty,
            total_chars=total,
            mean_chars_per_page=round(total / max(len(pages), 1), 1),
            heading_count=len(sections),
            table_count=len(tables),
            equation_count=len(equations),
            citation_count=len(citations),
            code_reference_count=len(code_refs),
            has_toc=bool(toc),
            warnings=warnings,
        )
