"""Markdown -> canonical content model.

The Markdown is rendered with cmark-gfm (GitHub's engine) with raw HTML enabled and the
resulting HTML is walked. Pipe tables and HTML tables therefore look the same, and
``<span class=...>`` / ``<strong>`` / ``<code>`` inside raw HTML are seen exactly as
GitHub shows them.
"""
from __future__ import annotations

from collections import Counter

import cmarkgfm
from cmarkgfm.cmark import Options
from lxml import html as lhtml

from .model import (
    Cell, Code, Document, Heading, Image, Inline, ListInfo, Para, Table, REF_KEY_RE,
    assign_sections, github_slug, is_reference_section, iter_blocks, links, merge_code,
    merge_inlines, norm, resolve_links, split_heading,
)
from .profile import Profile

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
CONTAINER_TAGS = {"div", "blockquote", "section", "details", "figure", "summary", "center"}


def render_html(md_text: str) -> str:
    return cmarkgfm.github_flavored_markdown_to_html(md_text, options=Options.CMARK_OPT_UNSAFE)


class MdReader:
    def __init__(self, text: str, profile: Profile):
        self.text = text
        self.profile = profile
        self.pending_ids: list = []
        self.id_counts: Counter = Counter()
        self.toc: list = []
        self.in_toc = False
        self.findings: list = []

    # ------------------------------------------------------------------ ids
    def _register_id(self, el) -> None:
        i = el.get("id")
        if i:
            self.pending_ids.append(i)
            self.id_counts[i] += 1

    def _take_ids(self) -> list:
        ids, self.pending_ids = self.pending_ids, []
        return ids

    # ------------------------------------------------------------------ inline
    @staticmethod
    def _mk(text: str, a: dict) -> Inline:
        return Inline(text, a.get("bold", False), a.get("italic", False), a.get("mono", False), a.get("cls"), a.get("link"))

    def _inline_content(self, el, a: dict) -> list:
        out = []
        if el.text:
            out.append(self._mk(el.text, a))
        for ch in el:
            if not isinstance(ch.tag, str):  # comment / processing instruction
                if ch.tail:
                    out.append(self._mk(ch.tail, a))
                continue
            out += self._inline_el(ch, a)
            if ch.tail:
                out.append(self._mk(ch.tail, a))
        return out

    def _inline_el(self, ch, a: dict) -> list:
        tag = ch.tag
        self._register_id(ch)
        a = dict(a)
        if tag in ("strong", "b"):
            a["bold"] = True
        elif tag in ("em", "i"):
            a["italic"] = True
        elif tag in ("code", "tt", "kbd", "samp"):
            a["mono"] = True
        elif tag == "span":
            for c in (ch.get("class") or "").split():
                if c in self.profile.md_span_classes:
                    a["cls"] = self.profile.md_span_classes[c]
                    a["mono"] = True  # the STIX stylesheet renders these classes in Consolas
        elif tag == "a":
            href = ch.get("href")
            if href:
                a["link"] = ("anchor:" + href[1:]) if href.startswith("#") else "url:" + href
        elif tag == "br":
            return [self._mk("\n", a)]
        elif tag == "img":
            return []
        return self._inline_content(ch, a)

    def _para(self, inlines, in_header=False, list_info=None) -> Para:
        inl = merge_inlines(inlines)
        text = "".join(i.text for i in inl)
        mono = bool(text.strip()) and all(i.mono for i in inl if i.text.strip())
        return Para(inlines=inl, list_info=list_info, mono=mono, anchor_ids=self._take_ids(), in_header=in_header)

    # ------------------------------------------------------------------ blocks
    def _children(self, el, out: list, in_header=False, toplevel=False) -> None:
        cur: list = []

        def flush():
            # `<br><br>` (two line breaks with nothing but whitespace between) is the STIX
            # device for a paragraph break inside a table cell: split there.
            groups, grp, breaks = [], [], 0
            for i in cur:
                if i.text == "\n":
                    breaks += 1
                    grp.append(i)
                    continue
                if breaks >= 2 and any(x.text.strip() for x in grp):
                    groups.append(grp)
                    grp = []
                if i.text.strip():
                    breaks = 0
                grp.append(i)
            groups.append(grp)
            for g in groups:
                while g and not g[0].text.strip():
                    g.pop(0)
                while g and not g[-1].text.strip():
                    g.pop()
                if g:
                    p = self._para(g, in_header=in_header)
                    if p.text.strip():
                        out.append(p)
            cur.clear()

        if el.text and el.text.strip():
            cur.append(Inline(el.text))
        for ch in el:
            tag = ch.tag if isinstance(ch.tag, str) else None
            if tag is None:
                if ch.tail:
                    cur.append(Inline(ch.tail))
                continue
            if toplevel and self.in_toc and tag not in HEADING_TAGS:
                if tag in ("ul", "ol"):
                    self._collect_toc(ch)
                continue
            if tag in HEADING_TAGS:
                flush()
                self._heading(ch, out)
            elif tag == "p":
                flush()
                self._register_id(ch)
                for im in ch.iter("img"):
                    out.append(Image(src=im.get("src", ""), alt=im.get("alt", "")))
                inl = self._inline_content(ch, {})
                p = self._para(inl, in_header=in_header)
                if p.text.strip():
                    out.append(p)
            elif tag == "pre":
                flush()
                self._register_id(ch)
                code = ch.text_content()
                out.append(Code(lines=code.rstrip("\n").split("\n")))
            elif tag == "table":
                flush()
                self._register_id(ch)
                out.append(self._table(ch))
            elif tag in ("ul", "ol"):
                flush()
                self._list(ch, out, "bullet" if tag == "ul" else "number", 0, in_header)
            elif tag in CONTAINER_TAGS:
                flush()
                self._register_id(ch)
                self._children(ch, out, in_header=in_header, toplevel=toplevel)
            elif tag == "img":
                out.append(Image(src=ch.get("src", ""), alt=ch.get("alt", "")))
            elif tag == "hr":
                flush()
            elif tag == "br":
                cur.append(Inline("\n"))
            else:
                cur += self._inline_el(ch, {})
            if ch.tail and (tag not in HEADING_TAGS):
                cur.append(Inline(ch.tail))
        flush()

    def _heading(self, h, out: list) -> None:
        inl = merge_inlines(self._inline_content(h, {}))
        text = norm("".join(i.text for i in inl))
        ids = self._take_ids()
        if text.lower() == self.profile.toc_heading_text.lower():
            self.in_toc = True
            return
        self.in_toc = False
        number, title = split_heading(text)
        if number:
            out.append(Heading(level=int(h.tag[1]), number=number, title=title, inlines=inl, anchor_ids=ids))
        else:
            out.append(Para(inlines=inl, anchor_ids=ids))

    def _collect_toc(self, lst) -> None:
        for li in lst:
            if li.tag != "li":
                continue
            own = [li.text or ""]
            href = None
            for ch in li:
                if ch.tag in ("ul", "ol"):
                    self._collect_toc(ch)
                    continue
                if ch.tag == "a" and href is None:
                    href = ch.get("href")
                own.append(ch.text_content())
                own.append(ch.tail or "")
            number, title = split_heading(norm("".join(own)))
            self.toc.append((number, title, href))

    def _list(self, lst, out: list, kind: str, level: int, in_header: bool) -> None:
        for li in lst:
            if li.tag != "li":
                continue
            self._register_id(li)
            cur: list = []
            first_done = False

            def flush(cur=cur):
                nonlocal first_done
                if cur and "".join(i.text for i in cur).strip():
                    out.append(self._para(cur, in_header, None if first_done else ListInfo(kind, level)))
                    first_done = True
                cur.clear()

            if li.text:
                cur.append(Inline(li.text))
            for ch in li:
                tag = ch.tag if isinstance(ch.tag, str) else None
                if tag in ("ul", "ol"):
                    flush()
                    self._list(ch, out, "bullet" if tag == "ul" else "number", level + 1, in_header)
                elif tag == "p":
                    flush()
                    cur.extend(self._inline_content(ch, {}))
                    flush()
                elif tag == "pre":
                    flush()
                    out.append(Code(lines=ch.text_content().rstrip("\n").split("\n")))
                elif tag == "table":
                    flush()
                    out.append(self._table(ch))
                elif tag in HEADING_TAGS:
                    flush()
                    self._heading(ch, out)
                elif tag is None:
                    pass
                else:
                    cur.extend(self._inline_el(ch, {}))
                if ch.tail:
                    cur.append(Inline(ch.tail))
            flush()

    def _table(self, t) -> Table:
        rows = []
        for sec in t:
            if not isinstance(sec.tag, str):
                continue
            trs = [sec] if sec.tag == "tr" else [x for x in sec if x.tag == "tr"]
            for tr in trs:
                cells = []
                for c in tr:
                    if c.tag not in ("td", "th"):
                        continue
                    self._register_id(c)
                    blocks: list = []
                    self._children(c, blocks, in_header=(c.tag == "th"))
                    cells.append(Cell(blocks=blocks, colspan=int(c.get("colspan") or 1), header=(c.tag == "th")))
                rows.append(cells)
        return Table(rows=rows)

    # ------------------------------------------------------------------ document
    def read(self) -> Document:
        root = lhtml.fragment_fromstring(render_html(self.text), create_parent="div")
        blocks: list = []
        self._children(root, blocks, toplevel=True)
        # Code blocks come from <pre> only; a paragraph made of inline code stays a paragraph
        # (the DOCX side keeps such paragraphs too: bold/typed/standalone monospace lines).
        doc = Document(blocks=blocks)
        assign_sections(doc)
        self._identities(doc)
        resolve_links(doc, lambda name: doc.ids.get(name, "unresolved:" + name))
        doc.meta["toc"] = self.toc
        self._hygiene(doc)
        doc.findings = self.findings
        return doc

    def _identities(self, doc: Document) -> None:
        ref_keys = Counter()
        for b, _ in iter_blocks(doc.blocks):
            if isinstance(b, Heading):
                ident = "heading:" + b.number
                for a in b.anchor_ids:
                    doc.ids[a] = ident
                doc.ids.setdefault(github_slug(b.text), ident)
            elif isinstance(b, Para):
                m = REF_KEY_RE.match(b.text)
                ident = None
                if m and is_reference_section(doc, b.section, self.profile.reference_section_keywords):
                    key = norm(m.group(1))
                    ref_keys[key] += 1
                    ident = f"ref:{key}" + (f"#{ref_keys[key]}" if ref_keys[key] > 1 else "")
                elif b.anchor_ids:
                    ident = "para:" + norm(b.text)[:60]
                if ident:
                    for a in b.anchor_ids:
                        doc.ids[a] = ident
        doc.meta["reference_keys"] = dict(ref_keys)

    def _hygiene(self, doc: Document) -> None:
        for text, target, loc in links(doc):
            if target.startswith("unresolved:"):
                self.findings.append({"kind": "unresolved-anchor", "target": target, "text": text, "loc": loc})
        for i, c in self.id_counts.items():
            if c > 1:
                self.findings.append({"kind": "duplicate-id", "id": i, "count": c})
        heads = {(h.number, h.title): h for h, _ in iter_blocks(doc.blocks) if isinstance(h, Heading)}
        if self.toc:
            for number, title, href in self.toc:
                h = heads.get((number, title))
                if h is None:
                    self.findings.append({"kind": "toc-entry-without-heading", "number": number, "title": title})
                elif not href or doc.ids.get(href[1:]) != "heading:" + number:
                    self.findings.append({"kind": "toc-link-mismatch", "number": number, "title": title, "href": href})
            listed = {(n, t) for n, t, _ in self.toc}
            for key in heads:
                if key not in listed:
                    self.findings.append({"kind": "heading-missing-from-toc", "number": key[0], "title": key[1]})
        for h, _ in iter_blocks(doc.blocks):
            if isinstance(h, Heading) and not h.anchor_ids:
                self.findings.append({"kind": "heading-without-anchor", "number": h.number, "title": h.title})


def read_md(path_or_text, profile: Profile, is_text=False) -> Document:
    text = path_or_text if is_text else open(path_or_text, encoding="utf8").read()
    return MdReader(text, profile).read()
