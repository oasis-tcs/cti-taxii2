from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Profile:
    name: str
    source: str
    output: str = ""
    resolutions: str = ""
    heading_styles: dict = field(default_factory=dict)
    appendix_heading_styles: dict = field(default_factory=dict)
    appendix_number_format: str = "Appendix {letter}"
    skip_style_prefixes: list = field(default_factory=lambda: ["toc"])
    skip_paragraph_texts: list = field(default_factory=lambda: ["Table of Contents"])
    mono_fonts: list = field(default_factory=lambda: ["Consolas"])
    shading_classes: dict = field(default_factory=dict)
    label_colours: list = field(default_factory=list)
    bold_drops_mono: bool = False  # STIX convention: property names are bold, not bold code
    reference_section_keywords: list = field(default_factory=lambda: ["References"])
    md_span_classes: dict = field(default_factory=dict)
    md_class_names: dict = field(default_factory=dict)
    toc_heading_text: str = "Table of Contents"
    split_reference_keys: bool = False
    unwrap_tables: dict = field(default_factory=dict)
    drop_empty_tables: bool = False
    front_matter: dict = field(default_factory=dict)
    images: dict = field(default_factory=dict)
    root: Path = field(default_factory=Path)

    @classmethod
    def load(cls, path) -> "Profile":
        path = Path(path).resolve()
        data = json.loads(path.read_text(encoding="utf8"))
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in data.items() if k in known}
        data["shading_classes"] = {k.upper(): v for k, v in data.get("shading_classes", {}).items()}
        data["label_colours"] = [c.upper() for c in data.get("label_colours", [])]
        return cls(root=path.parent.parent, **data)

    def source_path(self) -> Path:
        return (self.root / self.source).resolve()

    def output_path(self) -> Path:
        return (self.root / self.output).resolve()

    def resolutions_path(self) -> Path | None:
        return (self.root / self.resolutions).resolve() if self.resolutions else None
