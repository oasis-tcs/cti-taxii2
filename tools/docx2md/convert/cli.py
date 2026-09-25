from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fidelity.compare import load_resolutions
from fidelity.docx_model import read_docx
from fidelity.profile import Profile

from .render import Renderer

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="convert", description="Render the DOCX model as STIX-style Markdown")
    ap.add_argument("--profile", default=str(ROOT / "profiles" / "taxii-v2.1.json"))
    ap.add_argument("--docx")
    ap.add_argument("--out", help="output .md (default: profile output path)")
    ap.add_argument("--images-dir", help="where to extract images (default: <out dir>/images)")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--preview", help="also write an HTML preview (GitHub renderer + the taxii* stylesheet) to this path")
    args = ap.parse_args(argv)

    profile = Profile.load(args.profile)
    docx_path = args.docx or profile.source_path()
    out = Path(args.out) if args.out else profile.output_path()
    res_path = profile.resolutions_path()
    resolutions = load_resolutions(res_path) if res_path and res_path.exists() else []

    doc = read_docx(docx_path, profile)
    r = Renderer(doc, profile, resolutions)
    text = r.render()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf8")
    if not args.no_images:
        images_dir = Path(args.images_dir) if args.images_dir else out.parent / "images"
        written = r.extract_images(docx_path, images_dir)
        for p in written:
            print(f"image: {p}")
    print(f"wrote {out} ({len(text)} chars, {text.count(chr(10))} lines)")
    if args.preview:
        from fidelity.md_model import render_html
        body = render_html(text)
        # image paths are relative to the .md; make them relative to the preview file
        rel = (out.parent / "images").resolve()
        body = body.replace('src="images/', f'src="{rel}/')
        Path(args.preview).write_text(PREVIEW_TEMPLATE.replace("{TITLE}", profile.name).replace("{BODY}", body), encoding="utf8")
        print(f"wrote preview {args.preview}")
    for wmsg in r.warnings:
        print("warning:", wmsg, file=sys.stderr)
    return 0


PREVIEW_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{TITLE} preview</title>
<style>
body{font-family:Arial,Helvetica,sans-serif;max-width:1000px;margin:2em auto;padding:0 1em;line-height:1.45}
code,pre{font-family:Consolas,Menlo,monospace;font-size:0.92em}
pre{background:#f6f8fa;padding:0.8em;overflow-x:auto}
table{border-collapse:collapse;margin:1em 0} th,td{vertical-align:top;text-align:left}
th{background:#073763}
.taxiitype{font-family:Consolas,Menlo,monospace;color:#C7254E;background:#F8F2F4}
.taxiiliteral{font-family:Consolas,Menlo,monospace;color:#094B88;background:#D9E3FB}
.taxiialt{font-family:Consolas,Menlo,monospace;color:black;background:#EFEFEF}
.taxiitr{color:#FFFFFF}
</style></head><body>
{BODY}
</body></html>
"""
