"""#335: complete program URL observations require explicit content review."""

from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import pytest

from etl.programs import Program, load_catalog
from etl.programs.links import LinkResponse
from etl.programs.verify import CheckState, iter_urls, load_checks, main, verify

CATALOG = Path("data/programs.yaml")
DIGEST = sha256(b"reviewed").hexdigest()


@pytest.fixture
def program() -> Program:
    raw = next(p for p in load_catalog(CATALOG) if p.id == "hawaii-able").model_dump(mode="json")
    raw["enrichment"] = {
        "stats": [
            dict(
                label="Source",
                value=1.0,
                unit="persons",
                geography="Hawaiʻi",
                source="Census",
                source_url="https://api.census.gov/stat",
                table_id="B01003",
                cell="B01003_001E",
                vintage="2020–2024",
                method="Published",
                moe=1.0,
            )
        ],
        "media": [
            dict(
                url="https://agency.gov/photo",
                alt="Coast",
                credit="Agency",
                origin="federal-employee-work",
                licence="federal-public-domain",
                licence_url="https://agency.gov/terms",
            ),
            dict(
                url="https://agency.gov/second",
                alt="Coast",
                credit="Agency",
                origin="third-party",
                licence="permission",
                permission=dict(
                    record_url="https://agency.gov/permission",
                    date="2026-10-25",
                    permits_reuse=True,
                ),
            ),
        ],
    }
    return Program.model_validate(raw)


def test_every_url_occurrence_is_checked(program: Program) -> None:
    urls = dict(iter_urls(program))
    assert set(urls) == {
        "official_url",
        "referral_url",
        "agency_guideline.source_url",
        "eligibility_proxy.source_url",
        "rules.rule_url",
        "rules.application_url",
        "next_steps.contact.url",
        "enrichment.stats.0.source_url",
        "enrichment.media.0.url",
        "enrichment.media.0.licence_url",
        "enrichment.media.1.url",
        "enrichment.media.1.permission.record_url",
    }
    get = Mock(return_value=LinkResponse(200, body=b"reviewed"))
    state = verify([program], CheckState(), get=get)
    assert [(o.field, o.url) for o in state.observations] == list(urls.items())
    # The existing HTTP trust policy rejects the unapproved ABLE host before sending.
    assert {call.args[0] for call in get.call_args_list} == {
        url for url in urls.values() if "hawaiiablesavings.com" not in url
    }
    assert state.needs_review


@pytest.mark.parametrize("body", [b"reviewed", b"changed"])
def test_hashes_never_renew_review_or_dates(program: Program, body: bytes) -> None:
    # Use only trusted URLs for this hash comparison.
    assert program.rules is not None
    program.rules.application_url = program.official_url
    before = program.model_dump_json()
    baseline = dict.fromkeys(dict(iter_urls(program)).values(), DIGEST)
    state = verify(
        [program],
        CheckState(reviewed=baseline),
        get=Mock(return_value=LinkResponse(200, body=body)),
    )
    assert state.needs_review == (body != b"reviewed")
    assert state.reviewed == baseline
    assert program.model_dump_json() == before


@pytest.mark.parametrize(
    ("result", "expected_error"),
    [
        (LinkResponse(403), "HTTP 403: refused automated access; not verified"),
        (LinkResponse(403, body=b"denied"), "HTTP 403: refused automated access; not verified"),
        (LinkResponse(404), "HTTP 404: {url}"),
        (LinkResponse(500), "HTTP 500: {url}"),
        (LinkResponse(200), "Missing response body; not verified"),
        (OSError("offline"), "HTTP request failed: {url}"),
    ],
)
def test_failures_need_review_without_hashes(result: object, expected_error: str) -> None:
    # Every URL of this program is trusted, so trust rejection cannot mask a failure.
    program = load_catalog(CATALOG)[0]
    get = Mock(side_effect=result) if isinstance(result, OSError) else Mock(return_value=result)
    state = verify([program], CheckState(), get=get)
    assert get.call_count == len(state.observations) > 0
    assert state.needs_review
    for observation in state.observations:
        assert observation.sha256 is None
        assert observation.error == expected_error.format(url=observation.url)


