"""Canonical content model shared by the DOCX and Markdown readers.

Both readers produce a Document made of Heading, Para, Code, Table and Image blocks.
Inline text carries only the attributes that matter for fidelity: bold, italic,
monospace, semantic class (type / literal / alt) and link target.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Optional


@dataclass
class Inline:
    text: str
    bold: bool = False
    italic: bool = False
    mono: bool = False
    cls: Optional[str] = None
    link: Optional[str] = None

    def attrs(self):
        return (self.bold, self.italic, self.mono, self.cls, self.link)


@dataclass
class ListInfo:
    kind: str  # 'bullet' | 'number'
    level: int
    fmt: str = ""  # Word numFmt (decimal, lowerLetter, ...) for rendering; not compared


@dataclass
class Para:
    inlines: list = field(default_factory=list)
    list_info: Optional[ListInfo] = None
    mono: bool = False
    anchor_ids: list = field(default_factory=list)
    in_header: bool = False
    section: str = ""
    style: str = ""  # source paragraph style name (DOCX side only); not compared
    ident: str = ""  # link identity ('ref:RFC2119', 'para:...') when the paragraph is a link target
    standalone: bool = False  # never merged into a code block (rendering hint, DOCX side only)
    kind: str = "para"

    @property
    def text(self) -> str:
        return "".join(i.text for i in self.inlines)


@dataclass
class Heading:
    level: int
    number: str
    title: str
    inlines: list = field(default_factory=list)
    anchor_ids: list = field(default_factory=list)
    slug: str = ""
    section: str = ""
    kind: str = "heading"

    @property
    def text(self) -> str:
        return f"{self.number} {self.title}".strip()


@dataclass
class Code:
    lines: list
    section: str = ""
    kind: str = "code"


@dataclass
class Cell:
    blocks: list = field(default_factory=list)
    colspan: int = 1
    header: bool = False


@dataclass
class Table:
    rows: list = field(default_factory=list)
    section: str = ""
    kind: str = "table"

    def ncols(self) -> int:
        return max((sum(c.colspan for c in r) for r in self.rows), default=0)


@dataclass
class Image:
    src: str
    alt: str = ""
    section: str = ""
    kind: str = "image"


@dataclass
class Document:
    blocks: list = field(default_factory=list)
    ids: dict = field(default_factory=dict)     # anchor id -> identity
    slugs: dict = field(default_factory=dict)   # expected anchor slug -> identity
    meta: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)


# ----------------------------------------------------------------------------- text helpers

_WS = re.compile(r"[\s   ]+")


def norm(s: Optional[str]) -> str:
    """Whitespace-insensitive, NFC-normalised comparison form. Keeps every other character."""
    s = unicodedata.normalize("NFC", s or "")
    return _WS.sub(" ", s).strip()


def merge_inlines(inlines) -> list:
    out = []
    for i in inlines:
        if not i.text:
            continue
        if out and out[-1].attrs() == i.attrs():
            out[-1] = replace(out[-1], text=out[-1].text + i.text)
        else:
            out.append(replace(i))
    return out


def slugify(text: str) -> str:
    """STIX-style anchor: ascii, lowercase, hyphen-separated."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()


def github_slug(text: str) -> str:
    """Approximation of GitHub's automatic heading anchor."""
    t = norm(text).lower()
    t = re.sub(r"[^\w\- ]", "", t)
    return t.replace(" ", "-")


def normalize_number(num: str) -> str:
    return norm(num).rstrip(".:")


# A numbered heading in the Markdown: "1. Title", "1.1 Title", "Appendix A: Title".
# A level-1 number requires the trailing dot so that "10 June 2021" is not a heading number.
HEADING_NUM_RE = re.compile(
    r"^\s*(?:(Appendix\s+[A-Z])[.:]?|(\d+\.)|(\d+(?:\.\d+)+)\.?)\s+(.+?)\s*$"
)


def split_heading(text: str):
    m = HEADING_NUM_RE.match(text or "")
    if not m:
        return None, norm(text)
    num = m.group(1) or m.group(2) or m.group(3)
    return normalize_number(num), norm(m.group(4))


REF_KEY_RE = re.compile(r"^\s*\[([^\]]+)\]")


# ----------------------------------------------------------------------------- traversal

def iter_blocks(blocks, loc=""):
    """Yield (block, location) depth-first, descending into table cells."""
    for b in blocks:
        yield b, loc
        if isinstance(b, Table):
            for ri, row in enumerate(b.rows):
                for ci, cell in enumerate(row):
                    yield from iter_blocks(cell.blocks, f"{loc} T[r{ri}c{ci}]")


def assign_sections(doc: Document) -> None:
    current = ""

    def walk(blocks, section):
        nonlocal current
        for b in blocks:
            if isinstance(b, Heading):
                current = b.number
                b.section = current
                continue
            b.section = current
            if isinstance(b, Table):
                for row in b.rows:
                    for cell in row:
                        walk(cell.blocks, current)

    walk(doc.blocks, current)


def in_sections(section: str, wanted) -> bool:
    if not wanted:
        return True
    for w in wanted:
        w = normalize_number(w)
        if section == w or section.startswith(w + "."):
            return True
    return False


def section_titles(doc: Document) -> dict:
    return {b.number: b.title for b, _ in iter_blocks(doc.blocks) if isinstance(b, Heading)}


def is_reference_section(doc: Document, section: str, keywords) -> bool:
    titles = doc.meta.setdefault("_titles", section_titles(doc))
    # a paragraph in 1.3.2 belongs to 1.3 as well: check every prefix
    parts = section.split(".")
    for n in range(len(parts), 0, -1):
        title = titles.get(".".join(parts[:n]), "")
        if any(k.lower() in title.lower() for k in keywords):
            return True
    return False


