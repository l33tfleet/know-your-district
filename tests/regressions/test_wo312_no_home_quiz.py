"""WO #312: the home page asks no stats quiz. Kevin rejected #309's fixed-question ranking (2026-10-30): people come to
serve people, not to be quizzed on statistics. This replaces tests/regressions/test_wo302_question_rankings.py."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_home_has_the_picker_and_no_question_form() -> None:
    html = client.get("/").text
    assert 'class="picker"' in html
    assert 'class="question"' not in html
    assert 'id="question-answer"' not in html


def test_the_quiz_routes_are_gone() -> None:
    assert client.get("/questions", params={"q": "age_65_share"}).status_code == 404
    assert 'class="question"' not in client.get("/", params={"q": "median_household_income"}).text
