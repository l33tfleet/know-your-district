"""Place names to districts: the hand-curated Oʻahu list in `data/places/oahu_places.tsv`.

Step 1 of WO #263. Each row is one place, its ASCII alias, the House and Senate districts at
one point inside it, and that point (lon/lat, read only by the regression test that checks it
by point-in-polygon). Matching ignores the ʻokina, kahakō, case and extra spaces; results keep
the file's spelling. Place names only: no addresses, no geocoding, no external service.
"""

import difflib
import unicodedata
from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from etl.boundaries import DISTRICT_COUNTS

PLACES_PATH = Path(__file__).resolve().parent.parent / "data/places/oahu_places.tsv"
HEADER = ("place", "alias", "house", "senate", "lon", "lat")
ISLAND = "Oʻahu"
OKINA = "ʻ"
# What gets typed in place of the ʻokina: apostrophe, left/right quote, grave, acute.
OKINA_LOOKALIKES = "'\u2018\u2019`\u00b4"
# Substring matches start at this many folded characters; shorter queries match exactly.
MIN_PARTIAL = 3


def fold(text: str) -> str:
    """Comparable form: no kahakō or other marks, no ʻokina (or lookalike), casefolded."""
    decomposed = unicodedata.normalize("NFD", text)
    kept = (
        ch
        for ch in decomposed
        if not unicodedata.combining(ch) and ch != OKINA and ch not in OKINA_LOOKALIKES
    )
    return " ".join("".join(kept).casefold().split())


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    place: str = Field(min_length=1)
    alias: str = Field(min_length=1)
    island: str = ISLAND
    house: int
    senate: int
    lon: float
    lat: float

    @field_validator("place")
    @classmethod
    def okina_is_u02bb(cls, value: str) -> str:
        if any(ch in OKINA_LOOKALIKES for ch in value):
            raise ValueError(f"{value!r}: write the ʻokina as U+02BB")
        return value

    @field_validator("alias")
    @classmethod
    def alias_is_ascii(cls, value: str) -> str:
        if not value.isascii():
            raise ValueError(f"{value!r}: the alias must be ASCII")
        return value

    @field_validator("house")
    @classmethod
    def house_in_range(cls, value: int) -> int:
        if not 1 <= value <= DISTRICT_COUNTS["house"]:
            raise ValueError(f"house district {value} is not 1–{DISTRICT_COUNTS['house']}")
        return value

    @field_validator("senate")
    @classmethod
    def senate_in_range(cls, value: int) -> int:
        if not 1 <= value <= DISTRICT_COUNTS["senate"]:
            raise ValueError(f"senate district {value} is not 1–{DISTRICT_COUNTS['senate']}")
        return value

    @model_validator(mode="after")
    def alias_spells_the_place(self) -> "Place":
        if fold(self.alias) != fold(self.place):
            raise ValueError(f"alias {self.alias!r} is not {self.place!r} without diacritics")
        return self


def load_places(path: Path = PLACES_PATH) -> tuple[Place, ...]:
    """Read and validate the file; any bad row or folding collision fails loudly."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or tuple(lines[0].split("\t")) != HEADER:
        raise ValueError(f"{path}: header must be {chr(9).join(HEADER)!r}")
    places: list[Place] = []
    seen: dict[str, str] = {}
    for number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != len(HEADER):
            raise ValueError(f"{path}:{number}: expected {len(HEADER)} fields, got {len(fields)}")
        place = Place.model_validate(dict(zip(HEADER, fields, strict=True)))
        key = fold(place.place)
        if key in seen:
            raise ValueError(
                f"{path}:{number}: {place.place!r} and {seen[key]!r} fold to the same name"
            )
        seen[key] = place.place
        places.append(place)
    return tuple(places)


@cache
def curated() -> tuple[Place, ...]:
    return load_places()


def find(q: str) -> list[Place]:
    """Places named `q`; failing that, for 3+ characters, places whose name contains it."""
    key = fold(q)
    if not key:
        return []
    exact = [p for p in curated() if fold(p.place) == key]
    if exact or len(key) < MIN_PARTIAL:
        return exact
    return sorted((p for p in curated() if key in fold(p.place)), key=lambda p: fold(p.place))


def close_spellings(q: str, limit: int = 3) -> list[Place]:
    """Places whose folded name is close to `q`, closest first."""
    by_key = {fold(p.place): p for p in curated()}
    return [by_key[k] for k in difflib.get_close_matches(fold(q), by_key, n=limit, cutoff=0.7)]
