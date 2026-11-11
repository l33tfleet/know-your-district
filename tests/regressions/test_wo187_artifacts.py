"""WO187: brief, SNAP and artifact checks, with the plain wording.

Each test here is a copy of a superseded test, changed only where it pinned old
words or the digests of artifacts whose method notes now end clauses as sentences.
Digest copies also prove that putting the old semicolons back restores the old
bytes, so no value, MOE, CV, reliability, citation or row changed.
"""

import hashlib
from pathlib import Path

from etl.build import check
from etl.census import CensusClient
from etl.facts import METHOD_SEPARATOR
from tests.regressions.test_wo118_facts_build import recorded_client as recorded_client
from tests.regressions.test_wo139_manifest_build import DIGEST, manifests
from tests.regressions.test_wo147_coverage import OUTPUT

__all__ = ["DIGEST", "OUTPUT", "manifests", "recorded_client"]


def old_separators(tsv: bytes) -> bytes:
    """The TSV with each stored method's sentence boundaries put back as semicolons.

    Hashing this against the digest pinned before #187 proves that only the method
    separators changed: every other byte, field and row is as it was.
    """
    lines = tsv.decode("utf-8").split("\n")
    column = lines[0].split("\t").index("method")
    out = [lines[0]]
    for line in lines[1:]:
        if not line:
            out.append(line)
            continue
        fields = line.split("\t")
        fields[column] = fields[column].replace(METHOD_SEPARATOR, "; ")
        out.append("\t".join(fields))
    return "\n".join(out).encode("utf-8")


# Replaces test_wo147_coverage.py::test_published_bytes_match_the_operator_refresh (wording only, #187).
def test_published_bytes_match_the_operator_refresh() -> None:
    expected = {
        "facts.db": "fdc7d8408444f8e51dd4ceb92ab4f76fe5875091f74caf471ed1d6077dbf1959",
        "facts.tsv": "edd63ab8885477c3a386c31139b435e9275e4f52171a5b5d04c184e25dd8e68b",
        "facts.sha256": "d69306ba0ffa632d1aba37f5a7305bac8ef0e3e3d33cf9a750c46c49c3c9a809",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((OUTPUT / name).read_bytes()).hexdigest() == digest
    # Only the method separators changed: the pre-#187 bytes come back.
    assert hashlib.sha256(old_separators((OUTPUT / "facts.tsv").read_bytes())).hexdigest() == (
        "665fc0eff021859a41ff7f7d63cffbea5562f5ecf021f9a24f42a7b7389fda02"
    )
    # Also validates every row, exact schema, canonical TSV, and the digest manifest.
    assert check(OUTPUT)


# Replaces test_wo139_manifest_build.py::test_discovered_build_preserves_baseline_digest_and_separates_sources (wording only, #187).
def test_discovered_build_preserves_baseline_digest_and_separates_sources(
    tmp_path: Path, recorded_client: CensusClient
) -> None:
    from etl.build import check
    from etl.source_build import build_sources

    sources = manifests(tmp_path / "sources")
    output = tmp_path / "output"
    assert build_sources(sources, output) == 324
    assert check(output)
    assert check(output / "additional")
    assert hashlib.sha256((output / "facts.tsv").read_bytes()).hexdigest() == (
        "87fc38aec204c1b42f058a01e41e2f60e9dfc2099adaada010466be6457e5cc6"
    )
    # Only the method separators changed: the pre-#187 bytes come back.
    assert hashlib.sha256(old_separators((output / "facts.tsv").read_bytes())).hexdigest() == DIGEST
    assert len((output / "additional/facts.tsv").read_text().splitlines()) == 82
