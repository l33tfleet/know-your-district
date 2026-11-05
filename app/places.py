"""Place names to House districts: the hand-curated `data/places/oahu_places.tsv`.

Step 1 of WO #263 (Oʻahu, House only). Each row is a place with its correct spelling, its
ASCII alias, its House district and one point inside it (lon/lat, read only by the
regression test that checks the district by point-in-polygon). Matching ignores the ʻokina,
kahakō and case; results keep the file's spelling. No addresses, no geocoding.
"""

import unicodedata
from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from etl.boundaries import DISTRICT_COUNTS

PLACES_PATH = Path(__file__).resolve().parent.parent / "data/places/oahu_places.tsv"
HEADER = ("place", "alias", "house", "lon", "lat")
ISLAND = "Oʻahu"
# The ʻokina and what gets typed for it: apostrophe, left and right quotes.
OKINAS = "".join(map(chr, (0x02BB, 0x27, 0x2018, 0x2019)))


def fold(text: str) -> str:
    """Comparable form: no kahakō or other marks, no ʻokina, casefolded, single spaces."""
    kept = (
        ch
        for ch in unicodedata.normalize("NFD", text)
        if not unicodedata.combining(ch) and ch not in OKINAS
    )
    return " ".join("".join(kept).casefold().split())


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    place: str
    alias: str
    island: str = ISLAND
    house: int
    lon: float
    lat: float

    @field_validator("house")
    @classmethod
    def house_in_range(cls, value: int) -> int:
        if not 1 <= value <= DISTRICT_COUNTS["house"]:
            raise ValueError(f"house district {value} is not 1–{DISTRICT_COUNTS['house']}")
        return value


def load_places(path: Path = PLACES_PATH) -> tuple[Place, ...]:
    """Read and validate the file; a bad header, row or duplicate place fails loudly."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or tuple(lines[0].split("\t")) != HEADER:
        raise ValueError(f"{path}: header must be {chr(9).join(HEADER)!r}")
    places: list[Place] = []
    seen: set[str] = set()
    for number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != len(HEADER):
            raise ValueError(f"{path}:{number}: expected {len(HEADER)} fields, got {len(fields)}")
        place = Place.model_validate(dict(zip(HEADER, fields, strict=True)))
        if fold(place.place) in seen:
            raise ValueError(f"{path}:{number}: duplicate place {place.place!r}")
        seen.add(fold(place.place))
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
    names = {p: (fold(p.place), fold(p.alias)) for p in curated()}
    exact = [p for p, folded in names.items() if key in folded]
    if exact or len(key) < 3:
        return exact
    return sorted((p for p, (name, _) in names.items() if key in name), key=lambda p: p.place)
