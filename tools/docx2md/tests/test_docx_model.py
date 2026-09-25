"""Self-validation of the DOCX reader against oracles that do not depend on it:
Word's cached table of contents, raw-XML element counts, and python-docx's own text."""
import re
import zipfile
from collections import Counter

import docx

from fidelity.model import Code, Heading, Image, Para, Table, iter_blocks, links, norm, tables, images


def test_heading_numbers_match_cached_toc(docx_doc):
    computed = [(h.number, h.title) for h, _ in iter_blocks(docx_doc.blocks) if isinstance(h, Heading)]
    toc = docx_doc.meta["toc_headings"]
    assert len(toc) == 80
    assert computed == toc


def test_heading_level_distribution(docx_doc):
    heads = [h for h, _ in iter_blocks(docx_doc.blocks) if isinstance(h, Heading)]
    levels = Counter(h.level for h in heads if not h.number.startswith("Appendix"))
    assert levels == {1: 8, 2: 33, 3: 33, 4: 2}
    assert [h.number for h in heads if h.number.startswith("Appendix")] == ["Appendix A", "Appendix B", "Appendix C", "Appendix D"]


def test_counts_match_raw_xml(raw_doc, profile):
    docx_doc = raw_doc
    xml = zipfile.ZipFile(profile.source_path()).read("word/document.xml").decode("utf8")
    assert len(tables(docx_doc)) == len(re.findall(r"<w:tbl[ >]", xml))
    assert len(images(docx_doc)) == len(re.findall(r"<w:drawing", xml))
    # Hyperlinks whose text is only whitespace (Word artefacts, 5 in this document) carry no
    # content; the model merges them into the neighbouring same-target link or reports them.
    # Word's own table of contents is made of hyperlinks to _Toc bookmarks; it is dropped.
    # Adjacent hyperlinks with the same target and nothing in between (Word split
    # "STIX Version 2.1" into two links) are one link span in the model.
    raw_ext = raw_int = 0
    prev_target, prev_end = None, -1
    for m in re.finditer(r"<w:hyperlink ([^>]*)>(.*?)</w:hyperlink>", xml, re.S):
        target = re.search(r'(?:r:id|w:anchor)="([^"]+)"', m.group(1)).group(1)
        text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", m.group(2)))
        between = xml[prev_end:m.start()]
        adjacent = target == prev_target and "<w:t" not in between and "</w:p>" not in between
        prev_target, prev_end = target, m.end()
        if not text.strip() or 'w:anchor="_Toc' in m.group(1) or adjacent:
            continue
        if "r:id=" in m.group(1):
            raw_ext += 1
        else:
            raw_int += 1
    lk = [(t, tg) for t, tg, _ in links(docx_doc) if t]
    assert sum(1 for _, tg in lk if tg.startswith("url:")) == raw_ext
    assert sum(1 for _, tg in lk if not tg.startswith("url:")) == raw_int
    assert raw_ext == 74 and raw_int > 100
    assert sum(1 for f in docx_doc.findings if f["kind"] == "empty-link") == 5


def test_text_matches_python_docx(raw_doc, profile):
    """Top-level (non-table) text must equal what python-docx reads, line by line."""
    docx_doc = raw_doc
    d = docx.Document(str(profile.source_path()))
    expected = []
    for p in d.paragraphs:
        if p.style.name.lower().startswith("toc") or norm(p.text) == "Table of Contents":
            continue
        for line in p.text.split("\n"):
            if norm(line):
                expected.append(norm(line))
    got = []
    for b in docx_doc.blocks:
        if isinstance(b, Heading):
            got.append(norm(b.title))
        elif isinstance(b, Para):
            got += [norm(l) for l in b.text.split("\n") if norm(l)]
        elif isinstance(b, Code):
            got += [norm(l) for l in b.lines if norm(l)]
    assert got == expected


def test_code_indentation_preserved(docx_doc):
    lines = [l for b, _ in iter_blocks(docx_doc.blocks) if isinstance(b, Code) for l in b.lines]
    assert any(l.startswith('  "') for l in lines), "JSON example lines should keep their 2-space indentation"
    assert any(l.startswith('      "') for l in lines)


def test_endpoint_tables_have_spanned_cell(raw_doc):
    spanned = [t for t in tables(raw_doc) if any(c.colspan > 1 for r in t.rows for c in r)]
    assert len(spanned) == 11
    for t in spanned:
        assert len(t.rows) == 2 and t.rows[1][0].colspan == 2
    assert len(tables(raw_doc)) == 34