def test_cli_rejects_missing_explicit_checks_without_creating_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from etl.programs import verify as module

    checks = tmp_path / "missing.json"
    check = Mock()
    monkeypatch.setattr(module, "verify", check)
    assert main(["--checks", str(checks), "--save"]) == 1
    assert "Content check failed" in capsys.readouterr().out
    assert not checks.exists()
    check.assert_not_called()


def test_cli_enumerates_and_previews_then_saves_without_accepting_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from etl.programs import verify as module

    checks = tmp_path / "checks.json"
    checks.write_bytes(Path("data/program_checks.json").read_bytes())
    before = checks.read_bytes()
    catalog_before = CATALOG.read_bytes()
    real_verify = verify

    def offline(programs: list[Program], previous: CheckState) -> CheckState:
        return real_verify(
            programs, previous, get=Mock(return_value=LinkResponse(200, body=b"reviewed"))
        )

    monkeypatch.setattr(module, "verify", offline)
    args = ["--checks", str(checks)]
    assert main(args) == 1
    output = capsys.readouterr().out
    assert "rules.application_url" in output
    assert "https://www.hawaiiablesavings.com/" in output
    assert "REVIEW required" in output
    assert checks.read_bytes() == before
    assert main([*args, "--save"]) == 1
    state = load_checks(checks)
    assert state.observations and not state.reviewed
    assert main([*args, "--save"]) == 1
    assert load_checks(checks).reviewed == {}
    assert CATALOG.read_bytes() == catalog_before


def test_cli_compares_reviewed_hashes_across_saved_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from etl.programs import verify as module
    from etl.programs.verify import save_checks

    program = load_catalog(CATALOG)[0]
    baseline = dict.fromkeys(dict(iter_urls(program)).values(), DIGEST)
    checks = tmp_path / "checks.json"
    save_checks(checks, CheckState(reviewed=baseline))

    def catalog(_path: Path) -> list[Program]:
        return [program]

    monkeypatch.setattr(module, "load_catalog", catalog)
    real_verify = verify
    get = Mock(return_value=LinkResponse(200, body=b"reviewed"))

    def offline(programs: list[Program], previous: CheckState) -> CheckState:
        return real_verify(programs, previous, get=get)

    monkeypatch.setattr(module, "verify", offline)
    args = ["--checks", str(checks), "--save"]
    assert main(args) == 0
    assert "UNCHANGED reviewed content" in capsys.readouterr().out
    get.return_value = LinkResponse(200, body=b"changed")
    for _ in range(2):
        assert main(args) == 1
        assert "REVIEW required" in capsys.readouterr().out
        assert load_checks(checks).reviewed == baseline
        assert all(
            o.sha256 == sha256(b"changed").hexdigest() for o in load_checks(checks).observations
        )


@pytest.mark.parametrize("raw", ["{", '{"version":2}', '{"reviewed":{"bad":"hash"}}'])
def test_cli_rejects_bad_state_without_overwriting(
    tmp_path: Path, raw: str, capsys: pytest.CaptureFixture[str]
) -> None:
    checks = tmp_path / "checks.json"
    checks.write_text(raw)
    assert main(["--checks", str(checks), "--save"]) == 1
    assert "Content check failed" in capsys.readouterr().out
    assert checks.read_text() == raw


def test_new_url_requires_review_even_when_bytes_match_reviewed_content() -> None:
    program = load_catalog(CATALOG)[0]
    baseline = dict.fromkeys(dict(iter_urls(program)).values(), DIGEST)
    program.official_url = type(program.official_url)("https://agency.gov/new-source")
    before = program.model_dump_json()
    state = verify(
        [program],
        CheckState(reviewed=baseline),
        get=Mock(return_value=LinkResponse(200, body=b"reviewed")),
    )
    assert state.needs_review
    assert state.reviewed == baseline
    observation = next(o for o in state.observations if o.field == "official_url")
    assert observation.url == "https://agency.gov/new-source"
    assert observation.sha256 == DIGEST
    # A successful new source never changes the catalog's verification date.
    assert program.model_dump_json() == before


