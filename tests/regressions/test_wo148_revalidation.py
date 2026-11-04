"""#211 acceptance: accepted catalog only; optional enrichment awaits integration."""

from datetime import date
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from etl.programs import Program, load_catalog
from etl.programs.__main__ import main
from etl.programs.links import LinkResponse, check_catalog, http_content_get, iter_program_urls
from etl.programs.revalidation import CheckState, load_checks, revalidate, save_checks

CATALOG = Path("data/programs.yaml")
URLS = {
    "official_url": "https://humanservices.hawaii.gov/official",
    "referral_url": "https://www.auw211.org/",
    "agency_guideline.source_url": "https://humanservices.hawaii.gov/guideline",
    "eligibility_proxy.source_url": "https://api.census.gov/proxy",
}
DIGEST = sha256(b"reviewed bytes").hexdigest()


@pytest.fixture
def program() -> Program:
    raw = load_catalog(CATALOG)[0].model_dump(mode="json")
    raw["official_url"] = URLS["official_url"]
    raw["agency_guideline"]["source_url"] = URLS["agency_guideline.source_url"]
    raw["eligibility_proxy"]["source_url"] = URLS["eligibility_proxy.source_url"]
    return Program.model_validate(raw)


def test_all_catalog_urls_reach_both_consumers(program: Program) -> None:
    before = CATALOG.read_bytes()
    verified = program.last_verified
    assert dict(iter_program_urls(program)) == URLS
    get = Mock(return_value=LinkResponse(200, body=b"reviewed bytes"))
    report = check_catalog([program], get=get, today=lambda: date(2026, 10, 26))
    assert not report.failures
    assert [call.args[0] for call in get.call_args_list] == list(URLS.values())
    get.reset_mock()
    state = revalidate([program], CheckState(), get=get)
    assert [(o.field, o.url) for o in state.observations] == list(URLS.items())
    assert [call.args[0] for call in get.call_args_list] == list(URLS.values())
    assert all(o.sha256 == DIGEST for o in state.observations)
    assert state.needs_review
    assert program.last_verified == verified
    assert CATALOG.read_bytes() == before


def test_changed_hash_stays_pending_across_save_reload_recheck(
    program: Program, tmp_path: Path
) -> None:
    before = CATALOG.read_bytes()
    verified = program.last_verified
    baseline = dict.fromkeys(URLS.values(), DIGEST)
    state = CheckState(reviewed=baseline)
    same = Mock(return_value=LinkResponse(200, body=b"reviewed bytes"))
    assert not revalidate([program], state, get=same).needs_review
    changed = Mock(return_value=LinkResponse(200, body=b"new bytes"))
    path = tmp_path / "checks.json"
    result = revalidate([program], state, get=changed)
    save_checks(path, result)
    assert load_checks(path) == result
    assert path.read_text().count(sha256(b"new bytes").hexdigest()) == 4
    again = revalidate([program], load_checks(path), get=changed)
    assert again.needs_review
    assert again.reviewed == baseline
    assert result.reviewed == baseline
    assert CATALOG.read_bytes() == before
    assert program.last_verified == verified


def test_new_url_needs_review_even_when_other_urls_unchanged(program: Program) -> None:
    baseline = dict.fromkeys(list(URLS.values())[1:], DIGEST)
    state = revalidate(
        [program],
        CheckState(reviewed=baseline),
        get=Mock(return_value=LinkResponse(200, body=b"reviewed bytes")),
    )
    assert state.needs_review
    assert state.reviewed == baseline


@pytest.mark.parametrize("status", [401, 403, 429, 404, 500])
def test_unsuccessful_responses_never_hash(program: Program, status: int) -> None:
    state = revalidate(
        [program], CheckState(), get=Mock(return_value=LinkResponse(status, body=b"error"))
    )
    assert state.needs_review
    assert all(o.sha256 is None and o.error for o in state.observations)


@pytest.mark.parametrize("redirect", [False, True])
def test_untrusted_hosts_rejected_before_network(program: Program, redirect: bool) -> None:
    raw = program.model_dump(mode="json")
    raw["official_url"] = "https://evil.example/"
    unsafe = Program.model_validate(raw)
    get = Mock(return_value=LinkResponse(302, "https://evil.example/"))
    result = revalidate([program if redirect else unsafe], CheckState(), get=get)
    assert all(call.args[0] != "https://evil.example/" for call in get.call_args_list)
    assert "Untrusted URL" in (result.observations[0].error or "")
    assert result.observations[0].sha256 is None


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (LinkResponse(302), "Missing redirect location"),
        (LinkResponse(302, "/bad\npath"), "Untrusted URL"),
        (LinkResponse(302, "https://["), "Untrusted URL"),
        (LinkResponse(302, "/loop"), "Too many redirects"),
        (LinkResponse(200), "Missing response body"),
    ],
)
def test_fetch_failures_are_not_hashes(
    program: Program, response: LinkResponse, message: str
) -> None:
    result = revalidate([program], CheckState(), get=Mock(return_value=response))
    assert all(o.sha256 is None and message in (o.error or "") for o in result.observations)


def test_network_error_is_not_a_hash(program: Program) -> None:
    result = revalidate([program], CheckState(), get=Mock(side_effect=OSError("offline")))
    assert all(
        o.sha256 is None and "HTTP request failed" in (o.error or "") for o in result.observations
    )


