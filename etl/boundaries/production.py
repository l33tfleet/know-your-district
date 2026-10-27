"""Offline production export of normalized WGS84 boundaries.

Source-specific attribute mapping belongs before BoundaryCollection validation.
The optional fact comparison proves key equality, not geographic correspondence
or fact-table completeness. No real database or official boundaries ship here.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from etl.boundaries import DISTRICT_COUNTS, BoundaryCollection, all_districts


def compare_fact_keys(facts_db: Path, boundary_keys: set[str]) -> None:
    """Compare all district identities; counties/state are outside this contract.

    Distinct keys allow multiple variables/vintages per district. Unknown keys
    are retained so a misspelled chamber cannot silently disappear from the join.
    """
    with (
        closing(sqlite3.connect(facts_db.resolve().as_uri() + "?mode=ro", uri=True)) as db,
        closing(db.execute("SELECT DISTINCT geography FROM facts")) as cursor,
    ):
        fact_keys = {
            row[0]
            for row in cursor
            if row[0] != "state:15" and not str(row[0]).startswith("county:")
        }
    if fact_keys != boundary_keys:
        raise ValueError(
            f"fact key mismatch: missing={sorted(boundary_keys - fact_keys)}, "
            f"extra={sorted(fact_keys - boundary_keys)}"
        )


def export_boundaries(
    collection: BoundaryCollection,
    output: Path,
    *,
    credit: str,
    facts_db: Path | None = None,
) -> None:
    """Write qualified GeoJSON plus .provenance.json and .credit.txt sidecars.

    Require exactly the 2022 Hawaiʻi House and Senate district sets before
    writing anything. Existing local validators continue to accept partial sets.
    Credit is supplied by the operator from the source's attribution terms.
    """
    collection = BoundaryCollection.model_validate(collection.model_dump(mode="json"))
    expected = {
        district.fact_key for chamber in DISTRICT_COUNTS for district in all_districts(chamber)
    }
    actual = {feature.properties.fact_key for feature in collection.features}
    if actual != expected:
        raise ValueError(
            f"boundary key mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    if not credit.strip():
        raise ValueError("source credit must not be blank")
    provenance_path = output.with_suffix(".provenance.json")
    credit_path = output.with_suffix(".credit.txt")
    destinations = {output.resolve(), provenance_path.resolve(), credit_path.resolve()}
    if len(destinations) != 3 or (facts_db is not None and facts_db.resolve() in destinations):
        raise ValueError("export paths must be distinct from each other and the fact database")
    if facts_db is not None:
        compare_fact_keys(facts_db, actual)
    features = [
        {**feature.model_dump(mode="json"), "id": feature.properties.fact_key}
        for feature in sorted(collection.features, key=lambda feature: feature.properties.fact_key)
    ]
    output.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    provenance_path.write_text(
        collection.provenance.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    credit_path.write_text(credit.strip() + "\n", encoding="utf-8")
