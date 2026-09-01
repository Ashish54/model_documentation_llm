from modelkb.core import ids


def test_slugify_basic() -> None:
    assert ids.slugify("Swiss HPI Model!") == "swiss_hpi_model"
    assert ids.slugify("  policy-rate (2026) ") == "policy_rate_2026"
    assert ids.slugify("???") == "unnamed"


def test_readable_refs() -> None:
    assert ids.model_ref("swiss_hpi") == "model:swiss_hpi"
    assert ids.model_version_ref("swiss_hpi", "2026-03") == "modelver:swiss_hpi:2026_03"
    assert ids.document_version_ref("swiss_hpi", "2026-03") == "docver:swiss_hpi:2026_03"
    assert ids.variable_ref("macro", "policy rate") == "variable:macro.policy_rate"
    assert ids.code_symbol_ref("abc123def456", "models/hpi.py", "HPI.compute") == (
        "code:abc123def456:models/hpi.py#HPI.compute"
    )


def test_evidence_id_is_deterministic() -> None:
    a = ids.evidence_id("sha", kind="text_span", page=17, text_start=1, text_end=9)
    b = ids.evidence_id("sha", kind="text_span", page=17, text_start=1, text_end=9)
    c = ids.evidence_id("sha", kind="text_span", page=18, text_start=1, text_end=9)
    assert a == b
    assert a != c
    assert a.startswith("evidence:")


def test_evidence_id_distinguishes_kinds_and_labels() -> None:
    base = ids.evidence_id("sha", kind="table", page=3, table_label="Table 4")
    other = ids.evidence_id("sha", kind="equation", page=3, equation_label="Equation 2")
    assert base != other
