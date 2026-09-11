"""Layered comparison of two canonical documents (DOCX reference vs Markdown candidate)."""
from __future__ import annotations

import difflib
import json
from collections import Counter

from .model import (
    Document, cell_text, headings, images, links, list_items, mono_lines, spans, tables, units,
)

LAYERS = ["text", "headings", "tables", "links", "emphasis", "code", "lists", "images", "hygiene"]
EMPHASIS_ATTRS = ["bold", "italic", "mono", "type", "literal", "alt"]


def load_resolutions(path) -> list:
    if not path:
        return []
    with open(path, encoding="utf8") as fh:
        data = json.load(fh)
    return data.get("resolutions", data) if isinstance(data, dict) else data


def _seq_diff(a: list, b: list, a_ctx=None, b_ctx=None) -> list:
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        out.append({
            "op": op,
            "docx": [(a[k], a_ctx[k] if a_ctx else "") for k in range(i1, i2)],
            "md": [(b[k], b_ctx[k] if b_ctx else "") for k in range(j1, j2)],
        })
    return out, sm.ratio()


def apply_resolutions(link_list: list, resolutions: list) -> list:
    out = []
    for text, target, loc in link_list:
        for r in resolutions or []:
            if r.get("docx") == target and r.get("text", "*") in ("*", text):
                target = r["md"]
                if r.get("md_text") is not None:
                    text = r["md_text"]
                break
        out.append((text, target, loc))
    return out


def compare(dx: Document, md: Document, sections=None, resolutions=None, partial=False) -> dict:
    rep: dict = {"sections": sections or [], "partial": partial}

    # 1. text stream
    a, b = units(dx, sections), units(md, sections)
    diffs, ratio = _seq_diff([u for u, _ in a], [u for u, _ in b], [l for _, l in a], [l for _, l in b])
    rep["text"] = {"ok": not diffs, "docx": len(a), "md": len(b), "ratio": round(ratio, 4), "diffs": diffs}

    # 2. headings
    ha, hb = headings(dx, sections), headings(md, sections)
    diffs, _ = _seq_diff(ha, hb)
    rep["headings"] = {"ok": not diffs, "docx": len(ha), "md": len(hb), "diffs": diffs}

    # 3. tables
    ta, tb = tables(dx, sections), tables(md, sections)
    tdiffs = []
    for i, (x, y) in enumerate(zip(ta, tb)):
        if len(x.rows) != len(y.rows) or x.ncols() != y.ncols():
            tdiffs.append({"table": i, "issue": "shape", "docx": [len(x.rows), x.ncols()], "md": [len(y.rows), y.ncols()],
                           "first_cell": cell_text(x.rows[0][0])[:60] if x.rows and x.rows[0] else ""})
            continue
        for ri, (ra, rb) in enumerate(zip(x.rows, y.rows)):
            if [c.colspan for c in ra] != [c.colspan for c in rb]:
                tdiffs.append({"table": i, "row": ri, "issue": "colspan", "docx": [c.colspan for c in ra], "md": [c.colspan for c in rb]})
                continue
            for ci, (ca, cb) in enumerate(zip(ra, rb)):
                if cell_text(ca) != cell_text(cb):
                    tdiffs.append({"table": i, "cell": [ri, ci], "issue": "text", "docx": cell_text(ca)[:300], "md": cell_text(cb)[:300]})
    rep["tables"] = {"ok": len(ta) == len(tb) and not tdiffs, "docx": len(ta), "md": len(tb), "diffs": tdiffs}

    # 4. links
    la = apply_resolutions(links(dx, sections), resolutions)
    la = [x for x in la if x[1] is not None]  # resolutions may drop a link (md: null)
    lb = links(md, sections)
    if partial:
        lb = [(t, dx.slugs.get(tg[len("unresolved:"):], tg) if tg.startswith("unresolved:") else tg, loc) for t, tg, loc in lb]
    # GitHub autolinks bare URLs and e-mail addresses that are plain text in the DOCX. Such a
    # link (text == target) with no DOCX counterpart is representation, not content.
    budget = Counter((t, tg) for t, tg, _ in la)
    kept, autolinked = [], 0
    for t, tg, loc in lb:
        bare = tg.startswith("url:") and t and (t == tg[4:] or "mailto:" + t == tg[4:])
        if bare and budget[(t, tg)] <= 0:
            autolinked += 1
            continue
        budget[(t, tg)] -= 1
        kept.append((t, tg, loc))
    lb = kept
    diffs, _ = _seq_diff([(t, tg) for t, tg, _ in la], [(t, tg) for t, tg, _ in lb], [l for *_, l in la], [l for *_, l in lb])
    rep["links"] = {"ok": not diffs, "docx": len(la), "md": len(lb), "autolinked_ignored": autolinked, "diffs": diffs}

    # 5. emphasis and semantic spans
    em = {}
    for attr in EMPHASIS_ATTRS:
        ca, cb = spans(dx, attr, sections), spans(md, attr, sections)
        missing, extra = ca - cb, cb - ca
        em[attr] = {"ok": not missing and not extra, "docx": sum(ca.values()), "md": sum(cb.values()),
                    "missing": missing.most_common(60), "extra": extra.most_common(60)}
    rep["emphasis"] = {"ok": all(v["ok"] for v in em.values()), "attrs": em}

    # 6. code lines
    ca, cb = mono_lines(dx, sections), mono_lines(md, sections)
    missing, extra = ca - cb, cb - ca
    rep["code"] = {"ok": not missing and not extra, "docx": sum(ca.values()), "md": sum(cb.values()),
                   "missing": missing.most_common(60), "extra": extra.most_common(60)}

    # 7. lists
    li_a, li_b = list_items(dx, sections), list_items(md, sections)
    diffs, _ = _seq_diff(li_a, li_b)
    rep["lists"] = {"ok": not diffs, "docx": len(li_a), "md": len(li_b), "diffs": diffs}

    # 8. images
    ia, ib = images(dx, sections), images(md, sections)
    rep["images"] = {"ok": len(ia) == len(ib), "docx": len(ia), "md": len(ib),
                     "docx_srcs": [i.src for i in ia], "md_srcs": [i.src for i in ib]}

    # 9. markdown hygiene
    hyg = []
    for f in md.findings:
        if partial and f["kind"] == "unresolved-anchor" and f["target"][len("unresolved:"):] in dx.slugs:
            continue
        if partial and f["kind"] in ("heading-missing-from-toc", "toc-entry-without-heading"):
            continue
        hyg.append(f)
    rep["hygiene"] = {"ok": not hyg, "findings": hyg}

    rep["ok"] = all(rep[l]["ok"] for l in LAYERS)
    return rep


