"""Synthetic PDF corpus for tests — four structurally different documents.

Deliberately NOT uniform (the discovery stage exists precisely because the
real 28 PDFs are not):

* macro_core.pdf — PDF outline (TOC), numbered headings, gridded table with
  caption, parenthesised equation label, [n] references, backticked code ref.
* swiss_hpi.pdf — NO TOC, unnumbered bold/large headings, "Table A" caption,
  "Equation 2" label, relationship language, backticked code ref.
* pension.pdf — cover-page metadata lines, numbered headings, one page with
  NO text (simulated scan → extraction warning).
* irr.pdf — author-year citation, dotted-python-symbol code reference,
  "1."-style headings, gridded table.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

BODY = ("helv", 10)
BOLD = ("hebo", 10)
H1 = ("hebo", 16)
H2 = ("hebo", 13)


def _write_lines(
    page: fitz.Page, lines: list[tuple[str, tuple[str, float]]], y0: float = 72.0
) -> float:
    y = y0
    for text, (font, size) in lines:
        page.insert_text((72, y), text, fontname=font, fontsize=size)
        y += size * 1.6
    return y


def _draw_table(
    page: fitz.Page,
    *,
    x: float,
    y: float,
    col_widths: list[float],
    row_height: float,
    data: list[list[str]],
    caption: str | None = None,
) -> None:
    """Draw a real grid so PyMuPDF's line-based table detection finds it."""
    if caption:
        page.insert_text((x, y), caption, fontname=BOLD[0], fontsize=BODY[1])
        y += row_height
    total_w = sum(col_widths)
    n_rows = len(data)
    for i in range(n_rows + 1):
        yy = y + i * row_height
        page.draw_line(fitz.Point(x, yy), fitz.Point(x + total_w, yy))
    xx = x
    for w in col_widths:
        page.draw_line(fitz.Point(xx, y), fitz.Point(xx, y + n_rows * row_height))
        xx += w
    page.draw_line(fitz.Point(x + total_w, y), fitz.Point(x + total_w, y + n_rows * row_height))
    for r, row in enumerate(data):
        xx = x
        for c, cell in enumerate(row):
            page.insert_text(
                (xx + 4, y + r * row_height + row_height * 0.7),
                cell,
                fontname=BODY[0],
                fontsize=BODY[1] - 1,
            )
            xx += col_widths[c]


def make_macro_core(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    _write_lines(
        page,
        [
            ("Macro Core Model", H1),
            ("Model: Macro Core Model", BODY),
            ("Version: 2.3", BODY),
            ("Date: 2026-01-15", BODY),
            ("", BODY),
            ("1 Introduction", H2),
            ("This document describes the macro core model used for policy analysis.", BODY),
            ("2 Model methodology", H2),
            ("2.1 Policy rate specification", H2),
            ("The policy rate follows a Taylor-type rule:", BODY),
            ("r_t = rho r_{t-1} + (1-rho)(alpha + beta pi_t) + eps_t        (1)", BODY),
        ],
    )
    _draw_table(
        page,
        x=72,
        y=330,
        col_widths=[120, 80, 80],
        row_height=18,
        data=[
            ["Coefficient", "Value", "Unit"],
            ["beta", "0.65", "-"],
            ["rho", "0.80", "-"],
        ],
        caption="Table 1: Calibrated coefficients",
    )
    page2 = doc.new_page()
    _write_lines(
        page2,
        [
            ("3 Implementation", H2),
            ("The steady state is computed by `models/macro/core.py::solve_steady_state`.", BODY),
            ("The swiss_hpi model uses the policy rate produced by the macro core model.", BODY),
            ("", BODY),
            ("References", H2),
            ("[1] Taylor (1993). Discretion versus policy rules in practice.", BODY),
            ("[2] Woodford (2003). Interest and Prices.", BODY),
        ],
    )
    doc.set_toc(
        [
            [1, "1 Introduction", 1],
            [1, "2 Model methodology", 1],
            [2, "2.1 Policy rate specification", 1],
            [1, "3 Implementation", 2],
        ]
    )
    doc.save(path)
    doc.close()
    return path


def make_swiss_hpi(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    _write_lines(
        page,
        [
            ("Swiss House Price Index Model", H1),
            ("Version 1.4 — 2026-02-20", BODY),
            ("", BODY),
            ("Overview", H2),
            ("The model estimates a hedonic price index for Swiss residential property.", BODY),
            ("Interest-rate specification", H2),
            ("Equation 2: g_t = gamma_0 + gamma_1 * r_t + gamma_2 * s_t + u_t", BODY),
            ("The model uses the policy rate produced by the macro core model as input.", BODY),
        ],
    )
    _draw_table(
        page,
        x=72,
        y=280,
        col_widths=[140, 100],
        row_height=18,
        data=[
            ["Segment", "Weight"],
            ["Single-family", "0.55"],
            ["Condominium", "0.45"],
        ],
        caption="Table A: Segment weights",
    )
    page2 = doc.new_page()
    _write_lines(
        page2,
        [
            ("Implementation notes", H2),
            ("Index computation lives in `models/housing/swiss_hpi.py::compute_index`.", BODY),
        ],
    )
    doc.save(path)
    doc.close()
    return path


def make_pension(path: Path) -> Path:
    doc = fitz.open()
    cover = doc.new_page()
    _write_lines(
        cover,
        [
            ("Pension Liability Model — Documentation", H1),
            ("Model: Pension Liability Model", BODY),
            ("Version: 3.1", BODY),
            ("Date: 2026-03-15", BODY),
        ],
    )
    scanned = doc.new_page()  # intentionally left empty: simulates a scanned page
    assert not scanned.get_text().strip()
    page3 = doc.new_page()
    _write_lines(
        page3,
        [
            ("1 Demographic assumptions", H2),
            ("Mortality follows the BVG 2025 generation tables.", BODY),
            ("2 Benefit rules", H2),
            ("Retirement capital converts at the statutory rate.", BODY),
        ],
    )
    doc.save(path)
    doc.close()
    return path


def make_irr(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    _write_lines(
        page,
        [
            ("Interest-Rate-Risk Model", H1),
            ("Version: 0.9 (draft) — 2026-04-01", BODY),
            ("1. Scope", H2),
            ("The model computes EVE and NII under supervisory scenarios.", BODY),
            ("Curve bootstrapping follows Hull (2018), chapter 4.", BODY),
            ("Zero curves are built by irr.curves.bootstrap_zero_curve in the library.", BODY),
        ],
    )
    _draw_table(
        page,
        x=72,
        y=260,
        col_widths=[160, 120],
        row_height=18,
        data=[
            ["Scenario", "Shock (bp)"],
            ["Parallel up", "+200"],
            ["Parallel down", "-200"],
        ],
        caption="Table 4: Scenario definitions",
    )
    doc.save(path)
    doc.close()
    return path


BUILDERS = {
    "macro_core.pdf": make_macro_core,
    "swiss_hpi.pdf": make_swiss_hpi,
    "pension.pdf": make_pension,
    "irr.pdf": make_irr,
}


def make_corpus(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    return {name: builder(directory / name) for name, builder in BUILDERS.items()}
