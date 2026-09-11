# publish: Markdown specification to HTML and PDF

Renders `spec/<name>.md` to a standalone `spec/<name>.html` and a `spec/<name>.pdf`, the
way the STIX 2.1 repository publishes its specification: pandoc for the HTML, then the HTML
printed to PDF.

- HTML: pandoc, GitHub-flavoured Markdown reader (`-f gfm`), raw HTML passed through (the
  specification uses HTML tables, spans and anchors like STIX), images and stylesheet
  embedded, so the file is self-contained. Syntax highlighting is off by default (the
  `highlight` flag in the document config turns pandoc's highlighter on).
- PDF: WeasyPrint by default. It understands CSS paged media, so the PDF gets US Letter
  pages, running headers and footers ("Standards Track Work Product", copyright,
  "Page x of y" like the OASIS DOCX), and bookmarks for every heading.
  `--engine chrome` uses headless Chrome/Chromium instead, which is what the STIX 2.1 PDF
  was produced with (its metadata says HeadlessChrome / Skia); Chrome gives no running
  headers or footers.

Why not pandoc straight to PDF: pandoc's PDF route goes through LaTeX, which drops the raw
HTML tables. The HTML has to be the intermediate.

## Setup

```
tools/publish/setup.sh
```

creates `tools/publish/.venv` (WeasyPrint, pypdf, lxml) and downloads the pinned pandoc
release (version and sha256 in `publish.py`) into `tools/publish/.bin`. No system-wide
installation, no root. WeasyPrint needs the Pango/Cairo libraries that every desktop Linux
has; on macOS `brew install pango` first.

## Use

```
tools/publish/.venv/bin/python tools/publish/publish.py all taxii-v2.1
```

Steps individually: `html`, `pdf [--engine weasyprint|chrome]`, `check`.

`check` verifies the published files:

- HTML: every numbered heading of the Markdown is present, every internal link resolves,
  images are embedded; then, if `tools/docx2md` is set up, the fidelity harness compares the
  published HTML with the authoritative DOCX on all nine layers (text, headings, tables,
  links, emphasis, code, lists, images, hygiene). This is the same check the Markdown passed.
- PDF: page count, outline entries versus numbered headings, and the word-level similarity
  of the PDF text to the HTML text (page breaks lower it slightly; below 0.9 fails).

## Adding a document

Create `tools/publish/documents/<name>.json`:

| Field | Meaning |
|---|---|
| `title` | `<title>` of the HTML |
| `markdown`, `html`, `pdf` | paths relative to the repository root |
| `fidelity_profile` | optional path to the docx2md profile for the HTML-vs-DOCX check |
| `pdf_engine` | `weasyprint` (default) or `chrome` |
| `highlight` | `true` to enable pandoc syntax highlighting of fenced examples |
| `page.size`, `page.margin` | CSS page size and margins |
| `page.header_*`, `page.footer_*` | running header/footer texts; `{page}` and `{pages}` expand to counters |

Styling lives in `spec.css` (screen and print) and `print.css` (page-break rules); the page
box itself is generated from the document config.

## Reproducibility

Outputs depend on the pinned pandoc version, the WeasyPrint version in `requirements.txt`
and the fonts installed (Liberation Sans / Liberation Mono are the fallbacks for the Arial
and Consolas the DOCX uses). Commit the generated HTML and PDF next to the Markdown, as the
STIX repository does, so readers do not need the pipeline.
