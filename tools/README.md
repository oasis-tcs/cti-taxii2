# Tools shipped with the TAXII specification

| Directory | Purpose |
|---|---|
| `docx2md/` | Convert an OASIS DOCX to STIX-style Markdown and prove content fidelity (inventory, audit, convert, verify). Used once per DOCX edition; the harness stays useful to re-verify the Markdown after edits. |
| `publish/` | Render `spec/*.md` to standalone HTML (pandoc) and PDF (WeasyPrint or Chrome), with checks on the results. Used for every release of the Markdown. |

Each tool is self-contained (own `README.md`, `requirements.txt`, virtual environment) and
document-agnostic: the TAXII 2.1 specifics live in `docx2md/profiles/taxii-v2.1.json`,
`docx2md/resolutions/taxii-v2.1.json` and `publish/documents/taxii-v2.1.json`.

Typical flow for a new edition:

1. `docx2md`: freeze the DOCX, `inventory`, write the profile, `audit`, `convert`, `verify`.
2. Review the Markdown on GitHub (or `convert --preview`).
3. `publish`: `all <document>` and commit `spec/<name>.md`, `.html`, `.pdf`, `images/`.
