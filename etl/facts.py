"""Convert metadata-checked Census batches to published, validated scalar facts."""

from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.analysis.reliability import classify
from app.models import Fact
from etl.boundaries import all_districts
from etl.census import CensusBatch, CensusError
from etl.indicators import Indicator

HOUSE = "state legislative district (lower chamber)"
SENATE = "state legislative district (upper chamber)"
SENTINELS: dict[Decimal, str] = {
    Decimal(-666666666): "not available",
    Decimal(-999999999): "not available",
    Decimal(-888888888): "not available",
    Decimal(-555555555): "controlled",
    Decimal(-222222222): "not available",
    Decimal(-333333333): "not available: median in open-ended interval (top/bottom-coded)",
}


def _number(raw: str | None) -> tuple[Decimal | None, str | None]:
    if raw is None:
        return None, "not available"
    try:
        number = Decimal(raw)
    except InvalidOperation:
        raise CensusError("Invalid numeric Census cell") from None
    if not number.is_finite():
        raise CensusError("Invalid numeric Census cell")
    if number in SENTINELS:
        return None, SENTINELS[number]
    if number < 0:
        raise CensusError("Invalid numeric Census cell")
    return number, None


def _geographies(batch: CensusBatch, request: str) -> list[tuple[str, dict[str, str | None]]]:
    district_keys: dict[str, str] = {}
    if request == "state:15":
        column, prefix, expected = "state", "state", {"15"}
    elif request == "county:*":
        column, prefix, expected = "county", "county", {"001", "003", "007", "009"}
    elif request in (HOUSE + ":*", SENATE + ":*"):
        column = request[:-2]
        prefix = "house" if column == HOUSE else "senate"
        district_keys = {
            district.census_code: district.fact_key for district in all_districts(prefix)
        }
        expected = set(district_keys)
    else:
        raise CensusError("Unsupported Census geography request")
    seen: set[str] = set()
    rows: list[tuple[str, dict[str, str | None]]] = []
    for row in batch.rows:
        code = row.get(column)
        if row.get("state") != "15" or code is None or code in seen:
            raise CensusError("Missing, duplicate or incorrect Census geography")
        seen.add(code)
        if column == "county" and code == "005":
            continue
        if code not in expected:
            raise CensusError("Unexpected Census geography identity")
        if district_keys:
            key = district_keys[code]
        else:
            key = "state:15" if prefix == "state" else f"{prefix}:15:{code}"
        rows.append((key, row))
    if seen - ({"005"} if column == "county" else set()) != expected:
        raise CensusError("Incomplete Census geography set")
    return rows


def facts_from_batch(indicator: Indicator, batch: CensusBatch, geography: str) -> list[Fact]:
    """Require the exact requested HI geography set; exclude Kalawao before conversion.

    The batch must come from CensusClient's metadata gate. No sums, bracket
    interpolation or other derived estimates are performed here.
    """
    facts: list[Fact] = []
    for key, row in _geographies(batch, geography):
        for variable in indicator.variables:
            moe_variable = indicator.moe_variable(variable)
            try:
                value, estimate_status = _number(row[variable])
                moe, moe_status = _number(row[moe_variable])
                estimate_annotation = row[variable + "A"]
                moe_annotation = row[moe_variable + "A"]
                label = batch.labels[variable]
            except KeyError:
                raise CensusError("Missing Census cell, annotation or label") from None
            cv, reliability = classify(value, moe)
            method = "published estimate and 90% margin of error"
            for name, status, annotation in (
                ("estimate", estimate_status, estimate_annotation),
                ("MOE", moe_status, moe_annotation),
            ):
                if status is not None:
                    method += f"; {name} {status}"
                if annotation:
                    method += f"; {name} annotation: {annotation}"
            try:
                facts.append(
                    Fact(
                        variable=variable,
                        geography=key,
                        vintage=batch.vintage,
                        value=float(value) if value is not None else None,
                        moe=float(moe) if moe is not None else None,
                        cv=float(cv) if cv is not None else None,
                        reliability=reliability,
                        source="U.S. Census Bureau ACS 5-year",
                        table_id=indicator.table_id,
                        method=method,
                        endpoint=batch.endpoint,
                        label=label,
                        estimate_annotation=estimate_annotation,
                        moe_annotation=moe_annotation,
                    )
                )
            except ValidationError:
                raise CensusError("Invalid Census fact or provenance") from None
    return facts
