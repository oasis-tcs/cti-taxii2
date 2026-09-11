from fidelity.md_model import read_md
from fidelity.model import Heading, Para, Table, Code, iter_blocks, links, mono_lines, spans, units, headings


def test_fixture_headings_and_ids(fixture_doc):
    assert [(l, n, t) for l, n, t in headings(fixture_doc)] == [
        (2, "1.1", "IPR Policy"), (2, "1.2", "Terminology"), (2, "1.3", "Normative References"), (2, "1.6", "Overview"),
    ]
    assert fixture_doc.ids["ipr-policy"] == "heading:1.1"
    assert fixture_doc.ids["rfc2119"] == "ref:RFC2119"
    assert fixture_doc.ids["11-ipr-policy"] == "heading:1.1"  # GitHub's automatic anchor


def test_fixture_links_resolve(fixture_doc):
    lk = [(t, tg) for t, tg, _ in links(fixture_doc, ["1.2"])]
    assert lk == [("RFC2119", "ref:RFC2119"), ("RFC8174", "ref:RFC8174"), ("1.6", "heading:1.6")]
    assert not fixture_doc.findings, fixture_doc.findings


def test_fixture_escapes_and_emphasis(fixture_doc):
    text = " ".join(u for u, _ in units(fixture_doc, ["1.2"]))
    assert "BCP 14 [RFC2119] [RFC8174] when" in text
    b = spans(fixture_doc, "bold", ["1.2"])
    assert b["MUST NOT"] == 1 and b["MAY"] == 1 and sum(b.values()) == 11


def test_html_devices_are_parsed(profile):
    md = """# 1. Intro <a id="intro"></a>

<table border="1">
  <tr><th><span class='taxiitr'>Property Name</span></th><th>Type</th></tr>
  <tr><td><strong>title</strong> (required)</td><td><span class="taxiitype">string</span><br><br>Second para<ul><li>item one</li></ul></td></tr>
  <tr><td colspan="2"><pre class="nowrap"><code class="language-JSON">{
  "a": 1
}</code></pre></td></tr>
</table>

| A | B |
|---|---|
| <span class="taxiiliteral">complete</span> | `mono` |
"""
    doc = read_md(md, profile, is_text=True)
    tbls = [b for b, _ in iter_blocks(doc.blocks) if isinstance(b, Table)]
    assert len(tbls) == 2
    t = tbls[0]
    assert len(t.rows) == 3 and t.ncols() == 2 and t.rows[2][0].colspan == 2
    assert t.rows[0][0].header and not t.rows[1][0].header
    cell = t.rows[1][1]
    kinds = [type(b).__name__ for b in cell.blocks]
    assert kinds == ["Para", "Para", "Para"] and cell.blocks[2].list_info.kind == "bullet"
    assert cell.blocks[0].text == "string" and cell.blocks[1].text == "Second para"  # <br><br> = paragraph break
    assert isinstance(t.rows[2][0].blocks[0], Code) and t.rows[2][0].blocks[0].lines == ["{", '  "a": 1', "}"]
    assert spans(doc, "type")["string"] == 1 and spans(doc, "literal")["complete"] == 1
    assert spans(doc, "bold")["title"] == 1
    # a semantic span is monospace by stylesheet; inline code stays a paragraph (never a code block)
    assert spans(doc, "mono")["string"] == 1 and spans(doc, "mono")["complete"] == 1 and spans(doc, "mono")["mono"] == 1
    assert mono_lines(doc)["mono"] == 1 and mono_lines(doc)["complete"] == 1
    assert isinstance(tbls[1].rows[1][1].blocks[0], Para)
    assert tbls[1].rows[0][0].header
