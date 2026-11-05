"""WO185 / WO141 step 1: deterministic readability scoring contract."""

import pytest

from scripts.readability import score, syllables


def test_known_score() -> None:
    result = score("The cat sat on the mat.")
    assert (result.words, result.sentences, result.syllables) == (6, 1, 6)
    assert result.grade == pytest.approx(-1.45)


def test_known_multisyllable_score_is_not_rounded() -> None:
    result = score("People make tables.")
    assert (result.words, result.sentences, result.syllables) == (3, 1, 5)
    assert result.grade == pytest.approx(5.246666666666666)


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("cat", 1),
        ("make", 1),
        ("table", 2),
        ("baked", 1),
        ("wanted", 2),
        ("boxes", 2),
        ("cats", 1),
        ("people", 2),
        ("queue", 1),
        ("rhythm", 1),
        ("don't", 1),
        ("123", 1),
    ],
)
def test_syllable_rules(word: str, expected: int) -> None:
    assert syllables(word) == expected


@pytest.mark.parametrize("text", ["", " \n\t", "...!? —", "Hawaiʻi Kauaʻi"])
def test_empty_has_no_passing_grade(text: str) -> None:
    result = score(text)
    assert (result.words, result.sentences, result.syllables, result.grade) == (0, 0, 0, None)


def test_fragments_and_sentence_boundaries() -> None:
    result = score("Cat\nDog! Fish? Bird... Bat; rat: mat")
    assert (result.words, result.sentences, result.syllables) == (7, 5, 7)
    assert score("Cat!?!\n\nDog").sentences == 2
    assert score("Cat").sentences == 1


def test_numbers_and_placeholders_do_not_score_internal_keys() -> None:
    result = score("Rate {poverty_rate} and {{ household_income }} is 12.5%.")
    assert (result.words, result.sentences, result.syllables) == (6, 1, 6)
    assert score("Use [careful wording].").words == 3


@pytest.mark.parametrize(
    "name", ["Hawaiʻi", "Kauaʻi", "Lānaʻi", "Molokaʻi", "Oʻahu", "Kahoʻolawe", "Niʻihau"]
)
def test_exact_name_exclusions(name: str) -> None:
    assert score(f"{name}, cats sleep.") == score("Cats sleep.")


@pytest.mark.parametrize("name", ["Hawaii", "Hawai'i", "hawaiʻi", "Hawaiʻian", "Maui", "kūpuna"])
def test_no_broad_name_exclusion(name: str) -> None:
    assert score(name).words == 1


def test_citations_use_only_explicit_original_character_spans() -> None:
    text = "Cats [Source: ACS. 2024] sleep."
    start, end = text.index("["), text.index("]") + 1
    assert score(text, [(start, end)]) == score("Cats sleep.")
    assert score(text).words > 2
    assert score("catSOURCEdog", [(3, 9)]).words == 2
    assert score(text, [(0, len(text))]).grade is None
    assert score("🐟 Cats [ACS] sleep.", [(7, 12)]) == score("Cats sleep.")


@pytest.mark.parametrize("spans", [[(-1, 2)], [(0, 99)], [(2, 2)], [(3, 1)]])
def test_invalid_citation_bounds(spans: list[tuple[int, int]]) -> None:
    with pytest.raises(ValueError, match="citation span must satisfy"):
        score("Cats sleep.", spans)


@pytest.mark.parametrize("spans", [[(0, 4), (3, 6)], [(5, 8), (0, 4)]])
def test_overlapping_or_unsorted_citation_spans(spans: list[tuple[int, int]]) -> None:
    with pytest.raises(ValueError, match="citation spans must be sorted and disjoint"):
        score("Cats sleep.", spans)


def test_adjacent_spans_and_unicode_normalization() -> None:
    assert score("CatsAB sleep.", [(4, 5), (5, 6)]) == score("Cats sleep.")
    assert score("La\u0304naʻi cats.") == score("Cats.")
