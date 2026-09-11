#!/usr/bin/env python3
"""publish.py: render a specification's Markdown to HTML (pandoc) and PDF (WeasyPrint or Chrome).

Usage (from the repository root, after tools/publish/setup.sh):
    tools/publish/.venv/bin/python tools/publish/publish.py all taxii-v2.1
    tools/publish/.venv/bin/python tools/publish/publish.py html taxii-v2.1
    tools/publish/.venv/bin/python tools/publish/publish.py pdf  taxii-v2.1 [--engine weasyprint|chrome]
    tools/publish/.venv/bin/python tools/publish/publish.py check taxii-v2.1
    tools/publish/.venv/bin/python tools/publish/publish.py setup        # fetch the pinned pandoc

Documents are described in tools/publish/documents/<name>.json.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BIN = HERE / ".bin"

PANDOC_VERSION = "3.11"
# sha256 of the official release archives; add an entry the first time a platform is used
PANDOC_SHA256 = {
    "linux-amd64": "37edb3bbcf722f921a009941bf5874e2e0c09263226c9b4a2d980788cb062ab6",
}


# ----------------------------------------------------------------------------- helpers
def load_document(name: str) -> dict:
    path = HERE / "documents" / f"{name}.json"
    if not path.exists():
        sys.exit(f"no document config {path}")
    doc = json.loads(path.read_text(encoding="utf8"))
    doc["_name"] = name
    return doc


def repo_path(p: str) -> Path:
    return (REPO / p).resolve()


def pandoc_archive() -> tuple[str, str]:
    """(platform key, archive file name) for the pinned pandoc release."""
    system, machine = platform.system(), platform.machine().lower()
    if system == "Linux":
        arch = "amd64" if machine in ("x86_64", "amd64") else "arm64" if machine in ("aarch64", "arm64") else None
        return f"linux-{arch}", f"pandoc-{PANDOC_VERSION}-linux-{arch}.tar.gz"
    if system == "Darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"macOS-{arch}", f"pandoc-{PANDOC_VERSION}-{arch}-macOS.zip"
    if system == "Windows":
        return "windows-x86_64", f"pandoc-{PANDOC_VERSION}-windows-x86_64.zip"
    sys.exit(f"unsupported platform {system}/{machine}: install pandoc {PANDOC_VERSION} manually")


def find_pandoc() -> Path:
    local = BIN / f"pandoc-{PANDOC_VERSION}" / "bin" / "pandoc"
    if local.exists():
        return local
    local_win = BIN / f"pandoc-{PANDOC_VERSION}" / "pandoc.exe"
    if local_win.exists():
        return local_win
    on_path = shutil.which("pandoc")
    if on_path:
        ver = subprocess.run([on_path, "--version"], capture_output=True, text=True).stdout.split("\n")[0]
        if PANDOC_VERSION not in ver:
            print(f"warning: {ver} on PATH, pipeline is pinned to pandoc {PANDOC_VERSION}; run 'publish.py setup' for the pinned build", file=sys.stderr)
        return Path(on_path)
    sys.exit("pandoc not found: run 'publish.py setup' (downloads the pinned release into tools/publish/.bin)")


def find_chrome() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


# ----------------------------------------------------------------------------- setup
def cmd_setup(args) -> int:
    key, archive = pandoc_archive()
    target_dir = BIN / f"pandoc-{PANDOC_VERSION}"
    if (target_dir / "bin" / "pandoc").exists() or (target_dir / "pandoc.exe").exists():
        print(f"pandoc {PANDOC_VERSION} already in {target_dir}")
        return 0
    url = f"https://github.com/jgm/pandoc/releases/download/{PANDOC_VERSION}/{archive}"
    print(f"downloading {url}")
    BIN.mkdir(exist_ok=True)
    data = urllib.request.urlopen(url, timeout=120).read()
    digest = hashlib.sha256(data).hexdigest()
    expected = PANDOC_SHA256.get(key)
    if expected and digest != expected:
        sys.exit(f"sha256 mismatch for {archive}: got {digest}, expected {expected}")
    if not expected:
        print(f"note: no pinned sha256 for {key}; downloaded archive sha256 is {digest} (add it to PANDOC_SHA256)")
    if archive.endswith(".tar.gz"):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            tf.extractall(BIN)
    else:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(BIN)
    print(f"pandoc {PANDOC_VERSION} installed in {target_dir}")
    return 0


# ----------------------------------------------------------------------------- html
def cmd_html(args) -> int:
    doc = load_document(args.document)
    md, html = repo_path(doc["markdown"]), repo_path(doc["html"])
    pandoc = find_pandoc()
    cmd = [
        str(pandoc), str(md), "-f", "gfm", "-t", "html5", "--standalone",
        "--embed-resources", "--syntax-highlighting=none", "--wrap=none",
        "--resource-path", str(md.parent),
        "--css", str(HERE / "spec.css"),
        "--metadata", f"pagetitle={doc['title']}",
        "--metadata", f"lang={doc.get('lang', 'en')}",
        "-o", str(html),
    ]
    if doc.get("highlight"):
        cmd.remove("--syntax-highlighting=none")
    print(" ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode
    if r.stderr.strip():
        print(r.stderr.strip(), file=sys.stderr)
    print(f"wrote {html} ({html.stat().st_size} bytes)")
    return 0


# ----------------------------------------------------------------------------- pdf
def page_css(doc: dict) -> str:
    page = doc.get("page", {})

    def content(template: str) -> str:
        if not template:
            return "none"
        parts = re.split(r"(\{page\}|\{pages\})", template)
        out = []
        for p in parts:
            if p == "{page}":
                out.append("counter(page)")
            elif p == "{pages}":
                out.append("counter(pages)")
            elif p:
                out.append('"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"')
        return " ".join(out)

    boxes = []
    for box, key in (("top-left", "header_left"), ("top-center", "header_center"), ("top-right", "header_right"),
                     ("bottom-left", "footer_left"), ("bottom-center", "footer_center"), ("bottom-right", "footer_right")):
        boxes.append(f"  @{box} {{ content: {content(page.get(key, ''))}; }}")
    size = page.get("size", "Letter")
    margin = page.get("margin", "22mm 20mm 22mm 20mm")
    return "@page {\n  size: %s;\n  margin: %s;\n%s\n}\n" % (size, margin, "\n".join(boxes))


def cmd_pdf(args) -> int:
    doc = load_document(args.document)
    html, pdf = repo_path(doc["html"]), repo_path(doc["pdf"])
    if not html.exists():
        sys.exit(f"{html} missing: run 'publish.py html {args.document}' first")
    engine = args.engine or doc.get("pdf_engine", "weasyprint")
    if engine == "weasyprint":
        try:
            import weasyprint
        except ImportError:
            sys.exit("weasyprint not importable: run tools/publish/setup.sh and use tools/publish/.venv/bin/python")
        generated = page_css(doc)
        (HERE / ".generated-page.css").write_text(generated, encoding="utf8")
        sheets = [weasyprint.CSS(str(HERE / "print.css")), weasyprint.CSS(string=generated)]
        weasyprint.HTML(filename=str(html)).write_pdf(str(pdf), stylesheets=sheets)
        print(f"wrote {pdf} ({pdf.stat().st_size} bytes) with WeasyPrint {weasyprint.__version__}")
        return 0
    if engine == "chrome":
        chrome = find_chrome()
        if not chrome:
            sys.exit("no Chrome/Chromium found on PATH")
        cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
               "--generate-pdf-document-outline", f"--print-to-pdf={pdf}", html.as_uri()]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not pdf.exists():
            print(r.stderr, file=sys.stderr)
            return r.returncode or 1
        print(f"wrote {pdf} ({pdf.stat().st_size} bytes) with {chrome} (STIX 2.1 used this engine; no page headers/footers)")
        return 0
    sys.exit(f"unknown engine {engine}")


# ----------------------------------------------------------------------------- check
def _norm_words(text: str) -> list:
    return re.sub(r"\s+", " ", text).strip().split(" ")


def cmd_check(args) -> int:
    doc = load_document(args.document)
    md, html, pdf = repo_path(doc["markdown"]), repo_path(doc["html"]), repo_path(doc["pdf"])
    ok = True
    from lxml import html as lhtml

    md_text = md.read_text(encoding="utf8")
    md_headings = [l for l in md_text.splitlines() if re.match(r"^#{1,6} (\d+\.|\d+(\.\d+)+|Appendix [A-Z]:)\s", l)]

    # --- HTML
    if html.exists():
        page = lhtml.fromstring(html.read_bytes())
        heads = [h for h in page.iter("h1", "h2", "h3", "h4", "h5", "h6")
                 if re.match(r"^(\d+\.|\d+(\.\d+)+|Appendix [A-Z]:)\s", h.text_content().strip())]
        ids = {el.get("id") for el in page.iter() if el.get("id")}
        hrefs = [a.get("href") for a in page.iter("a") if (a.get("href") or "").startswith("#")]
        broken = sorted({h for h in hrefs if h[1:] not in ids})
        ext_imgs = [im.get("src") for im in page.iter("img") if not (im.get("src") or "").startswith("data:")]
        tables = len(list(page.iter("table")))
        print(f"html: numbered headings {len(heads)} (markdown {len(md_headings)}), tables {tables}, "
              f"images {len(list(page.iter('img')))} (not embedded: {len(ext_imgs)}), internal links {len(hrefs)}, broken {len(broken)}")
        if len(heads) != len(md_headings) or broken:
            ok = False
            for b in broken[:20]:
                print("  broken anchor:", b)
        # strongest check: the fidelity harness against the DOCX, if the docx2md tool is set up
        fid_py = REPO / "tools" / "docx2md" / ".venv" / "bin" / "python"
        profile = doc.get("fidelity_profile")
        if fid_py.exists() and profile:
            r = subprocess.run([str(fid_py), "-m", "fidelity", "--profile", str(REPO / profile), "verify", str(html), "--html"],
                               cwd=str(REPO / "tools" / "docx2md"), capture_output=True, text=True)
            summary = [l for l in r.stdout.splitlines() if l.startswith(("fidelity", "[OK", "[FAIL"))]
            print("fidelity verify (HTML vs DOCX):")
            for l in summary:
                print("  " + l)
            if r.returncode != 0:
                ok = False
                print(r.stdout[-3000:])
    else:
        print(f"html: {html} missing")
        ok = False

    # --- PDF
    if pdf.exists():
        try:
            import pypdf
            reader = pypdf.PdfReader(str(pdf))
            outline = []

            def walk(items):
                for it in items:
                    if isinstance(it, list):
                        walk(it)
                    else:
                        outline.append(it.title)

            walk(reader.outline)
            numbered = [t for t in outline if re.match(r"^(\d+\.|\d+(\.\d+)+|Appendix [A-Z]:)\s", t or "")]
            print(f"pdf: pages {len(reader.pages)}, outline entries {len(outline)} (numbered {len(numbered)}, markdown {len(md_headings)})")
            if len(numbered) != len(md_headings):
                print("  warning: PDF outline does not list every numbered heading")
            if shutil.which("pdftotext"):
                pdf_text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout
            else:
                pdf_text = "\n".join(p.extract_text() or "" for p in reader.pages)
            page = doc.get("page", {})
            for k, v in page.items():
                if k.startswith(("header_", "footer_")) and v:
                    pdf_text = pdf_text.replace(v.replace("{page}", "").replace("{pages}", ""), " ")
            pdf_text = re.sub(r"Page \d+ of \d+", " ", pdf_text)
            ref_text = lhtml.fromstring(html.read_bytes()).body.text_content() if html.exists() else md_text
            ratio = difflib.SequenceMatcher(None, _norm_words(ref_text), _norm_words(pdf_text), autojunk=False).ratio()
            print(f"pdf: text similarity to HTML {ratio:.4f} (word level; page breaks and hyphenation lower it slightly)")
            if ratio < 0.9:
                ok = False
        except ImportError:
            print("pdf: pypdf not installed, skipping PDF checks")
    else:
        print(f"pdf: {pdf} missing")
    print("check:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_all(args) -> int:
    for fn in (cmd_html, cmd_pdf, cmd_check):
        rc = fn(args)
        if rc:
            return rc
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="publish", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("setup", help="download the pinned pandoc release into tools/publish/.bin")
    p.set_defaults(fn=cmd_setup)
    for name, fn, help_ in (("html", cmd_html, "Markdown -> standalone HTML with pandoc"),
                            ("pdf", cmd_pdf, "HTML -> PDF"),
                            ("check", cmd_check, "sanity checks on the published files"),
                            ("all", cmd_all, "html, pdf, check")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("document", help="name of tools/publish/documents/<name>.json")
        p.add_argument("--engine", choices=["weasyprint", "chrome"], help="PDF engine (default from the document config)")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
