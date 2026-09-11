from pathlib import Path

import pytest

from fidelity.docx_model import read_docx
from fidelity.md_model import read_md
from fidelity.profile import Profile
from fidelity.compare import load_resolutions

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def profile():
    return Profile.load(ROOT / "profiles" / "taxii-v2.1.json")


@pytest.fixture(scope="session")
def docx_doc(profile):
    return read_docx(profile.source_path(), profile)


@pytest.fixture(scope="session")
def raw_profile(profile):
    """The profile without the representation rules (unwrap/drop/split): the DOCX as it is."""
    from dataclasses import replace
    return replace(profile, unwrap_tables={}, drop_empty_tables=False, split_reference_keys=False)


@pytest.fixture(scope="session")
def raw_doc(raw_profile):
    return read_docx(raw_profile.source_path(), raw_profile)


@pytest.fixture(scope="session")
def resolutions(profile):
    return load_resolutions(profile.resolutions_path())


@pytest.fixture(scope="session")
def fixture_text():
    return (ROOT / "tests" / "fixtures" / "taxii-1.1-1.2.md").read_text(encoding="utf8")


@pytest.fixture(scope="session")
def fixture_doc(fixture_text, profile):
    return read_md(fixture_text, profile, is_text=True)
