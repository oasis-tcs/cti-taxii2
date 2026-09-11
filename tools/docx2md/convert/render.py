"""Render the canonical DOCX model as Markdown in the conventions of stix-v2.1.md.

Everything here is representation. Content comes from the model unchanged; the fidelity
harness (`python -m fidelity verify`) is the judge of whether that promise held.
"""
from __future__ import annotations

import html
import re
import zipfile
from dataclasses import replace
from pathlib import Path

from fidelity.model import (
    Code, Document, Heading, Image, Inline, Para, Table, REF_KEY_RE, is_reference_section, iter_blocks, norm,
)
from fidelity.profile import Profile

HARD_BREAK = " \\\n"
TABLE_OPEN = '<table border="1" cellspacing="0" cellpadding="6" width="100%">'

_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>~])")
_ENTITY_LIKE = re.compile(r"&(?=[#A-Za-z0-9]+;)")
_LINE_START = re.compile(r"^(\s*)([#>+\-])(?=\s|$)")
_ORDERED_START = re.compile(r"^(\s*\d+)([.)])(?=\s|$)")


def escape_md(text: str) -> str:
    text = _MD_SPECIAL.sub(r"\\\1", text)
    return _ENTITY_LIKE.sub(r"\\&", text)


def escape_line_start(line: str) -> str:
    m = _LINE_START.match(line)
    if m:
        return m.group(1) + "\\" + line[len(m.group(1)):]
    m = _ORDERED_START.match(line)
    if m:  # "1. text" would start an ordered list: escape the delimiter, not the digit
        return m.group(1) + "\\" + line[len(m.group(1)):]
    return line


def split_ws(s: str):
    """(leading whitespace, body, trailing whitespace)"""
    body = s.strip()
    if not body:
        return s, "", ""
    lead = s[: len(s) - len(s.lstrip())]
    trail = s[len(s.rstrip()):]
    return lead, body, trail


def code_span(text: str) -> str:
    """Inline code keeping the text's own whitespace inside the span, so that a monospace run
    split across differently formatted pieces stays one monospace run when rendered.
    cmark strips one space from each end only when both ends are spaces: pad in that case."""
    if not text:
        return text
    runs = re.findall(r"`+", text)
    fence = "`" * (max(len(r) for r in runs) + 1 if runs else 1)
    body = text
    if (body.startswith(" ") and body.endswith(" ") and body.strip()) or body.startswith("`") or body.endswith("`"):
        body = f" {body} "
    return f"{fence}{body}{fence}"


def is_json(lines) -> bool:
    for l in lines:
        if l.strip():
            return l.lstrip()[0] in "{["
    return False


def split_lines(inlines) -> list:
    """Split an inline sequence on '\\n' into a list of inline sequences."""
    lines, cur = [], []
    for i in inlines:
        parts = i.text.split("\n")
        for k, part in enumerate(parts):
            if k:
                lines.append(cur)
                cur = []
            if part:
                cur.append(replace(i, text=part))
    lines.append(cur)
    return lines


