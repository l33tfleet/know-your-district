"""WO #37: keep the security/privacy note brief and discoverable."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_security_privacy_note_has_at_most_300_words() -> None:
    note = (ROOT / "docs/security-privacy.md").read_text(encoding="utf-8")
    word_count = len(note.split())
    assert 0 < word_count <= 300, f"Security/privacy note has {word_count} words"


def test_readme_links_security_privacy_and_data_licences() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "](docs/security-privacy.md)" in readme
    assert "](docs/data.md#data-licences)" in readme
