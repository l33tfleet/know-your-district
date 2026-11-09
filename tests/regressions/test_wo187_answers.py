"""WO187: brief, SNAP and artifact checks, with the plain wording.

Each test here is a copy of a superseded test, changed only where it pinned old
words or the digests of artifacts whose method notes now end clauses as sentences.
Digest copies also prove that putting the old semicolons back restores the old
bytes, so no value, MOE, CV, reliability, citation or row changed.
"""

from app.copy import section_copy
from tests.regressions.test_wo140_answers import DISTRICT, fact, render

__all__ = ["DISTRICT", "fact", "render"]


# Replaces test_wo140_answers.py::test_all_geography_labels_and_escaped_fact_labels (wording only, #187).
def test_all_geography_labels_and_escaped_fact_labels() -> None:
    row = fact(DISTRICT, 103, 2, label="<script>untrusted</script>").model_copy(
        update={"method": "derived estimate from published cells"}
    )
    html = render(
        {"kind": "routed", "indicator_id": "below_poverty_no_snap", "confidence": 0.9}, [row]
    )
    assert "Built from published figures" in html
    assert "&lt;script&gt;untrusted&lt;/script&gt;" in html
    assert "<script>" not in html
    assert set(section_copy("ask")["geography_labels"].values()) == {
        "Published for district",
        "Built from published figures",
        "County/state context",
    }