def _char_window(a: str, b: str, width: int = 70) -> tuple:
    """Excerpts of a and b around their first difference."""
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    start = max(0, i - width // 2)
    pre = "…" if start else ""
    wa, wb = a[start:i + width], b[start:i + width]
    return (pre + wa + ("…" if i + width < len(a) else ""), pre + wb + ("…" if i + width < len(b) else ""))


def _fmt_pairs(pairs, limit) -> list:
    out = []
    for i, (val, ctx) in enumerate(pairs):
        if i >= limit:
            out.append(f"      ... {len(pairs) - limit} more")
            break
        v = val if isinstance(val, str) else " | ".join(str(x) for x in val)
        out.append(f"      {v[:220]}" + (f"   [{ctx}]" if ctx else ""))
    return out


def format_report(rep: dict, max_items: int = 40) -> str:
    lines = []
    status = lambda ok: "OK  " if ok else "FAIL"
    scope = f" sections={','.join(rep['sections'])}" if rep.get("sections") else ""
    lines.append(f"fidelity verify{scope}{' (partial)' if rep.get('partial') else ''}: {'PASS' if rep['ok'] else 'FAIL'}")
    t = rep["text"]
    lines.append(f"[{status(t['ok'])}] text     units docx={t['docx']} md={t['md']} similarity={t['ratio']}")
    for d in t["diffs"][:max_items]:
        lines.append(f"    {d['op']}:")
        if d["op"] == "replace" and len(d["docx"]) == len(d["md"]):
            for (ua, la), (ub, _) in zip(d["docx"], d["md"]):
                wa, wb = _char_window(ua, ub)
                lines.append(f"      docx: {wa}   [{la}]")
                lines.append(f"      md:   {wb}")
            continue
        if d["docx"]:
            lines.append("      docx:")
            lines += _fmt_pairs(d["docx"], 6)
        if d["md"]:
            lines.append("      md:")
            lines += _fmt_pairs(d["md"], 6)
    if len(t["diffs"]) > max_items:
        lines.append(f"    ... {len(t['diffs']) - max_items} more text differences")
    for layer in ("headings", "lists"):
        r = rep[layer]
        lines.append(f"[{status(r['ok'])}] {layer:8s} docx={r['docx']} md={r['md']}")
        for d in r["diffs"][:max_items]:
            lines.append(f"    {d['op']}: docx={[x for x, _ in d['docx']][:5]} md={[x for x, _ in d['md']][:5]}")
    r = rep["tables"]
    lines.append(f"[{status(r['ok'])}] tables   docx={r['docx']} md={r['md']}")
    for d in r["diffs"][:max_items]:
        lines.append(f"    table {d['table']} {d.get('issue')}: {d.get('cell', d.get('row', ''))} docx={str(d['docx'])[:160]!r} md={str(d['md'])[:160]!r}")
    r = rep["links"]
    lines.append(f"[{status(r['ok'])}] links    docx={r['docx']} md={r['md']}"
                 + (f" (+{r['autolinked_ignored']} bare URLs autolinked by GitHub, ignored)" if r.get("autolinked_ignored") else ""))
    for d in r["diffs"][:max_items]:
        lines.append(f"    {d['op']}:")
        lines += ["      docx: " + " | ".join(str(x) for x in v) + f"   [{c}]" for v, c in d["docx"][:6]]
        lines += ["      md:   " + " | ".join(str(x) for x in v) + f"   [{c}]" for v, c in d["md"][:6]]
    r = rep["emphasis"]
    lines.append(f"[{status(r['ok'])}] emphasis " + " ".join(f"{k}={v['docx']}/{v['md']}" for k, v in r["attrs"].items()))
    for k, v in r["attrs"].items():
        if v["missing"]:
            lines.append(f"    {k} missing in md: " + "; ".join(f"{t!r}x{c}" if c > 1 else repr(t) for t, c in v["missing"][:max_items]))
        if v["extra"]:
            lines.append(f"    {k} extra in md:   " + "; ".join(f"{t!r}x{c}" if c > 1 else repr(t) for t, c in v["extra"][:max_items]))
    r = rep["code"]
    lines.append(f"[{status(r['ok'])}] code     lines docx={r['docx']} md={r['md']}")
    if r["missing"]:
        lines.append("    missing in md: " + "; ".join(repr(t) for t, _ in r["missing"][:max_items]))
    if r["extra"]:
        lines.append("    extra in md:   " + "; ".join(repr(t) for t, _ in r["extra"][:max_items]))
    r = rep["images"]
    lines.append(f"[{status(r['ok'])}] images   docx={r['docx']} md={r['md']}")
    r = rep["hygiene"]
    lines.append(f"[{status(r['ok'])}] hygiene  findings={len(r['findings'])}")
    for f in r["findings"][:max_items]:
        lines.append(f"    {f}")
    return "\n".join(lines)