@pytest.mark.parametrize("trusted_redirect", [True, False])
def test_redirects_use_http_trust_policy_and_preserve_original_url(
    trusted_redirect: bool,
) -> None:
    program = load_catalog(CATALOG)[0]
    original = str(program.official_url)
    target = "https://agency.gov/current" if trusted_redirect else "http://127.0.0.1/private"

    def get(url: str, _timeout: float) -> LinkResponse:
        if url == original:
            return LinkResponse(302, location=target)
        assert url != "http://127.0.0.1/private"
        return LinkResponse(200, body=b"reviewed")

    before = program.model_dump_json()
    baseline = dict.fromkeys(dict(iter_urls(program)).values(), DIGEST)
    state = verify([program], CheckState(reviewed=baseline), get=get)
    observation = next(o for o in state.observations if o.field == "official_url")
    assert observation.url == original
    assert observation.sha256 == (DIGEST if trusted_redirect else None)
    assert bool(observation.error) != trusted_redirect
    assert state.needs_review != trusted_redirect
    assert state.reviewed == baseline
    assert program.model_dump_json() == before


def test_one_failed_source_does_not_hide_later_new_urls(program: Program) -> None:
    urls = list(iter_urls(program))
    failed_url = urls[0][1]

    def get(url: str, _timeout: float) -> LinkResponse:
        if url == failed_url:
            raise TimeoutError("offline")
        return LinkResponse(200, body=b"reviewed")

    state = verify([program], CheckState(), get=get)
    assert [(o.field, o.url) for o in state.observations] == urls
    assert state.observations[0].error
    permission = next(
        o for o in state.observations if o.field == "enrichment.media.1.permission.record_url"
    )
    assert permission.sha256 == DIGEST
    assert state.needs_review


def test_default_save_preserves_legacy_checks_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    program: Program,
) -> None:
    from etl.programs import revalidation
    from etl.programs import verify as module

    data = tmp_path / "data"
    data.mkdir()
    legacy_path = data / "program_checks.json"
    legacy_state = revalidation.CheckState(
        reviewed={str(program.official_url): DIGEST},
        observations=[
            revalidation.Observation(
                program_id=program.id,
                field="official_url",
                url=str(program.official_url),
                sha256=DIGEST,
            )
        ],
    )
    revalidation.save_checks(legacy_path, legacy_state)
    legacy_before = legacy_path.read_bytes()
    real_verify = verify

    def offline(programs: list[Program], previous: CheckState) -> CheckState:
        return real_verify(
            programs, previous, get=Mock(return_value=LinkResponse(200, body=b"reviewed"))
        )

    def catalog(_path: Path) -> list[Program]:
        return [program]

    monkeypatch.setattr(module, "load_catalog", catalog)
    monkeypatch.setattr(module, "verify", offline)
    monkeypatch.chdir(tmp_path)
    # Preview works before any extended checks file exists and writes nothing.
    extended_path = data / "program_verification_checks.json"
    assert main([]) == 1
    assert "rules.application_url" in capsys.readouterr().out
    assert not extended_path.exists()
    assert main(["--save"]) == 1
    assert "Saved observations" in capsys.readouterr().out
    extended = load_checks(extended_path)
    assert {"rules.application_url", "enrichment.media.0.url"} <= {
        observation.field for observation in extended.observations
    }
    assert legacy_path.read_bytes() == legacy_before
    assert revalidation.load_checks(legacy_path) == legacy_state
    # A legacy save cannot remove the separately persisted extended observations.
    extended_before = extended_path.read_bytes()
    revalidation.save_checks(legacy_path, legacy_state)
    assert extended_path.read_bytes() == extended_before
    assert main(["--save"]) == 1
    assert load_checks(extended_path) == extended


def test_cli_refuses_to_save_extended_state_over_legacy_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from etl.programs import verify as module

    data = tmp_path / "data"
    data.mkdir()
    legacy = data / "program_checks.json"
    legacy.write_text(CheckState().model_dump_json())
    before = legacy.read_bytes()
    monkeypatch.chdir(tmp_path)
    get = Mock()
    monkeypatch.setattr(module, "verify", get)
    assert main(["--checks", str(legacy), "--save"]) == 1
    assert "legacy checks file" in capsys.readouterr().out
    assert legacy.read_bytes() == before
    get.assert_not_called()
