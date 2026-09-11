# docx2md: OASIS DOCX to Markdown with fidelity checking

This toolkit converts an OASIS specification from its authoritative DOCX into the hybrid
Markdown style used by `oasis-tcs/cti-stix2/spec/stix-v2.1.md`, and, more importantly,
proves that no content was lost or altered on the way.

It was built for TAXII 2.1 but is document-agnostic: everything specific to one document
lives in a profile (`profiles/<name>.json`) and a resolutions file
(`resolutions/<name>.json`).

## Layout

```
tools/docx2md/
  README.md                this file
  requirements.txt         python-docx, lxml, cmarkgfm, pytest
  profiles/<name>.json     document profile: style ids, shading/colour semantics, paths
  resolutions/<name>.json  accepted deviations from the source, each with a reason
  source/<name>.docx       frozen copy of the authoritative DOCX + SHA256SUMS
  fidelity/                content model, DOCX reader, Markdown reader, comparison, CLI
  convert/                 renderer: canonical model -> STIX-style Markdown (+ image extraction)
  tests/                   self-tests of the harness (run before trusting any result)
  reports/                 generated reports: <name>-inventory.md (discovery), <name>-source-audit.md
```

## Setup

```
cd tools/docx2md
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

The Markdown side is rendered with `cmarkgfm`, the same cmark-gfm engine GitHub uses, with
raw HTML enabled, so what the harness sees is what GitHub renders.

## Commands

All commands take `--profile profiles/<name>.json` (default: `profiles/taxii-v2.1.json`).

| Command | Purpose |
|---|---|
| `python -m fidelity inventory` | Discovery: styles, fonts, shading fills, colours, list formats, tables, images, links, fields, bookmarks of the DOCX. Use it to write the profile for a new document. |
| `python -m fidelity audit [--out reports/x.md]` | Extract the DOCX model and report source anomalies: dangling anchors, mis-targeted reference links, duplicate reference keys, duplicate headings, TOC mismatches, odd link spans. |
| `python -m fidelity dump --docx` / `--md FILE` `[--section N ...]` | Print the canonical model of either side, for eyeballing what the comparison compares. |
| `python -m fidelity verify spec.md [--section N ...] [--partial] [--json]` | Compare the Markdown with the DOCX, layer by layer. Exit code 1 on any difference not covered by the resolutions file. |
| `python -m fidelity verify spec.html --html` | Same comparison for a published HTML rendering (for example pandoc's output from `tools/publish`), so the publishing step is verified too. |
| `python -m convert [--out FILE] [--no-images] [--preview FILE.html]` | Render the DOCX model as STIX-style Markdown (to the profile's `output`), extract the images next to it, apply the resolutions file to links. Deterministic: same input, same output. `--preview` also writes a local HTML rendering (GitHub's engine plus the `taxii*` stylesheet) for the reading pass. |

The normal loop is `convert`, then `verify`, then fix the converter or add a resolution, never
edit the generated Markdown by hand.

`--section` restricts both sides to one or more numbered sections (`1.2`, `3`, `Appendix A`),
so a document can be converted and checked incrementally. `--partial` additionally lets
internal links that point at not-yet-written sections resolve through the expected anchor
slugs instead of failing hygiene.

## What is compared

Both sides are reduced to the same canonical model (headings with numbers, paragraphs with
inline attributes, lists, tables with spans, code lines, images, links with resolved targets).
Layers, all of which must pass:

1. Text stream: every visible text unit in order, whitespace-normalised, diffed with locations.
2. Headings: (level, number, title).
3. Tables: count, shape, colspans, per-cell text.
4. Links: ordered (text, target) pairs; internal targets are compared as identities
   (`heading:1.6`, `ref:RFC2119`) so anchor naming is free.
5. Emphasis: bold, italic, monospace, and the semantic span classes (type, literal, alt).
6. Code: monospace lines with exact leading whitespace.
7. Lists: (bullet/number, level, text) sequence.
8. Images: count.
9. Markdown hygiene: anchors resolve, ids unique, TOC matches headings.

Deliberate deviations (for example a link whose Word bookmark is broken in the source) are
declared in the resolutions file:

```json
{"text": "4", "docx": "dangling:_rctaybmqy5s0", "md": "heading:4", "why": "bookmark missing in source; text names section 4"}
```

`text` may be `*` to match any link text. Only declared deviations are accepted.

## Conventions the Markdown must follow for the harness to work

These are the STIX 2.1 conventions; the harness parses them.

- Numbered headings: `# 1. Title`, `## 1.1 Title`, `# Appendix A: Title`. A level-1 number
  needs the trailing dot (that is how `10 June 2021` is told apart from a numbered heading).
