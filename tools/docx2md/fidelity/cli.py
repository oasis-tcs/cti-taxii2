from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .compare import compare, format_report, load_resolutions
from .model import Code, Heading, Image, Para, Table, in_sections, iter_blocks
from .profile import Profile

ROOT = Path(__file__).resolve().parent.parent


def _profile(args) -> Profile:
    return Profile.load(args.profile)


def _docx(args, profile: Profile):
    from .docx_model import read_docx
    return read_docx(args.docx or profile.source_path(), profile)


def cmd_inventory(args) -> int:
    from .inventory import inventory
    profile = _profile(args)
    print(inventory(args.docx or profile.source_path()))
    return 0


def cmd_audit(args) -> int:
    profile = _profile(args)
    doc = _docx(args, profile)
    lines = [f"# Source audit: {profile.name}", "", f"Source: `{doc.meta['source']}`", ""]
    heads = [b for b, _ in iter_blocks(doc.blocks) if isinstance(b, Heading)]
    from .model import headings, images, links, list_items, mono_lines, tables
    lines += ["## Counts", "",
              f"- headings: {len(heads)} " + str(dict(sorted(__import__('collections').Counter((h.level, h.number.startswith('Appendix')) for h in heads).items()))),
              f"- tables: {len(tables(doc))}",
              f"- images: {len(images(doc))}",
              f"- links: {len(links(doc))} (external {sum(1 for _, t, _ in links(doc) if t.startswith('url:'))})",
              f"- list items: {len(list_items(doc))}",
              f"- monospace lines: {sum(mono_lines(doc).values())}",
              f"- reference entries: {len(doc.meta.get('reference_keys', {}))}",
              f"- non-ASCII characters: {doc.meta.get('non_ascii')}",
              ""]
    lines += ["## Heading numbers vs Word's cached table of contents", ""]
    toc = doc.meta["toc_headings"]
    computed = [(h.number, h.title) for h in heads]
    if toc == computed:
        lines.append(f"- OK: {len(toc)} entries match the computed outline numbers.")
    else:
        lines.append(f"- MISMATCH: toc={len(toc)} computed={len(computed)}")
        for i, (a, b) in enumerate(zip(toc, computed)):
            if a != b:
                lines.append(f"  - {i}: toc={a} computed={b}")
    lines.append("")
    lines += ["## Findings", ""]
    by_kind = {}
    for f in doc.findings:
        by_kind.setdefault(f["kind"], []).append(f)
    if not by_kind:
        lines.append("- none")
    for kind, items in sorted(by_kind.items()):
        lines.append(f"### {kind} ({len(items)})")
        lines.append("")
        for f in items:
            lines.append("- " + ", ".join(f"{k}={v!r}" for k, v in f.items() if k != "kind"))
        lines.append("")
    text = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(text, encoding="utf8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def _dump_blocks(blocks, sections, indent=0):
    pad = "  " * indent
    for b in blocks:
        if not in_sections(b.section, sections):
            continue
        tag = f"{pad}[§{b.section or 'front'}]"
        if isinstance(b, Heading):
            print(f"{tag} H{b.level} {b.number} {b.title}  ids={b.anchor_ids} slug={b.slug}")
        elif isinstance(b, Para):
            li = f" list={b.list_info.kind}/{b.list_info.level}" if b.list_info else ""
            mono = " mono" if b.mono else ""
            hdr = " header" if b.in_header else ""
            print(f"{tag} P{li}{mono}{hdr} {b.text[:160]!r}")
            for i in b.inlines:
                flags = "".join(x for x, on in (("B", i.bold), ("I", i.italic), ("M", i.mono)) if on)
                if flags or i.cls or i.link:
                    print(f"{pad}     - [{flags}{('#' + i.cls) if i.cls else ''}{(' -> ' + i.link) if i.link else ''}] {i.text[:80]!r}")
        elif isinstance(b, Code):
            print(f"{tag} CODE {len(b.lines)} lines")
            for l in b.lines[:8]:
                print(f"{pad}     | {l}")
            if len(b.lines) > 8:
                print(f"{pad}     | ... {len(b.lines) - 8} more")
        elif isinstance(b, Table):
            print(f"{tag} TABLE {len(b.rows)}x{b.ncols()}")
            for ri, row in enumerate(b.rows):
                for ci, cell in enumerate(row):
                    print(f"{pad}   cell r{ri}c{ci} span={cell.colspan}{' header' if cell.header else ''}")
                    _dump_blocks(cell.blocks, None, indent + 3)
        elif isinstance(b, Image):
            print(f"{tag} IMAGE {b.src} alt={b.alt!r}")


def cmd_dump(args) -> int:
    profile = _profile(args)
    if args.md:
        from .md_model import read_md
        doc = read_md(args.md, profile, is_html=args.md.lower().endswith((".html", ".htm")))
    else:
        doc = _docx(args, profile)
    if args.json:
        from dataclasses import asdict
        print(json.dumps([asdict(b) for b in doc.blocks if in_sections(b.section, args.section)], ensure_ascii=False, indent=1))
    else:
        _dump_blocks(doc.blocks, args.section)
        if doc.findings:
            print(f"\n{len(doc.findings)} findings:")
            for f in doc.findings:
                print(f"  {f}")
    return 0


def cmd_verify(args) -> int:
    profile = _profile(args)
    from .md_model import read_md
    dx = _docx(args, profile)
    is_html = args.html or args.md.lower().endswith((".html", ".htm"))
    md = read_md(args.md, profile, is_html=is_html)
    res_path = args.resolutions or profile.resolutions_path()
    resolutions = load_resolutions(res_path) if res_path and Path(res_path).exists() else []
    rep = compare(dx, md, sections=args.section, resolutions=resolutions, partial=args.partial)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    else:
        print(format_report(rep, max_items=args.max))
    return 0 if rep["ok"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fidelity", description="DOCX vs Markdown fidelity harness")
    ap.add_argument("--profile", default=str(ROOT / "profiles" / "taxii-v2.1.json"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inventory", help="discovery report of a DOCX (for writing a profile)")
    p.add_argument("--docx")
    p.set_defaults(fn=cmd_inventory)

    p = sub.add_parser("audit", help="extract the DOCX model and report source anomalies")
    p.add_argument("--docx")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_audit)

    p = sub.add_parser("dump", help="print the canonical model of the DOCX or of a Markdown file")
    p.add_argument("--docx")
    p.add_argument("--md")
    p.add_argument("--section", action="append")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_dump)

    p = sub.add_parser("verify", help="compare a Markdown file (or published HTML) with the DOCX")
    p.add_argument("md", help="Markdown file, or an .html file (published rendering)")
    p.add_argument("--html", action="store_true", help="treat the input as HTML instead of Markdown")
    p.add_argument("--docx")
    p.add_argument("--section", action="append")
    p.add_argument("--partial", action="store_true", help="tolerate links to sections not yet converted")
    p.add_argument("--resolutions")
    p.add_argument("--json", action="store_true")
    p.add_argument("--max", type=int, default=40)
    p.set_defaults(fn=cmd_verify)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