class Renderer:
    def __init__(self, doc: Document, profile: Profile, resolutions=None):
        self.doc = doc
        self.profile = profile
        self.resolutions = resolutions or []
        self.warnings: list = []
        self.cls = profile.md_class_names or {"type": "stixtype", "literal": "stixliteral", "alt": "stixalt", "header": "stixtr"}
        self.anchor: dict = {}
        for b, _ in iter_blocks(doc.blocks):
            if isinstance(b, Heading):
                self.anchor["heading:" + b.number] = b.slug
        for slug, ident in doc.slugs.items():
            if ident.startswith("ref:") and ident not in self.anchor:
                self.anchor[ident] = slug
        self.ref_keywords = profile.reference_section_keywords
        self._apply_resolutions()

    # ------------------------------------------------------------------ links
    def _apply_resolutions(self) -> None:
        """Rewrite link spans per the resolutions file (target and, if given, span text)."""
        for b, _ in iter_blocks(self.doc.blocks):
            if not isinstance(b, (Para, Heading)):
                continue
            inl = b.inlines
            new, i = [], 0
            while i < len(inl):
                if not inl[i].link:
                    new.append(inl[i])
                    i += 1
                    continue
                j = i
                while j < len(inl) and inl[j].link == inl[i].link:
                    j += 1
                span = inl[i:j]
                text = norm("".join(x.text for x in span))
                target = inl[i].link
                res = next((r for r in self.resolutions if r.get("docx") == target and r.get("text", "*") in ("*", text)), None)
                if res is not None:
                    md_target = res.get("md")
                    if res.get("md_text") is not None and text.startswith(res["md_text"]):
                        remainder = "".join(x.text for x in span)[len(res["md_text"]):]
                        span = [replace(span[0], text=res["md_text"], link=md_target)]
                        if remainder:
                            span.append(replace(span[0], text=remainder, link=None, bold=False, mono=False, cls=None))
                    else:
                        span = [replace(x, link=md_target) for x in span]
                new.extend(span)
                i = j
            b.inlines = new

    def href(self, target) -> str | None:
        if not target:
            return None
        if target.startswith("url:"):
            return target[4:]
        slug = self.anchor.get(target)
        if slug:
            return "#" + slug
        self.warnings.append(f"unresolved link target {target}")
        return None

    # ------------------------------------------------------------------ inline: markdown context
    def md_atom(self, i: Inline) -> str:
        text = i.text
        if i.cls:
            core = f'<span class="{self.cls[i.cls]}">{escape_md(text)}</span>' if text.strip() else code_span(text)
        elif i.mono:
            core = code_span(text)
        else:
            core = escape_md(text)
        if i.link:
            href = self.href(i.link)
            if href:
                lead, body, trail = split_ws(core)
                plain = text.strip()
                if body and (plain == href or plain == href.replace("mailto:", "", 1)):
                    core = f"{lead}<{plain}>{trail}"
                elif body:
                    core = f"{lead}[{body}]({href}){trail}"
        return core

    def md_inlines(self, inlines) -> str:
        groups = []
        for inl in inlines:
            key = (inl.bold, inl.italic)
            if groups and groups[-1][0] == key:
                groups[-1][1].append(inl)
            else:
                groups.append((key, [inl]))
        out = []
        for (bold, italic), grp in groups:
            inner = "".join(self.md_atom(x) for x in grp)
            lead, body, trail = split_ws(inner)
            if body:
                if bold:
                    body = f"**{body}**"
                if italic:
                    body = f"*{body}*"
            out.append(f"{lead}{body}{trail}")
        return "".join(out)

    def md_para_lines(self, inlines) -> list:
        lines = []
        for line in split_lines(inlines):
            if any(x.text.strip() for x in line):
                lines.append(escape_line_start(self.md_inlines(line).strip()))
        return lines

    def md_para(self, p: Para) -> str:
        if p.ident.startswith("ref:") and is_reference_section(self.doc, p.section, self.ref_keywords):
            return self.md_reference(p)
        return HARD_BREAK.join(self.md_para_lines(p.inlines))

    def md_reference(self, p: Para) -> str:
        first = p.inlines[0]
        m = REF_KEY_RE.match(first.text)
        key = m.group(1)
        rest_text = first.text[m.end():].lstrip(" \t\n")
        rest = ([replace(first, text=rest_text)] if rest_text else []) + p.inlines[1:]
        slug = self.anchor.get(p.ident, "")
        head = f"**\\[{escape_md(key)}\\]** <a id=\"{slug}\"></a>"
        lines = self.md_para_lines(rest)
        return HARD_BREAK.join([head] + lines) if lines else head

    def md_list(self, items) -> str:
        out = []
        for it in items:
            lvl = it.list_info.level
            marker = "- " if it.list_info.kind == "bullet" else "1. "
            indent = "    " * lvl
            lines = self.md_para_lines(it.inlines) or [""]
            cont = HARD_BREAK + indent + " " * len(marker)
            out.append(indent + marker + cont.join(lines))
        return "\n".join(out)

    def md_code(self, c: Code) -> str:
        body = "\n".join(c.lines)
        runs = re.findall(r"`{3,}", body)
        fence = "`" * (max(len(r) for r in runs) + 1 if runs else 3)
        info = "json" if is_json(c.lines) else ""
        return f"{fence}{info}\n{body}\n{fence}"

    # ------------------------------------------------------------------ inline: html context
    def html_inlines(self, inlines) -> str:
        out = []
        for i in inlines:
            text = html.escape(i.text, quote=False).replace("\n", "<br>")
            if i.cls:
                text = f'<span class="{self.cls[i.cls]}">{text}</span>'
            elif i.mono:
                text = f"<code>{text}</code>"
            if i.link:
                href = self.href(i.link)
                if href:
                    text = f'<a href="{html.escape(href, quote=True)}">{text}</a>'
            if i.bold:
                text = f"<strong>{text}</strong>"
            if i.italic:
                text = f"<em>{text}</em>"
            out.append(text)
        return "".join(out)

    def html_list(self, items) -> str:
        out, stack, open_li = [], [], False
        for it in items:
            lvl, kind = it.list_info.level, ("ul" if it.list_info.kind == "bullet" else "ol")
            if lvl >= len(stack):
                while len(stack) < lvl + 1:
                    out.append(f"<{kind}>")
                    stack.append(kind)
                    open_li = False
            else:
                while len(stack) > lvl + 1:
                    if open_li:
                        out.append("</li>")
                    out.append(f"</{stack.pop()}>")
                    open_li = True
                if open_li:
                    out.append("</li>")
                    open_li = False
            out.append("<li>" + self.html_inlines(it.inlines))
            open_li = True
        while stack:
            if open_li:
                out.append("</li>")
            out.append(f"</{stack.pop()}>")
            open_li = True
        return "".join(out)

    def html_cell(self, cell, header: bool) -> str:
        parts, blocks, i = [], cell.blocks, 0
        while i < len(blocks):
            b = blocks[i]
            if isinstance(b, Para) and b.list_info:
                j = i
                while j < len(blocks) and isinstance(blocks[j], Para) and blocks[j].list_info:
                    j += 1
                parts.append(self.html_list(blocks[i:j]))
                i = j
                continue
            if isinstance(b, Para):
                if b.text.strip():
                    # header cells: no <strong> (STIX convention), and the header span wraps
                    # inline content only, never a block
                    inl = [replace(x, bold=False) for x in b.inlines] if header else b.inlines
                    inner = self.html_inlines(inl).strip()
                    parts.append(f'<span class="{self.cls["header"]}">{inner}</span>' if header else inner)
            elif isinstance(b, Code):
                lang = ' class="language-JSON"' if is_json(b.lines) else ""
                body = "\n".join(html.escape(l, quote=False) if l.strip() else "&nbsp;" for l in b.lines)
                parts.append(f"<pre><code{lang}>{body}</code></pre>")
            elif isinstance(b, Table):
                parts.append(self.html_table(b))
            i += 1
        return "<br><br>".join(parts)

    def html_table(self, t: Table) -> str:
        lines = [TABLE_OPEN]
        for ri, row in enumerate(t.rows):
            lines.append("  <tr>")
            for cell in row:
                tag = "th" if cell.header else "td"
                span = f' colspan="{cell.colspan}"' if cell.colspan > 1 else ""
                lines.append(f"    <{tag}{span}>{self.html_cell(cell, cell.header)}</{tag}>")
            lines.append("  </tr>")
        lines.append("</table>")
        # an HTML block ends at the first blank line: make sure there is none inside
        return "\n".join(l if l.strip() else "&nbsp;" for l in lines)

    # ------------------------------------------------------------------ blocks
    def heading(self, h: Heading) -> str:
        if h.number.startswith("Appendix"):
            num = h.number + ":"
        elif h.level == 1:
            num = h.number + "."
        else:
            num = h.number
        return f'{"#" * h.level} {num} {escape_md(h.title)} <a id="{h.slug}"></a>'

    def image(self, im: Image, caption: str) -> str:
        mapped = self.profile.images.get(im.src, im.src)
        if mapped is None:
            url = self.profile.front_matter.get("logo_url", "")
            return f"![OASIS Logo]({url})"
        alt = html.escape(caption or Path(mapped).stem, quote=True)
        return f'<img src="images/{mapped}" alt="{alt}">'

    def toc(self) -> str:
        lines = ["# Table of Contents", ""]
        for b in self.doc.blocks:
            if isinstance(b, Heading):
                indent = "  " * (b.level - 1)
                if b.number.startswith("Appendix"):
                    num = b.number + ":"
                elif b.level == 1:
                    num = b.number + "\\."  # "- 1. x" would nest an ordered list inside the bullet
                else:
                    num = b.number
                lines.append(f"{indent}- {num} [{escape_md(b.title)}](#{b.slug})")
        return "\n".join(lines)

    def body_blocks(self, blocks) -> list:
        """Render a block sequence (markdown context) into a list of chunks."""
        out, i, last_caption = [], 0, ""
        while i < len(blocks):
            b = blocks[i]
            if isinstance(b, Para) and b.list_info:
                j = i
                while j < len(blocks) and isinstance(blocks[j], Para) and (blocks[j].list_info or not blocks[j].text.strip()):
                    j += 1
                items = [x for x in blocks[i:j] if x.list_info]
                out.append(self.md_list(items))
                i = j
                continue
            if isinstance(b, Heading):
                out.append(self.heading(b))
            elif isinstance(b, Para):
                if b.text.strip():
                    out.append(self.md_para(b))
                    if norm(b.text).startswith("Figure"):
                        last_caption = norm(b.text)
            elif isinstance(b, Code):
                out.append(self.md_code(b))
            elif isinstance(b, Table):
                out.append(self.html_table(b))
            elif isinstance(b, Image):
                out.append(self.image(b, last_caption))
                last_caption = ""
            i += 1
        return out

    def front_matter(self, blocks) -> list:
        fm = self.profile.front_matter
        title_style = fm.get("title_style", "Title")
        subtitle_style = fm.get("subtitle_style", "Subtitle")
        label_styles = set(fm.get("label_styles", ["Title page info"]))
        notices_style = fm.get("notices_style", "Notices")
        out, i, subtitles, after_notices = [], 0, 0, False
        while i < len(blocks):
            b = blocks[i]
            if isinstance(b, Image):
                out.append(self.image(b, ""))
                out.append("---")
            elif isinstance(b, Para) and b.list_info:
                j = i
                while j < len(blocks) and isinstance(blocks[j], Para) and (blocks[j].list_info or not blocks[j].text.strip()):
                    j += 1
                out.append(self.md_list([x for x in blocks[i:j] if x.list_info]))
                i = j
                continue
            elif isinstance(b, Para) and b.text.strip():
                if b.style == title_style:
                    out.append("# " + self.md_inlines(b.inlines).strip())
                elif b.style == subtitle_style:
                    subtitles += 1
                    out.append(("## " if subtitles == 1 else "### ") + self.md_inlines(b.inlines).strip())
                elif b.style in label_styles:
                    out.append("#### " + self.md_inlines(b.inlines).strip())
                elif b.style == notices_style:
                    after_notices = True
                    out.append("---")
                    out.append("## " + self.md_inlines(b.inlines).strip())
                elif b.style == "Normal" and not after_notices:
                    # consecutive plain lines under a label (stage URLs, chairs, editors): hard breaks
                    j = i
                    while j < len(blocks) and isinstance(blocks[j], Para) and blocks[j].style == "Normal" \
                            and blocks[j].text.strip() and not blocks[j].list_info:
                        j += 1
                    out.append(HARD_BREAK.join(self.md_para(x) for x in blocks[i:j]))
                    i = j
                    continue
                else:
                    out.append(self.md_para(b))
            elif isinstance(b, (Code, Table)):
                out.extend(self.body_blocks([b]))
            i += 1
        out.append("---")
        return out

    def render(self) -> str:
        blocks = self.doc.blocks
        first = next((k for k, b in enumerate(blocks) if isinstance(b, Heading)), len(blocks))
        chunks = self.front_matter(blocks[:first])
        chunks.append(self.toc())
        chunks.extend(self.body_blocks(blocks[first:]))
        return "\n\n".join(chunks) + "\n"

    # ------------------------------------------------------------------ images
    def extract_images(self, docx_path, images_dir: Path) -> list:
        written = []
        with zipfile.ZipFile(docx_path) as z:
            for im in (b for b, _ in iter_blocks(self.doc.blocks) if isinstance(b, Image)):
                mapped = self.profile.images.get(im.src, im.src)
                if mapped is None:
                    continue
                member = f"word/media/{im.src}"
                if member not in z.namelist():
                    self.warnings.append(f"image {member} not found in package")
                    continue
                images_dir.mkdir(parents=True, exist_ok=True)
                target = images_dir / mapped
                target.write_bytes(z.read(member))
                written.append(target)
        return written
