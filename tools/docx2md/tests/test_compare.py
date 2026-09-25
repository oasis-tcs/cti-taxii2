"""The hand-written STIX-style fixture of sections 1.1 and 1.2 must verify clean against the
DOCX, and every mutation of it must be caught by the intended layer."""
import pytest

from fidelity.compare import compare, format_report
from fidelity.md_model import read_md

SECTIONS = ["1.1", "1.2"]


def test_fixture_verifies_clean(docx_doc, fixture_doc, resolutions):
    rep = compare(docx_doc, fixture_doc, sections=SECTIONS, resolutions=resolutions)
    assert rep["ok"], format_report(rep)
    assert rep["text"]["docx"] == rep["text"]["md"] == 5


def test_resolutions_accept_only_declared_deviations(docx_doc, fixture_text, profile):
    """A deliberately re-targeted link fails without a resolution and passes with exactly one."""
    md = read_md(fixture_text.replace("[1.6](#overview)", "[1.6](#normative-references)"), profile, is_text=True)
    assert not compare(docx_doc, md, sections=SECTIONS, resolutions=[])["links"]["ok"]
    right = [{"text": "1.6", "docx": "heading:1.6", "md": "heading:1.3", "why": "test"}]
    assert compare(docx_doc, md, sections=SECTIONS, resolutions=right)["links"]["ok"]
    wrong_text = [{"text": "1.7", "docx": "heading:1.6", "md": "heading:1.3", "why": "test"}]
    assert not compare(docx_doc, md, sections=SECTIONS, resolutions=wrong_text)["links"]["ok"]
    wrong_target = [{"text": "*", "docx": "heading:1.6", "md": "heading:1.2", "why": "test"}]
    assert not compare(docx_doc, md, sections=SECTIONS, resolutions=wrong_target)["links"]["ok"]


MUTATIONS = [
    ("dropped words", "when, and only when, they appear", "when they appear", "text"),
    ("changed keyword", '"**MUST NOT**"', '"**MUST**"', "text"),
    ("typo", "Technical Committee was established", "Technical Comittee was established", "text"),
    ("dropped sentence", "All text is normative except for examples, the overview (section [1.6](#overview)), and any text marked non-normative.", "", "text"),
    ("lost bold", '"**MAY**"', '"MAY"', "emphasis"),
    ("spurious italic", "the mode chosen", "the *mode* chosen", "emphasis"),
    ("wrong link target", "[RFC8174](#rfc8174)", "[RFC8174](#rfc2119)", "links"),
    ("dropped link", "[1.6](#overview)", "1.6", "links"),
    ("changed url", "policies-guidelines/ipr)", "policies-guidelines/ipr/)", "links"),
    ("wrong heading number", "## 1.2 Terminology", "## 1.4 Terminology", "headings"),
    ("wrong heading level", "## 1.2 Terminology", "### 1.2 Terminology", "headings"),
    ("broken anchor", "[RFC2119](#rfc2119)", "[RFC2119](#rfc-2119)", "hygiene"),
]


@pytest.mark.parametrize("name,old,new,layer", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_mutation_is_caught(docx_doc, fixture_text, profile, resolutions, name, old, new, layer):
    assert old in fixture_text
    mutated = read_md(fixture_text.replace(old, new), profile, is_text=True)
    rep = compare(docx_doc, mutated, sections=SECTIONS, resolutions=resolutions)
    assert not rep["ok"], f"{name}: mutation not detected"
    assert not rep[layer]["ok"], f"{name}: expected layer {layer} to fail\n{format_report(rep)}"


def test_partial_mode_tolerates_links_to_unconverted_sections(docx_doc, fixture_text, profile, resolutions):
    stub = "## 1.6 Overview <a id=\"overview\"></a>\n\nFixture stub.\n"
    assert stub in fixture_text
    md = read_md(fixture_text.replace(stub, ""), profile, is_text=True)
    strict = compare(docx_doc, md, sections=SECTIONS, resolutions=resolutions)
    assert not strict["hygiene"]["ok"] and not strict["links"]["ok"]
    partial = compare(docx_doc, md, sections=SECTIONS, resolutions=resolutions, partial=True)
    assert partial["ok"], format_report(partial)


def test_section_filter_isolates_sections(docx_doc, fixture_doc, resolutions):
    only_11 = compare(docx_doc, fixture_doc, sections=["1.1"], resolutions=resolutions)
    assert only_11["ok"] and only_11["text"]["docx"] == 2
    whole = compare(docx_doc, fixture_doc, resolutions=resolutions)
    assert not whole["ok"] and whole["text"]["docx"] > 1000
