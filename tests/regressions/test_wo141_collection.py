"""WO186: collection keeps difficult leaves and blocks independently visible."""

import json
from pathlib import Path

import pytest

from scripts.readability import score
from scripts.readability_corpus import (
    collect,
    recorded_blocks,
    rendered_blocks,
    rendered_pages,
    yaml_blocks,
)

HARD = "Institutionalization necessitates interdisciplinary administrative operationalization."


@pytest.mark.parametrize("source", ["copy", "programs"])
def test_every_yaml_leaf_including_nested_lists(source: str, tmp_path: Path) -> None:
    path = tmp_path / f"{source}.yaml"
    path.write_text(
        f'label: "{HARD}"\nnested:\n  - purpose: "{HARD}"\n    empty: null\n  - [false, 2, ""]\n',
        encoding="utf-8",
    )
    blocks = yaml_blocks(path)
    assert len(blocks) == 6
    assert len({b.id for b in blocks}) == 6
    assert sum(b.text == HARD for b in blocks) == 2
    assert all(not b.citation_spans for b in blocks)
    for block in blocks:
        if block.text == HARD:
            grade = score(block.text).grade
            assert grade is not None and grade > 12


def test_rendered_blocks_do_not_average_or_hide_prose_as_citations() -> None:
    html = f'''<label>{HARD}</label><p>Cats sleep. <em>{HARD}</em></p>
    <details class="source"><summary>{HARD}</summary><dl class="citation">
    <dt>{HARD}</dt><dd data-field="source">ACS</dd>
    <dd data-field="method">{HARD}</dd><dd>Care: {HARD} <code data-field="geography">state:15</code></dd>
    </dl><p class="missing">{HARD}</p></details>
    <li class="program"><p>{HARD}</p></li><svg><text>County label</text></svg>
    <input aria-label="{HARD}" placeholder="{HARD}"><script>{HARD}</script>'''
    blocks = rendered_blocks(html, "injected")
    difficult = [b for b in blocks if HARD in b.text]
    assert len(difficult) == 10
    for block in difficult:
        result = score(block.text, block.citation_spans)
        assert result.grade is not None and result.grade > 12
        assert all(HARD not in block.text[start:end] for start, end in block.citation_spans)
    assert any(b.text == "County label" for b in blocks)
    assert not any("script" in b.id for b in blocks)
    assert any(b.text == "ACS" and b.citation_spans == ((0, 3),) for b in blocks)


def test_recorded_answer_and_refusal_keep_offsets_and_prose(tmp_path: Path) -> None:
    path = tmp_path / "answers.jsonl"
    text = f"{HARD} [ACS] {HARD}"
    start = text.index("[")
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": kind,
                    "kind": kind,
                    "text": text,
                    "citation_spans": [[start, start + 5]],
                }
            )
            for kind in ("answer", "refusal")
        ),
        encoding="utf-8",
    )
    blocks = recorded_blocks(path)
    assert {b.source for b in blocks} == {"answer", "refusal"}
    assert all(b.text == text and b.citation_spans == ((start, start + 5),) for b in blocks)
    for block in blocks:
        result = score(block.text, block.citation_spans)
        assert result.grade is not None and result.grade > 12


@pytest.mark.parametrize(
    "record, message",
    [
        ({"id": "x", "kind": "other", "text": "hi", "citation_spans": []}, "kind"),
        ({"id": "", "kind": "answer", "text": "hi", "citation_spans": []}, "id"),
        ({"id": "x", "kind": "answer", "text": "hi", "citation_spans": [[0, 5]]}, "citation span"),
        ({"id": "x", "kind": "answer", "text": "hi", "citation_spans": [[False, 1]]}, "integer"),
        ({"id": "x", "kind": "answer", "text": 1, "citation_spans": []}, "text"),
    ],
)
def test_invalid_recordings_are_errors(
    tmp_path: Path, record: dict[str, object], message: str
) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        recorded_blocks(path)


def test_duplicate_recording_ids_are_errors(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.jsonl"
    row = json.dumps({"id": "same", "kind": "answer", "text": "Hi", "citation_spans": []})
    path.write_text(row + "\n" + row, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        recorded_blocks(path)


def test_absent_coverage_is_explicit(tmp_path: Path) -> None:
    corpus = collect(tmp_path, pages={})
    assert set(corpus.absent) == {
        "app/copy.yaml",
        "data/programs.yaml",
        "rendered",
        "answer",
        "refusal",
    }
    assert not corpus.blocks
    (tmp_path / "app").mkdir()
    (tmp_path / "app/copy.yaml").write_text('label: ""', encoding="utf-8")
    corpus = collect(tmp_path, pages={"empty": "<p> </p>"})
    assert "app/copy.yaml" in corpus.absent
    assert "rendered:empty" in corpus.absent


def test_rendered_matrix_includes_all_districts_counties_and_missing_figures() -> None:
    pages = rendered_pages()
    assert all(f"/brief/house/{n}" in pages for n in range(1, 52))
    assert all(f"/brief/senate/{n}" in pages for n in range(1, 26))
    assert {
        "/",
        "/not-found",
        "/picker/numbers?chamber=senate",
        "fixture:missing-figures",
    } <= pages.keys()
    html = " ".join(pages.values())
    assert all(
        name in html
        for name in ("Hawaiʻi County", "Honolulu County", "Kauaʻi County", "Maui County")
    )
    assert "This district lies in more than one county." in html
    missing = rendered_blocks(pages["fixture:missing-figures"], "missing")
    assert any("No published figure" in b.text for b in missing)
    assert any("not available" in b.text for b in missing)


def test_recorded_coverage_distinguishes_missing_and_unscorable_kinds(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(
        json.dumps({"id": "a", "kind": "answer", "text": HARD, "citation_spans": []}),
        encoding="utf-8",
    )
    corpus = collect(tmp_path, pages={"page": f"<p>{HARD}</p>"}, recordings=path)
    assert "answer" not in corpus.absent and "refusal" in corpus.absent
    assert "rendered:page" not in corpus.absent
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            "\n"
            + json.dumps(
                {"id": "r", "kind": "refusal", "text": "[ACS]", "citation_spans": [[0, 5]]}
            )
        )
    assert "refusal" in collect(tmp_path, pages={}, recordings=path).absent
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            "\n" + json.dumps({"id": "r2", "kind": "refusal", "text": HARD, "citation_spans": []})
        )
    assert "refusal" not in collect(tmp_path, pages={}, recordings=path).absent


def test_rendered_whitespace_does_not_create_fake_sentence_boundaries() -> None:
    block = rendered_blocks("<p>Cats\n  <em>sleep</em> here.</p>", "page")[0]
    assert score(block.text).sentences == 1
    citation = rendered_blocks(
        '<p>Cats\n <code data-field="geography">state:15</code> sleep.</p>', "page"
    )[0]
    assert score(citation.text, citation.citation_spans) == score("Cats sleep.")
