"""Deterministic document-diff primitives.

Used today to make re-ingestion observable (what changed between two artifact
versions of the same document); later the SharePoint change-detection pipeline
builds semantic diffs on top of these.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from modelkb.pdf.models import PageRecord


@dataclass(frozen=True)
class PageChange:
    page_number: int
    old_hash: str
    new_hash: str
    similarity: float  # 0.0-1.0


@dataclass(frozen=True)
class DocumentDiff:
    added_pages: list[int] = field(default_factory=list)
    removed_pages: list[int] = field(default_factory=list)
    changed_pages: list[PageChange] = field(default_factory=list)
    unchanged_pages: list[int] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added_pages or self.removed_pages or self.changed_pages)


def text_similarity(old: str, new: str) -> float:
    if old == new:
        return 1.0
    if not old or not new:
        return 0.0
    return difflib.SequenceMatcher(a=old, b=new, autojunk=False).quick_ratio()


def diff_pages(old: list[PageRecord], new: list[PageRecord]) -> DocumentDiff:
    """Page-number-aligned diff on text hashes, with similarity for changes."""
    old_by_no = {p.page_number: p for p in old}
    new_by_no = {p.page_number: p for p in new}
    diff = DocumentDiff()
    for page_no in sorted(set(old_by_no) | set(new_by_no)):
        before, after = old_by_no.get(page_no), new_by_no.get(page_no)
        if before is None and after is not None:
            diff.added_pages.append(page_no)
        elif after is None and before is not None:
            diff.removed_pages.append(page_no)
        elif before is not None and after is not None:
            if before.text_hash == after.text_hash:
                diff.unchanged_pages.append(page_no)
            else:
                diff.changed_pages.append(
                    PageChange(
                        page_number=page_no,
                        old_hash=before.text_hash,
                        new_hash=after.text_hash,
                        similarity=round(text_similarity(before.text, after.text), 4),
                    )
                )
    return diff
