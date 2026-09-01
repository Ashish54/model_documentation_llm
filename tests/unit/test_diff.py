from modelkb.core.hashing import sha256_text
from modelkb.pdf.diff import diff_pages, text_similarity
from modelkb.pdf.models import PageRecord


def _page(number: int, text: str) -> PageRecord:
    return PageRecord(
        page_number=number, text=text, text_hash=sha256_text(text), char_count=len(text)
    )


def test_diff_classifies_pages() -> None:
    old = [_page(1, "same"), _page(2, "old text"), _page(3, "gone")]
    new = [_page(1, "same"), _page(2, "old text with a small edit"), _page(4, "brand new")]
    diff = diff_pages(old, new)
    assert diff.unchanged_pages == [1]
    assert diff.removed_pages == [3]
    assert diff.added_pages == [4]
    assert [c.page_number for c in diff.changed_pages] == [2]
    # quick_ratio for a small edit is well above noise but below identity
    assert 0.3 < diff.changed_pages[0].similarity < 1.0
    assert diff.has_changes


def test_diff_identical_documents() -> None:
    pages = [_page(1, "a"), _page(2, "b")]
    diff = diff_pages(pages, [_page(1, "a"), _page(2, "b")])
    assert not diff.has_changes


def test_similarity_bounds() -> None:
    assert text_similarity("abc", "abc") == 1.0
    assert text_similarity("", "abc") == 0.0
