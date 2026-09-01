"""Parser tests against the synthetic corpus (varied structures on purpose)."""

from pathlib import Path

import pytest

from modelkb.pdf.pymupdf_parser import PyMuPdfParser
from tests.fixtures.synthetic_pdfs import make_corpus


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return make_corpus(tmp_path_factory.mktemp("corpus"))


@pytest.fixture(scope="module")
def parser() -> PyMuPdfParser:
    return PyMuPdfParser()


def test_toc_headings_build_hierarchy(parser, corpus) -> None:
    parsed = parser.parse(corpus["macro_core.pdf"])
    by_heading = {s.heading: s for s in parsed.sections}
    sub = by_heading["2.1 Policy rate specification"]
    assert sub.heading_path == ["2 Model methodology", "2.1 Policy rate specification"]
    assert sub.detection == "toc"
    assert sub.level == 2


def test_unnumbered_headings_detected_by_font(parser, corpus) -> None:
    parsed = parser.parse(corpus["swiss_hpi.pdf"])
    assert not parsed.quality.has_toc
    headings = {s.heading for s in parsed.sections}
    assert "Interest-rate specification" in headings
    assert any(s.detection == "font" for s in parsed.sections)


def test_table_with_caption(parser, corpus) -> None:
    parsed = parser.parse(corpus["macro_core.pdf"])
    assert len(parsed.tables) == 1
    table = parsed.tables[0]
    assert table.label == "Table 1"
    assert table.header == ["Coefficient", "Value", "Unit"]
    assert ["beta", "0.65", "-"] in table.rows
    assert table.bbox is not None


def test_equation_labels(parser, corpus) -> None:
    macro = parser.parse(corpus["macro_core.pdf"])
    assert [e.label for e in macro.equations] == ["(1)"]
    hpi = parser.parse(corpus["swiss_hpi.pdf"])
    assert [e.label for e in hpi.equations] == ["Equation 2"]


def test_code_references_extract_path_and_symbol(parser, corpus) -> None:
    parsed = parser.parse(corpus["macro_core.pdf"])
    assert len(parsed.code_references) == 1
    ref = parsed.code_references[0]
    assert ref.path == "models/macro/core.py"
    assert ref.symbol == "solve_steady_state"


def test_code_reference_lines_are_not_equations(parser, corpus) -> None:
    irr = parser.parse(corpus["irr.pdf"])
    assert irr.equations == []
    assert irr.code_references[0].symbol == "irr.curves.bootstrap_zero_curve"


def test_citations(parser, corpus) -> None:
    parsed = parser.parse(corpus["macro_core.pdf"])
    entries = [c for c in parsed.citations if c.kind == "reference_entry"]
    assert len(entries) == 2
    irr = parser.parse(corpus["irr.pdf"])
    assert any(c.kind == "author_year" and "Hull" in c.raw for c in irr.citations)


def test_metadata_candidates(parser, corpus) -> None:
    parsed = parser.parse(corpus["macro_core.pdf"])
    assert parsed.metadata_candidates.version_strings == ["2.3"]
    assert parsed.metadata_candidates.date_strings == ["2026-01-15"]
    assert parsed.metadata_candidates.model_names == ["Macro Core Model"]


def test_scanned_page_produces_warning(parser, corpus) -> None:
    parsed = parser.parse(corpus["pension.pdf"])
    assert 2 in parsed.quality.pages_without_text
    assert any("scan" in w for w in parsed.quality.warnings)


def test_parsing_is_deterministic(parser, corpus) -> None:
    a = parser.parse(corpus["macro_core.pdf"])
    b = parser.parse(corpus["macro_core.pdf"])
    assert [p.text_hash for p in a.pages] == [p.text_hash for p in b.pages]
    assert a.model_dump(exclude={"pages"}) == b.model_dump(exclude={"pages"})
