"""Discovery report for a DOCX: what a profile author needs to know."""
from __future__ import annotations

import re
import zipfile
from collections import Counter


def _count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


def inventory(path) -> str:
    z = zipfile.ZipFile(path)
    names = z.namelist()
    doc = z.read("word/document.xml").decode("utf8")
    styles = z.read("word/styles.xml").decode("utf8") if "word/styles.xml" in names else ""
    numbering = z.read("word/numbering.xml").decode("utf8") if "word/numbering.xml" in names else ""
    out = [f"# Inventory of {path}", ""]

    out.append("## Package parts")
    out += [f"- {n}" for n in names if n.startswith("word/") and not n.startswith("word/theme")]
    out.append("")

    out.append("## Element counts (document.xml)")
    for label, pat in [
        ("paragraphs", r"<w:p[ >]"), ("tables", r"<w:tbl[ >]"), ("table rows", r"<w:tr[ >]"), ("table cells", r"<w:tc[ >]"),
        ("gridSpan (horizontal merges)", r"<w:gridSpan"), ("vMerge (vertical merges)", r"<w:vMerge"),
        ("drawings (images)", r"<w:drawing"), ("hyperlinks external", r"<w:hyperlink [^>]*r:id="),
        ("hyperlinks internal", r"<w:hyperlink [^>]*w:anchor="), ("bookmarks", r"<w:bookmarkStart"),
        ("footnote refs", r"<w:footnoteReference"), ("endnote refs", r"<w:endnoteReference"),
        ("comments", r"<w:commentRangeStart"), ("tracked insertions", r"<w:ins "), ("tracked deletions", r"<w:del "),
        ("fields (instrText)", r"<w:instrText"), ("content controls", r"<w:sdt[ >]"), ("equations", r"<m:oMath"),
        ("list paragraphs (numPr)", r"<w:numPr>"), ("soft line breaks", r"<w:br"), ("tabs", r"<w:tab/>"),
    ]:
        out.append(f"- {label}: {_count(pat, doc)}")
    out.append("")

    out.append("## Field codes")
    for k, c in Counter(re.findall(r"<w:instrText[^>]*>\s*([A-Z]+)", doc)).most_common():
        out.append(f"- {k}: {c}")
    out.append("")

    out.append("## Paragraph styles used (styleId: count)")
    for k, c in Counter(re.findall(r'<w:pStyle w:val="([^"]+)"', doc)).most_common():
        out.append(f"- {k}: {c}")
    out.append("")

    out.append("## Styles with outline numbering (styleId -> numId) and style names")
    for m in re.finditer(r'<w:style [^>]*w:styleId="([^"]+)"[^>]*>(.*?)</w:style>', styles, re.S):
        sid, body = m.group(1), m.group(2)
        nm = re.search(r'<w:name w:val="([^"]+)"', body)
        num = re.search(r'<w:numId w:val="(\d+)"', body)
        if num or re.match(r"Heading\d|.*Heading|Title|TOC", sid):
            out.append(f"- {sid} ({nm.group(1) if nm else '?'}) numId={num.group(1) if num else '-'}")
    out.append("")

    out.append("## List number formats in numbering.xml")
    for k, c in Counter(re.findall(r'<w:numFmt w:val="([^"]+)"', numbering)).most_common():
        out.append(f"- {k}: {c}")
    out.append("")

    out.append("## Run fonts (explicit rFonts ascii)")
    for k, c in Counter(re.findall(r'<w:rFonts [^>]*w:ascii="([^"]+)"', doc)).most_common(10):
        out.append(f"- {k}: {c}")
    out.append("")

    out.append("## Run shading fills (rPr)")
    for k, c in Counter(re.findall(r"<w:rPr>(?:<[^>]*>)*?<w:shd [^>]*w:fill=\"([^\"]+)\"", doc)).most_common():
        out.append(f"- {k}: {c}")
    out.append("")

    out.append("## Paragraph shading fills (pPr)")
    for k, c in Counter(re.findall(r"<w:pPr>(?:<[^>]*>)*?<w:shd [^>]*w:fill=\"([^\"]+)\"", doc)).most_common():
        out.append(f"- {k}: {c}")
    out.append("")

    out.append("## Cell shading fills (tcPr)")
    for k, c in Counter(re.findall(r"<w:tcPr>(?:<[^>]*>)*?<w:shd [^>]*w:fill=\"([^\"]+)\"", doc)).most_common():
        out.append(f"- {k}: {c}")
    out.append("")

    out.append("## Run colours")
    for k, c in Counter(re.findall(r'<w:color w:val="([0-9A-Fa-f]{6})"', doc)).most_common(15):
        out.append(f"- {k}: {c}")
    out.append("")

    out.append("## Run formatting")
    out.append(f"- bold runs: {_count(r'<w:b/>|<w:b w:val=\"(?:1|true|on)\"', doc)}")
    out.append(f"- italic runs: {_count(r'<w:i/>|<w:i w:val=\"(?:1|true|on)\"', doc)}")
    out.append(f"- underline runs: {_count(r'<w:u ', doc)}")
    out.append(f"- strike runs: {_count(r'<w:strike', doc)}")
    out.append(f"- hidden runs (vanish): {_count(r'<w:vanish', doc)}")
    out.append("")

    out.append("## External link targets (top 15)")
    rels = z.read("word/_rels/document.xml.rels").decode("utf8")
    for k, c in Counter(re.findall(r'Target="([^"]+)"[^>]*TargetMode="External"', rels)).most_common(15):
        out.append(f"- {k}: {c}")
    out.append("")

    out.append("## Headers / footers text")
    for n in names:
        if re.match(r"word/(header|footer)\d*\.xml", n):
            txt = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", z.read(n).decode("utf8")))
            out.append(f"- {n}: {txt[:160]!r}")
    return "\n".join(out)