- Each numbered heading and each reference entry carries an explicit anchor:
  `## 1.1 Title <a id="slug"></a>`, `**[RFC2119]** <a id="rfc2119"></a>`.
- Reference entries start with the bracketed key and sit under a heading whose title contains
  "References".
- The table of contents is a list under a heading titled `Table of Contents`; it is skipped in
  the text comparison and checked against the headings instead.
- Table header rows use `<th>` (or pipe-table syntax). Header cells are excluded from the
  emphasis comparison because Word marks them bold and white.
- Semantic spans: `<span class="stixtype">`, `<span class="stixliteral">`, `<span class="stixalt">`
  (configurable in the profile under `md_span_classes`).

## Reproducing the process for another OASIS document

1. Freeze the source: copy the authoritative DOCX to `source/`, record its SHA-256 in
   `source/SHA256SUMS`.
2. Discover: `python -m fidelity inventory --docx source/<file>.docx`. Note which style ids are
   headings (and whether they are auto-numbered), which fonts mean code, which shading fills
   and colours carry meaning (the document's own "Document Conventions" section says), how
   table header rows are marked, and where examples live (body vs. table cells).
3. Write `profiles/<name>.json` (copy `profiles/taxii-v2.1.json` and adjust). Fields:
   - `source`, `output`: paths relative to `tools/docx2md/`.
   - `heading_styles`: style id to outline level; `appendix_heading_styles` and
     `appendix_number_format` for lettered appendices.
   - `skip_style_prefixes` (Word TOC styles) and `skip_paragraph_texts` ("Table of Contents").
   - `mono_fonts`, `shading_classes` (fill to type/literal/alt), `label_colours` (run colours
     that act as bold labels).
   - `reference_section_keywords`: how to recognise the reference lists.
   - `md_span_classes`: HTML span classes in the Markdown and their meaning.
4. Audit: `python -m fidelity audit --out reports/<name>-source-audit.md`. Read it. Every
   anomaly needs a decision: resolve it in `resolutions/<name>.json` with a reason, and file it
   as an errata candidate if it is a genuine source error.
5. Validate the harness on this document before trusting it: adapt `tests/` (the oracle counts
   and the fixture section) and run `pytest`. The mutation tests must still fail for the
   right reasons.
6. Convert: `python -m convert`. Review section by section:
   `python -m fidelity verify spec/<name>.md --section N`. Fix the converter or the profile,
   not the Markdown by hand, unless the deviation is deliberate (then it goes in resolutions).
   Representation rules that change structure (endpoint tables unwrapped, reference keys on
   their own line, empty picture-frame tables unwrapped) are applied to the reference model by
   the profile (`unwrap_tables`, `split_reference_keys`, `drop_empty_tables`) so that the
   harness still compares like with like; `tests/test_docx_model.py::test_representation_rules`
   proves those rules move content without losing any.
7. When complete: `python -m fidelity verify spec/<name>.md` (no `--section`, no `--partial`)
   must be clean, then a human reading pass on the rendered GitHub page.
8. Keep the DOCX, the profile, the resolutions and the audit report in the repository so the
   result can be re-derived and re-verified later (for example after errata).

## Known limitations

- Word content that is not text (footnotes, comments, tracked changes, equations, content
  controls) is not modelled. `inventory` reports whether the document has any.
- Vertically merged cells (`vMerge`) are not modelled; TAXII has none. Add support before
  using the toolkit on a document that has them.
- List numbering values are not compared, only list kind and nesting depth.
