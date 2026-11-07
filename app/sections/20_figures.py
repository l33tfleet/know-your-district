# ruff: noqa: N999 -- sections are named NN_name.py by convention (#97); the prefix orders them
"""Three figures (population, share 65+, median household income) for the district, each read
as one sentence suited to its unit (#284): the district's figure with its ±MOE and reliability
in words, the county and state figures beside it, and every shown geography cited."""

from string import Formatter

from app.brief_facts import FORMATS, KINDS, BriefFacts, citation, comparison, reading
from app.copy import Copy, geography_name, section_copy
from app.counties import load_mapping
from app.facts import FactStore, acs_config
from app.features import enabled
from app.models import Fact
from app.page_state import PageState
from app.source_links import MAPPING_URL, evidence_link, source_links

Part = dict[str, object]


def phrase(template: str, **slots: str | dict[str, object]) -> list[Part]:
    """Split a copy template into text parts and reading parts; numbers never enter text."""
    parts: list[Part] = []
    for text, name, _, _ in Formatter().parse(template):
        if text:
            parts.append({"text": text})
        if name is not None:
            slot = slots[name]
            parts.append({"text": slot} if isinstance(slot, str) else {"reading": slot})
    return parts


def sentence(
    figure: str, readings: list[dict[str, object]], found: list[Fact | None], copy: Copy
) -> list[Part]:
    """One sentence: the district clause, then a clause per county and the state.

    Population (never compared) names the reference counts; the share and the median carry
    `comparison()`'s words, which make no larger/smaller claim unless the difference is real.
    """
    kind = KINDS[figure]
    district, *references = readings
    parts = phrase(
        copy[f"{kind.kind}_sentence"],
        geography=geography_name(str(district["geography"])),
        reading=district,
    )
    for ref, fact in zip(references, found[1:], strict=True):
        name = geography_name(str(ref["geography"]))
        parts.append({"text": copy["clause_separator"]})
        words = comparison(
            found[0], fact, FORMATS[figure], copy, figure=figure, geography=str(ref["geography"])
        )
        if words is None:
            parts.extend(phrase(copy["count_reference"], name=name, reading=ref))
            continue
        parts.extend(
            phrase(copy["comparison_clause"], lead=str(words["clause"]), name=name, reading=ref)
        )
        if words["tail"]:
            parts.extend(phrase(copy["comparison_tail"], tail=str(words["tail"])))
    parts.append({"text": copy["sentence_end"]})
    return parts


def companion(figure: str, district: str) -> Fact | None:
    """The published count behind a share, only if its own Fact exists; never computed."""
    variable = KINDS[figure].companion_count
    if variable is None:
        return None
    vintage, _ = acs_config()
    return FactStore.default().get([(variable, district)], vintage).get((variable, district))


def context(state: PageState) -> dict[str, object]:
    copy = section_copy("figures")
    vintage, _ = acs_config()
    checks_enabled = enabled("source_links", state)
    selected = BriefFacts(state.district, load_mapping()[state.district.fact_key])
    district = selected.district
    shares = selected.shares
    geographies = selected.geographies
    variables = selected.variables
    facts = selected.facts
    figures: list[dict[str, object]] = []
    for figure, fmt in FORMATS.items():
        found = [facts.get((variables[figure], g)) for g in geographies]
        readings = [reading(g, f, fmt, copy) for g, f in zip(geographies, found, strict=True)]
        for r in readings[1:-1]:
            r["label"] = geography_name(str(r["geography"]))
        cited = [(f, fmt, False) for f in found if f is not None]
        count = companion(figure, district)
        count_sentence: list[Part] = []
        if count is not None:
            cited.append((count, FORMATS["population"], True))
            count_sentence = phrase(
                copy["companion_sentence"],
                geography=geography_name(district),
                reading=reading(district, count, FORMATS["population"], copy),
            )
        figures.append(
            {
                "key": figure,
                "kind": KINDS[figure].kind,
                "variable": variables[figure],
                "name": copy["names"][figure],
                # The same dicts the sentence shows, so a caller's edit reaches both.
                "district": readings[0],
                "state": readings[-1],
                "counties": readings[1:-1],
                # With nothing loaded (#129) the section's notice says so once, and the card
                # falls back to stacked readings, each one short phrase, not a sentence of blanks.
                "sentence": sentence(figure, readings, found, copy) if facts else [],
                "count_sentence": count_sentence,
                "count_unavailable": copy["count_unavailable"]
                if KINDS[figure].kind == "share" and count is None
                else "",
                "citations": [
                    citation(f, f_fmt, copy)
                    | {"links": source_links(f) if checks_enabled else (), "companion": extra}
                    for f, f_fmt, extra in cited
                ],
            }
        )
    return {
        "figures": figures,
        "multi_county": len(shares) > 1,
        "county_shares": [
            {"name": geography_name(s.county), "share_text": f"{s.area_share * 100:.1f}%"}
            for s in shares
        ],
        "mapping": shares[0],
        "mapping_links": [
            evidence_link(shares[0].district_source, "district_source"),
            evidence_link(shares[0].county_source, "county_source"),
            evidence_link(MAPPING_URL, "mapping_file"),
        ]
        if checks_enabled
        else [],
        "not_loaded": None if facts else copy["not_loaded"].format(vintage=vintage),
    }
