"""DOCX -> canonical content model, driven by a Profile.

Walks the WordprocessingML body directly (python-docx is used for package access and
relationships). Everything visible is modelled: headings with computed outline numbers,
paragraphs with inline attributes, list membership, tables with spans, images, hyperlinks
with their targets, bookmarks. Word's own table of contents is dropped and kept in
``meta['toc']`` as an oracle for heading numbers.
"""
from __future__ import annotations

import re
from collections import Counter

import docx
from lxml import etree

from .model import (
    Cell, Code, Document, Heading, Image, Inline, ListInfo, Para, Table, REF_KEY_RE,
    assign_sections, github_slug, is_reference_section, iter_blocks, links, merge_code,
    merge_inlines, norm, resolve_links, slugify,
)
from .profile import Profile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def w(tag: str) -> str:
    return "{%s}%s" % (W, tag)


def _on(el) -> bool:
    """Toggle property present and not switched off."""
    return el is not None and (el.get(w("val")) or "true") not in ("0", "false", "off")


TOC_ENTRY_RE = re.compile(r"^(Appendix\s+[A-Z])\.?\s+(.*)$|^(\d+(?:\.\d+)*)\s+(.*)$")


def parse_toc_entry(entry: str):
    """'1.1 IPR Policy\\t7' -> ('1.1', 'IPR Policy'); returns None if unparseable."""
    parts = entry.split("\t")
    if len(parts) > 1 and parts[-1].strip().isdigit():
        parts = parts[:-1]
    m = TOC_ENTRY_RE.match(norm(" ".join(parts)))
    if not m:
        return None
    return (m.group(1) or m.group(3), norm(m.group(2) or m.group(4)))