def test_trusted_redirect_hashes_final_body(program: Program) -> None:
    def get(url: str, timeout: float) -> LinkResponse:
        assert timeout > 0
        if url.endswith("/final"):
            return LinkResponse(200, body=b"reviewed bytes")
        return LinkResponse(302, "https://humanservices.hawaii.gov/final", body=b"redirect")

    result = revalidate([program], CheckState(), get=get)
    assert all(o.sha256 == DIGEST for o in result.observations)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ('{"reviewed":{"https://agency.gov/":"not a hash"}}', "string_pattern_mismatch"),
        ('{"unexpected":1}', "extra_forbidden"),
        (
            '{"observations":[{"program_id":"snap","field":"official_url","url":"https://agency.gov/","sha256":null,"error":null}]}',
            "exclusively",
        ),
        ('{"version":2}', "literal_error"),
        ("{", "json_invalid"),
        ('{"reviewed":{"not-a-url":"' + DIGEST + '"}}', "url_parsing"),
        (
            '{"reviewed":{"https://agency.gov/\\nx":"' + DIGEST + '"}}',
            "URL contains control or space",
        ),
        (
            '{"observations":[{"program_id":"snap","field":"official_url","url":"https://agency.gov/","sha256":"'
            + DIGEST
            + '","error":"failed"}]}',
            "exclusively",
        ),
    ],
)
def test_invalid_persistence_rejected(tmp_path: Path, raw: str, message: str) -> None:
    path = tmp_path / "checks.json"
    path.write_text(raw)
    with pytest.raises(ValidationError, match=message):
        load_checks(path)


def test_missing_persistence_is_not_silently_reset(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_checks(tmp_path / "missing.json")


def test_cli_previews_then_explicitly_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from etl.programs import __main__ as cli

    original = CATALOG.read_bytes()
    checks = tmp_path / "checks.json"
    save_checks(checks, CheckState())
    before = checks.read_bytes()
    real_revalidate = revalidate
    get = Mock(return_value=LinkResponse(200, body=b"reviewed bytes"))

    def mocked_revalidate(programs: list[Program], state: CheckState) -> CheckState:
        return real_revalidate(programs, state, get=get)

    monkeypatch.setattr(cli, "revalidate", mocked_revalidate)
    args = ["--revalidate", "--checks", str(checks)]
    assert main(args) == 1
    assert "REVIEW" in capsys.readouterr().out
    assert checks.read_bytes() == before
    assert main([*args, "--save"]) == 1
    assert load_checks(checks).observations
    assert load_checks(checks).reviewed == {}
    assert CATALOG.read_bytes() == original


def test_cli_rejects_save_without_revalidation() -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["--save"])


def test_content_facade_reads_bytes_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    from etl.programs import links

    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 200
    response.getheader.return_value = None
    response.read.return_value = b"reviewed bytes"
    monkeypatch.setattr(links, "HTTPSConnection", Mock(return_value=connection))
    assert http_content_get("https://agency.gov/page", 10).body == b"reviewed bytes"
    response.read.assert_called_once()
    connection.close.assert_called_once()


def test_programming_errors_abort_instead_of_becoming_observations(program: Program) -> None:
    with pytest.raises(ValueError, match="broken adapter"):
        revalidate([program], CheckState(), get=Mock(side_effect=ValueError("broken adapter")))


@pytest.mark.parametrize("status", [200, 302, 403, 500])
def test_content_facade_only_reads_successful_bodies(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    from etl.programs import links

    connection = Mock()
    response = connection.getresponse.return_value
    response.status = status
    response.getheader.return_value = None
    response.read.return_value = b""
    monkeypatch.setattr(links, "HTTPSConnection", Mock(return_value=connection))
    result = http_content_get("https://agency.gov/", 10)
    assert result.body == (b"" if status == 200 else None)
    assert response.read.call_count == (1 if status == 200 else 0)
    connection.close.assert_called_once()


def test_content_facade_closes_on_read_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from etl.programs import links

    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 200
    response.read.side_effect = OSError("read failed")
    monkeypatch.setattr(links, "HTTPSConnection", Mock(return_value=connection))
    with pytest.raises(OSError, match="read failed"):
        http_content_get("https://agency.gov/", 10)
    connection.close.assert_called_once()


def test_cli_unchanged_and_missing_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from etl.programs import __main__ as cli

    get = Mock(return_value=LinkResponse(200, body=b"reviewed bytes"))
    state = revalidate(load_catalog(CATALOG), CheckState(), get=get)
    state.reviewed = {o.url: DIGEST for o in state.observations}
    checks = tmp_path / "checks.json"
    save_checks(checks, state)
    real_revalidate = revalidate

    def mocked_revalidate(programs: list[Program], previous: CheckState) -> CheckState:
        return real_revalidate(programs, previous, get=get)

    monkeypatch.setattr(cli, "revalidate", mocked_revalidate)
    assert main(["--revalidate", "--checks", str(checks)]) == 0
    assert "UNCHANGED reviewed content" in capsys.readouterr().out
    assert main(["--revalidate", "--checks", str(tmp_path / "missing")]) == 1
    assert "Content check failed" in capsys.readouterr().out


def test_failed_save_preserves_baseline_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "checks.json"
    save_checks(path, CheckState(reviewed={URLS["official_url"]: DIGEST}))
    before = path.read_bytes()
    monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        save_checks(path, CheckState())
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