def resolve_links(doc: Document, resolver) -> None:
    for b, _ in iter_blocks(doc.blocks):
        if isinstance(b, (Para, Heading)):
            for i in b.inlines:
                if i.link and i.link.startswith("anchor:"):
                    i.link = resolver(i.link[len("anchor:"):])


def is_code_line(p) -> bool:
    """A monospace paragraph that is plain code: no semantic span, bold or link on it.
    Type names, literals and property names are monospace too but stay paragraphs so their
    semantic attributes remain comparable."""
    return (
        isinstance(p, Para) and p.mono and not p.list_info and not p.standalone
        and not any(i.bold or i.link or i.cls in ("type", "literal") for i in p.inlines)
    )


def merge_code(blocks) -> list:
    """Merge runs of consecutive code-line paragraphs (blank paragraphs allowed inside) into Code blocks."""
    out, run = [], []

    def flush():
        trailing = []
        while run and not is_code_line(run[-1]):
            trailing.append(run.pop())  # trailing blanks stay ordinary paragraphs
        if run:
            lines = []
            for p in run:
                lines.extend(p.text.split("\n") if p.mono else [""])
            out.append(Code(lines=lines, section=run[0].section))
        out.extend(reversed(trailing))
        run.clear()

    for b in blocks:
        if is_code_line(b):
            run.append(b)
        elif isinstance(b, Para) and not b.text.strip() and run:
            run.append(b)
        else:
            flush()
            out.append(b)
    flush()
    return out


# ----------------------------------------------------------------------------- comparison views

def block_lines(b) -> list:
    if isinstance(b, Heading):
        return [b.text]
    if isinstance(b, Para):
        return b.text.split("\n")
    if isinstance(b, Code):
        return list(b.lines)
    return []


def units(doc: Document, sections=None) -> list:
    """Visible text units in document order: (normalised text, location)."""
    out = []
    for b, loc in iter_blocks(doc.blocks):
        if not in_sections(b.section, sections):
            continue
        for line in block_lines(b):
            n = norm(line)
            if n:
                out.append((n, f"§{b.section or 'front'}{loc}"))
    return out


def headings(doc: Document, sections=None) -> list:
    return [
        (b.level, b.number, b.title)
        for b, _ in iter_blocks(doc.blocks)
        if isinstance(b, Heading) and in_sections(b.section, sections)
    ]


def tables(doc: Document, sections=None) -> list:
    return [b for b, _ in iter_blocks(doc.blocks) if isinstance(b, Table) and in_sections(b.section, sections)]


def images(doc: Document, sections=None) -> list:
    return [b for b, _ in iter_blocks(doc.blocks) if isinstance(b, Image) and in_sections(b.section, sections)]


def cell_text(cell: Cell) -> str:
    lines = []
    for blk in cell.blocks:
        for line in block_lines(blk):
            n = norm(line)
            if n:
                lines.append(n)
    return "\n".join(lines)


def links(doc: Document, sections=None) -> list:
    """Ordered (text, target, location) for every link span."""
    out = []
    for b, loc in iter_blocks(doc.blocks):
        if not isinstance(b, (Para, Heading)) or not in_sections(b.section, sections):
            continue
        cur_text, cur_link = [], None
        for i in b.inlines:
            if i.link and i.link == cur_link:
                cur_text.append(i.text)
                continue
            if cur_link:
                out.append((norm("".join(cur_text)), cur_link, f"§{b.section or 'front'}{loc}"))
            cur_text, cur_link = ([i.text] if i.link else []), i.link
        if cur_link:
            out.append((norm("".join(cur_text)), cur_link, f"§{b.section or 'front'}{loc}"))
    return out


def spans(doc: Document, attr: str, sections=None) -> Counter:
    """Multiset of texts carrying an attribute (bold/italic/mono or class type/literal/alt)."""
    c = Counter()
    for b, _ in iter_blocks(doc.blocks):
        if not isinstance(b, Para) or b.in_header or not in_sections(b.section, sections):
            continue
        cur = []
        for i in b.inlines:
            on = (i.cls == attr) if attr in ("type", "literal", "alt") else bool(getattr(i, attr))
            if on:
                cur.append(i.text)
            elif not i.text.strip():
                # whitespace (a space, a line break) is transparent: it neither starts nor
                # ends a span, so renderer choices about where spaces sit do not matter
                if cur:
                    cur.append(i.text)
            elif cur:
                n = norm("".join(cur))
                if n:
                    c[n] += 1
                cur = []
        if cur:
            n = norm("".join(cur))
            if n:
                c[n] += 1
    return c


def mono_lines(doc: Document, sections=None) -> Counter:
    """Multiset of monospace lines (code blocks and all-monospace paragraphs), exact leading whitespace."""
    c = Counter()
    for b, _ in iter_blocks(doc.blocks):
        if not in_sections(b.section, sections):
            continue
        if isinstance(b, Code):
            lines = b.lines  # indentation is content in a code block
        elif isinstance(b, Para) and b.mono:
            lines = [l.strip() for l in b.text.split("\n")]  # leading space is not rendered in a paragraph
        else:
            continue
        for l in lines:
            if l.strip():
                c[unicodedata.normalize("NFC", l.rstrip()).replace("\t", "    ")] += 1
    return c


def list_items(doc: Document, sections=None) -> list:
    out = []
    for b, _ in iter_blocks(doc.blocks):
        if isinstance(b, Para) and b.list_info and in_sections(b.section, sections):
            n = norm(b.text.split("\n")[0])
            if n:
                out.append((b.list_info.kind, b.list_info.level, n))
    return out