def test_representation_rules(docx_doc, raw_doc):
    """PRD D10/D22/D23: endpoint tables unwrapped, empty title-page box dropped, reference keys split."""
    assert len(tables(docx_doc)) == 34 - 11 - 1
    heads = [b for b in docx_doc.blocks if isinstance(b, Para) and b.style == "EndpointHeader"]
    assert len(heads) == 11 and heads[0].text == "GET /taxii2/" and heads[0].mono and heads[0].standalone
    assert all(re.match(r"^(GET|POST|DELETE) /", h.text) for h in heads)
    assert sum(1 for f in docx_doc.findings if f["kind"] == "unwrapped-image-table") == 1
    assert len(images(docx_doc)) == 3
    ref = next(b for b in docx_doc.blocks if isinstance(b, Para) and b.ident == "ref:RFC2119")
    assert ref.text.startswith("[RFC2119]\n")
    raw_ref = next(b for b in raw_doc.blocks if isinstance(b, Para) and b.ident == "ref:RFC2119")
    assert not raw_ref.text.startswith("[RFC2119]\n")
    # The restructuring moves content but never loses it. The only unit changes are the
    # reference entries (key split onto its own line) and the endpoint header cells (joined
    # into one line): the multiset difference must be exactly those units and nothing else.
    from fidelity.model import units, block_lines, norm
    a = Counter(u for u, _ in units(raw_doc))
    b = Counter(u for u, _ in units(docx_doc))

    def para_units(p):
        return [norm(l) for l in block_lines(p) if norm(l)]

    raw_changed, new_changed = [], []
    for p in raw_doc.blocks:
        if isinstance(p, Para) and p.ident.startswith("ref:"):
            raw_changed += para_units(p)
    for t in tables(raw_doc):
        if len(t.rows) == 2 and len(t.rows[1]) == 1 and t.rows[1][0].colspan == 2:
            for cell in t.rows[0]:
                for blk in cell.blocks:
                    raw_changed += para_units(blk)
    for p in docx_doc.blocks:
        if isinstance(p, Para) and (p.ident.startswith("ref:") or p.style == "EndpointHeader"):
            new_changed += para_units(p)
    raw_ref = [u for p in raw_doc.blocks if isinstance(p, Para) and p.ident.startswith("ref:") for u in para_units(p)]
    new_ref = [u for p in docx_doc.blocks if isinstance(p, Para) and p.ident.startswith("ref:") for u in para_units(p)]
    assert len(raw_ref) == 38 and len(new_ref) == 76  # 37 distinct keys, RFC7617 listed twice
    assert len(raw_changed) - len(raw_ref) >= 22 and len(new_changed) - len(new_ref) >= 11  # header cells (some URLs wrap)
    # exact: whatever differs between the two models is precisely the changed units
    assert a - b == Counter(raw_changed) - Counter(new_changed)
    assert b - a == Counter(new_changed) - Counter(raw_changed)
    assert docx_doc.slugs["rfc7617"] == "ref:RFC7617" and docx_doc.slugs["rfc7617-2"] == "ref:RFC7617#2"


def test_known_source_anomalies_are_reported(docx_doc):
    kinds = Counter(f["kind"] for f in docx_doc.findings)
    dangling = {f["target"] for f in docx_doc.findings if f["kind"] == "dangling-anchor"}
    assert dangling == {
        "dangling:_rctaybmqy5s0", "dangling:_wzwrwiz8wvuc", "dangling:_ajzyjryzbne1",
        "dangling:_h1stnx7npfus", "dangling:lq5lkamlx4vg", "dangling:_dwru50atx72x",
    }
    mismatched = {f["text"] for f in docx_doc.findings if f["kind"] == "ref-link-mismatch"}
    assert {"RFC8259", "RFC8446"} <= mismatched
    assert any(f["kind"] == "duplicate-reference-key" and f["key"] == "RFC7617" for f in docx_doc.findings)
    assert any(f["kind"] == "duplicate-heading-title" and f["title"] == "Endpoints" for f in docx_doc.findings)
    assert kinds["toc-mismatch"] == 0
    assert kinds["unsupported-vmerge"] == 0


def test_url_fragment_links_are_external(docx_doc):
    """Word stores 'https://host/page#frag' as r:id + w:anchor; they must come out as one URL."""
    targets = {t for _, t, _ in links(docx_doc)}
    assert "url:https://www.oasis-open.org/committees/tc_home.php?wg_abbrev=cti#technical" in targets


def test_semantic_spans_and_slugs(docx_doc):
    from fidelity.model import spans
    assert spans(docx_doc, "type")["collection"] >= 1
    assert spans(docx_doc, "literal")["complete"] >= 1
    assert docx_doc.slugs["overview"] == "heading:1.6"
    assert docx_doc.slugs["overview-endpoints"] == "heading:1.6.3"
    assert docx_doc.slugs["rfc2119"] == "ref:RFC2119"
    assert docx_doc.ids["_g6vzg6qixpic"] == "heading:1.6"
