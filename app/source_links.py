"""Offline verification URLs from recorded facts, never model output or live queries."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

from app.models import Fact

MAPPING_URL = "https://github.com/l33tfleet/know-your-district/blob/main/data/district_counties.tsv"


@dataclass(frozen=True)
class SourceLink:
    kind: str
    url: str


def evidence_link(url: str, kind: str = "evidence") -> SourceLink:
    """Recorded evidence must be a web URL without embedded credentials."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.username is not None
        or any(ord(c) < 32 for c in url)
        or {key.lower() for key in parse_qs(parsed.query, keep_blank_values=True)}
        & {"key", "api_key", "token", "access_token"}
    ):
        raise ValueError("Invalid source evidence URL: use HTTP(S) without credentials or controls")
    return SourceLink(kind, url)


def source_links(fact: Fact) -> tuple[SourceLink, ...]:
    """Primary published table and optional credential-free API query.

    Only native published ACS observations identify a Census cell. Derived or
    non-Census observations retain their recorded evidence and citation method.
    Legislative geography's final component is the plan, not the ACS release.
    """
    if not (
        fact.source.startswith("U.S. Census Bureau ACS 5-year")
        and fact.method.startswith("published estimate")
        and re.search(r"\b(?:apportion\w*|deriv\w*|allocat\w*|weight\w*)\b", fact.method, re.I)
        is None
    ):
        return (evidence_link(fact.endpoint),)
    if re.fullmatch(r"(?:[BC][0-9]{5}[A-I]?|DP[0-9]{2}|S[0-9]{4})", fact.table_id) is None:
        raise ValueError("Invalid ACS table identity")
    if (
        re.fullmatch(re.escape(fact.table_id) + r"_(?:C[0-9]{2}_)?[0-9]{3,4}P?E", fact.variable)
        is None
    ):
        raise ValueError("Invalid ACS variable identity")
    vintage = re.fullmatch(r"([0-9]{4})[–-]([0-9]{4})", fact.vintage)
    if vintage is None or int(vintage[2]) - int(vintage[1]) != 4:
        raise ValueError("Invalid ACS vintage: expected a five-year range")
    year = vintage[2]
    geo = re.fullmatch(
        r"(?:(house|senate):([0-9]{2}):([0-9]{3}):[0-9]{4}|county:([0-9]{2}):([0-9]{3})|state:([0-9]{2}))",
        fact.geography,
    )
    if geo is None:
        raise ValueError("Unsupported ACS geography: expected house, senate, county or state")
    params = {"get": fact.variable}
    if geo[1] is not None:
        chamber, summary = ("lower", "620") if geo[1] == "house" else ("upper", "610")
        params |= {
            "for": f"state legislative district ({chamber} chamber):{geo[3]}",
            "in": f"state:{geo[2]}",
        }
        geoid = f"{summary}XX00US{geo[2]}{geo[3]}"
    elif geo[4] is not None:
        params |= {"for": f"county:{geo[5]}", "in": f"state:{geo[4]}"}
        geoid = f"050XX00US{geo[4]}{geo[5]}"
    else:
        params["for"] = f"state:{geo[6]}"
        geoid = f"040XX00US{geo[6]}"
    suffix, family = (
        ("/profile", "ACSDP")
        if fact.table_id.startswith("DP")
        else ("/subject", "ACSST")
        if fact.table_id.startswith("S")
        else ("", "ACSDT")
    )
    return (
        SourceLink(
            "table", f"https://data.census.gov/table/{family}5Y{year}.{fact.table_id}?g={geoid}"
        ),
        SourceLink(
            "api", f"https://api.census.gov/data/{year}/acs/acs5{suffix}?{urlencode(params)}"
        ),
    )