class DocxReader:
    def __init__(self, path, profile: Profile):
        self.path = str(path)
        self.profile = profile
        self.doc = docx.Document(self.path)
        self.body = self.doc.element.body
        self.rels = dict(self.doc.part.rels.items())
        self.style_names = {}
        for st in self.doc.styles.element.findall(w("style")):
            sid = st.get(w("styleId"))
            nm = st.find(w("name"))
            self.style_names[sid] = nm.get(w("val")) if nm is not None else sid
        self.num_fmt = self._load_numbering()
        self.counters = [0] * 10
        self.appendix = 0
        self.cur_section = ""
        self.toc_entries = []
        self.findings = []

    # ------------------------------------------------------------------ package parts
    def _load_numbering(self) -> dict:
        fmt = {}
        try:
            numbering = self.doc.part.numbering_part.element
        except Exception:
            return fmt
        abstract = {}
        for an in numbering.findall(w("abstractNum")):
            aid = an.get(w("abstractNumId"))
            for lvl in an.findall(w("lvl")):
                f = lvl.find(w("numFmt"))
                abstract.setdefault(aid, {})[lvl.get(w("ilvl"))] = f.get(w("val")) if f is not None else "decimal"
        for num in numbering.findall(w("num")):
            a = num.find(w("abstractNumId"))
            if a is None:
                continue
            for ilvl, f in abstract.get(a.get(w("val")), {}).items():
                fmt[(num.get(w("numId")), ilvl)] = f
        return fmt

    # ------------------------------------------------------------------ runs
    def _run(self, r, link=None, images=None) -> list:
        rPr = r.find(w("rPr"))
        bold = italic = mono = False
        cls = None
        if rPr is not None:
            if rPr.find(w("vanish")) is not None or rPr.find(w("webHidden")) is not None:
                return []
            bold = _on(rPr.find(w("b")))
            italic = _on(rPr.find(w("i")))
            f = rPr.find(w("rFonts"))
            if f is not None:
                fonts = {f.get(w("ascii")), f.get(w("hAnsi"))}
                mono = bool(fonts & set(self.profile.mono_fonts))
            s = rPr.find(w("shd"))
            if s is not None:
                cls = self.profile.shading_classes.get((s.get(w("fill")) or "").upper())
            c = rPr.find(w("color"))
            if c is not None and (c.get(w("val")) or "").upper() in self.profile.label_colours:
                bold = True
            if bold and self.profile.bold_drops_mono and not cls:
                mono = False  # PRD D24: bold property names and labels render as plain bold
        parts = []
        for ch in r:
            tag = etree.QName(ch).localname
            if tag == "t":
                parts.append(ch.text or "")
            elif tag == "tab":
                parts.append("\t")
            elif tag in ("br", "cr"):
                parts.append("\n")
            elif tag == "noBreakHyphen":
                parts.append("-")
            elif tag == "drawing" and images is not None:
                for blip in ch.iter("{%s}blip" % A_NS):
                    rid = blip.get("{%s}embed" % R_NS)
                    part = self.doc.part.related_parts.get(rid) if rid else None
                    src = str(part.partname).rsplit("/", 1)[-1] if part is not None else (rid or "?")
                    images.append(Image(src=src))
        text = "".join(parts)
        return [Inline(text, bold, italic, mono, cls, link)] if text else []

    def _link_target(self, h) -> str:
        anchor = h.get(w("anchor"))
        rid = h.get("{%s}id" % R_NS)
        if rid:
            rel = self.rels.get(rid)
            target = rel.target_ref if rel is not None else rid
            return "url:" + target + ("#" + anchor if anchor else "")
        if anchor:
            return "anchor:" + anchor
        return "anchor:?"

    # ------------------------------------------------------------------ paragraphs
    def _plain(self, p) -> str:
        out = []
        for el in p.iter():
            tag = etree.QName(el).localname
            if tag == "t":
                out.append(el.text or "")
            elif tag == "tab":
                out.append("\t")
            elif tag in ("br", "cr"):
                out.append("\n")
        return "".join(out)

    def _paragraph(self, p, in_header=False) -> list:
        pPr = p.find(w("pPr"))
        style_id, num = None, None
        if pPr is not None:
            ps = pPr.find(w("pStyle"))
            style_id = ps.get(w("val")) if ps is not None else None
            npr = pPr.find(w("numPr"))
            if npr is not None:
                ni, il = npr.find(w("numId")), npr.find(w("ilvl"))
                if ni is not None:
                    num = (ni.get(w("val")), il.get(w("val")) if il is not None else "0")
        style_name = (self.style_names.get(style_id, style_id) or "Normal")
        if any(style_name.lower().startswith(pfx.lower()) for pfx in self.profile.skip_style_prefixes):
            self.toc_entries.append(self._plain(p))
            return []
        if any((it.text or "").lstrip().startswith("TOC") for it in p.iter(w("instrText"))):
            return []

        inlines, images = [], []
        anchors = [b.get(w("name")) for b in p.iter(w("bookmarkStart"))]
        for ch in p:
            tag = etree.QName(ch).localname
            if tag == "r":
                inlines += self._run(ch, images=images)
            elif tag == "hyperlink":
                link = self._link_target(ch)
                before = len(inlines)
                for r in ch.iter(w("r")):
                    inlines += self._run(r, link=link, images=images)
                if not "".join(i.text for i in inlines[before:]).strip():
                    self.findings.append({"kind": "empty-link", "target": link, "section": self.cur_section})
            elif tag in ("ins", "smartTag", "sdt", "sdtContent", "customXml"):
                for r in ch.iter(w("r")):
                    inlines += self._run(r, images=images)
        inlines = merge_inlines(inlines)
        text = "".join(i.text for i in inlines)
        blocks = list(images)

        level = self.profile.heading_styles.get(style_id)
        if level:
            self.counters[level] += 1
            for l in range(level + 1, 10):
                self.counters[l] = 0
            number = ".".join(str(self.counters[l]) for l in range(1, level + 1))
            self.cur_section = number
            blocks.append(Heading(level=level, number=number, title=norm(text), inlines=inlines, anchor_ids=anchors))
            return blocks
        if style_id in self.profile.appendix_heading_styles:
            self.appendix += 1
            for l in range(1, 10):
                self.counters[l] = 0
            number = self.profile.appendix_number_format.format(letter=chr(ord("A") + self.appendix - 1), n=self.appendix)
            self.cur_section = number
            blocks.append(Heading(level=1, number=number, title=norm(text), inlines=inlines, anchor_ids=anchors))
            return blocks
        if norm(text) in self.profile.skip_paragraph_texts:
            return blocks

        li = None
        if num:
            f = self.num_fmt.get(num, "decimal")
            li = ListInfo("bullet" if f == "bullet" else "number", int(num[1]), f)
        mono = bool(text.strip()) and all(i.mono for i in inlines if i.text.strip())
        blocks.append(Para(inlines=inlines, list_info=li, mono=mono, anchor_ids=anchors, in_header=in_header, style=style_name))
        return blocks

    # ------------------------------------------------------------------ tables
    def _table(self, tbl) -> Table:
        rows = []
        for ri, tr in enumerate(tbl.findall(w("tr"))):
            cells = []
            for tc in tr.findall(w("tc")):
                span = 1
                tcPr = tc.find(w("tcPr"))
                if tcPr is not None:
                    gs = tcPr.find(w("gridSpan"))
                    if gs is not None:
                        span = int(gs.get(w("val")) or 1)
                    if tcPr.find(w("vMerge")) is not None:
                        self.findings.append({"kind": "unsupported-vmerge", "section": self.cur_section})
                blocks = []
                for ch in tc:
                    tag = etree.QName(ch).localname
                    if tag == "p":
                        blocks += self._paragraph(ch, in_header=(ri == 0))
                    elif tag == "tbl":
                        blocks.append(self._table(ch))
                cells.append(Cell(blocks=merge_code(blocks), colspan=span, header=(ri == 0)))
            rows.append(cells)
        return Table(rows=rows)

    # ------------------------------------------------------------------ document
    def read(self) -> Document:
        blocks = []
        for ch in self.body:
            tag = etree.QName(ch).localname
            if tag == "p":
                blocks += self._paragraph(ch)
            elif tag == "tbl":
                blocks.append(self._table(ch))
            elif tag in ("sdt", "sdtContent"):
                for inner in ch.iter():
                    if etree.QName(inner).localname == "p":
                        blocks += self._paragraph(inner)
        blocks = self._restructure(blocks)
        doc = Document(blocks=merge_code(blocks))
        assign_sections(doc)
        self._identities(doc)
        resolve_links(doc, lambda name: doc.ids.get(name, "dangling:" + name))
        doc.meta["source"] = self.path
        doc.meta["toc"] = self.toc_entries
        doc.meta["toc_headings"] = [e for e in (parse_toc_entry(t) for t in self.toc_entries) if e]
        self._audit(doc)
        doc.findings = self.findings
        return doc

    def _restructure(self, blocks: list) -> list:
        """Profile-driven representation changes applied to the reference model so that the
        Markdown can use a different structure without losing content (PRD D10/Q7):
        - unwrap_tables: a table of N rows whose last row is one spanned cell (the TAXII
          endpoint tables) becomes: one monospace paragraph joining the header cells, then
          the spanned cell's blocks.
        - drop_empty_tables: tables without any text are dropped."""
        out = []
        rule = self.profile.unwrap_tables
        for b in blocks:
            if isinstance(b, Table):
                has_text = any(
                    norm(line)
                    for r in b.rows for c in r for blk in c.blocks
                    for line in (blk.lines if isinstance(blk, Code) else blk.text.split("\n") if isinstance(blk, Para) else [])
                )
                if self.profile.drop_empty_tables and not has_text:
                    imgs = [blk for r in b.rows for c in r for blk in c.blocks if isinstance(blk, Image)]
                    if imgs:  # a table used only as a picture frame (TAXII: Figures 1.2 and 1.3)
                        self.findings.append({"kind": "unwrapped-image-table", "images": [i.src for i in imgs]})
                        out.extend(imgs)
                    else:
                        self.findings.append({"kind": "dropped-empty-table", "rows": len(b.rows)})
                    continue
                if rule and len(b.rows) == rule.get("rows") and len(b.rows[-1]) == 1 \
                        and b.rows[-1][0].colspan == rule.get("last_row_colspan"):
                    head = []
                    for cell in b.rows[0]:
                        for p in cell.blocks:
                            if isinstance(p, Para) and p.text.strip():
                                head.append(Inline(p.text.strip(), mono=True))
                    joined = []
                    for i, inl in enumerate(head):
                        if i:
                            joined.append(Inline(" ", mono=True))
                        joined.append(inl)
                    out.append(Para(inlines=merge_inlines(joined), mono=True, style="EndpointHeader", standalone=True))
                    for blk in b.rows[-1][0].blocks:
                        if isinstance(blk, Para):
                            blk.in_header = False
                        out.append(blk)
                    continue
            out.append(b)
        return out

    def _identities(self, doc: Document) -> None:
        heads = [b for b, _ in iter_blocks(doc.blocks) if isinstance(b, Heading)]
        dup = {s for s, c in Counter(slugify(h.title) for h in heads).items() if c > 1}
        parents = {}
        for h in heads:
            s = slugify(h.title)
            if s in dup:
                parent = parents.get(h.level - 1)
                s = f"{parent}-{s}" if parent else s
            parents[h.level] = s
            for l in list(parents):
                if l > h.level:
                    del parents[l]
            h.slug = s
            ident = "heading:" + h.number
            doc.slugs[s] = ident
            doc.slugs.setdefault(github_slug(h.text), ident)
            for a in h.anchor_ids:
                doc.ids[a] = ident
        ref_keys = Counter()
        for b, _ in iter_blocks(doc.blocks):
            if not isinstance(b, Para):
                continue
            m = REF_KEY_RE.match(b.text)
            ident = None
            if m and is_reference_section(doc, b.section, self.profile.reference_section_keywords):
                key = norm(m.group(1))
                ref_keys[key] += 1
                ident = f"ref:{key}" + (f"#{ref_keys[key]}" if ref_keys[key] > 1 else "")
                doc.slugs.setdefault(slugify(key) + (f"-{ref_keys[key]}" if ref_keys[key] > 1 else ""), ident)
                if re.match(r"^\s*\[[^\]]+\]\S", b.text):
                    self.findings.append({"kind": "reference-key-no-space", "text": b.text[:60], "section": b.section})
                if self.profile.split_reference_keys:
                    # The Markdown puts the key on its own line (STIX style); do the same here so
                    # the text units agree: '[KEY] \tAuthor...' -> '[KEY]' + '\n' + 'Author...'
                    first = b.inlines[0]
                    m2 = re.match(r"^(\s*\[[^\]]+\])[ \t]*", first.text)
                    if m2 and m2.end() <= len(first.text):
                        from dataclasses import replace as _replace
                        rest = first.text[m2.end():]
                        b.inlines[0] = _replace(first, text=m2.group(1) + "\n" + rest)
            elif b.anchor_ids:
                ident = "para:" + norm(b.text)[:60]
            if ident:
                b.ident = ident
                for a in b.anchor_ids:
                    doc.ids[a] = ident
        for key, c in ref_keys.items():
            if c > 1:
                self.findings.append({"kind": "duplicate-reference-key", "key": key, "count": c})
        doc.meta["reference_keys"] = dict(ref_keys)

    def _audit(self, doc: Document) -> None:
        for text, target, loc in links(doc):
            if target.startswith("dangling:"):
                self.findings.append({"kind": "dangling-anchor", "text": text, "target": target, "loc": loc})
            elif target.startswith("ref:"):
                want = re.sub(r"\W", "", text).lower()
                got = re.sub(r"\W", "", target[4:].split("#")[0]).lower()
                if want and want != got:
                    self.findings.append({"kind": "ref-link-mismatch", "text": text, "target": target, "loc": loc})
            if text.startswith("[") != text.endswith("]") and re.match(r"^\[?[A-Za-z0-9 ._-]+\]?$", text):
                self.findings.append({"kind": "odd-link-span", "text": text, "target": target, "loc": loc})
        titles = Counter(h.title for h, _ in iter_blocks(doc.blocks) if isinstance(h, Heading))
        for t, c in titles.items():
            if c > 1:
                self.findings.append({"kind": "duplicate-heading-title", "title": t, "count": c})
        computed = [(h.number, h.title) for h, _ in iter_blocks(doc.blocks) if isinstance(h, Heading)]
        if doc.meta["toc_headings"] and doc.meta["toc_headings"] != computed:
            self.findings.append({"kind": "toc-mismatch", "toc": len(doc.meta["toc_headings"]), "computed": len(computed)})
        non_ascii = Counter()
        for b, _ in iter_blocks(doc.blocks):
            if isinstance(b, (Para, Heading)):
                for ch in b.text:
                    if ord(ch) > 127:
                        non_ascii[ch] += 1
        doc.meta["non_ascii"] = dict(non_ascii.most_common())


def read_docx(path, profile: Profile) -> Document:
    return DocxReader(path, profile).read()
