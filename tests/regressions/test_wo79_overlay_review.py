"""WO-79 review: isolate export range rejection and the 99% acceptance boundary."""

import io
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from etl.boundaries import overlay
from tests.regressions.test_wo27_overlay import archive, exported


def test_export_rejects_out_of_range_longitude(tmp_path: Path) -> None:
    path = exported(tmp_path)
    document = json.loads(path.read_text())
    # A simple, closed rectangle that remains valid when projection wraps its
    # longitudes. Only the WGS84 range check should reject this export.
    document["features"][0]["geometry"]["coordinates"] = [
        [[200, 20], [201, 20], [201, 21], [200, 21], [200, 20]]
    ]
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError) as caught:
        overlay.compare_export(
            path, archive(tmp_path, "house"), archive(tmp_path, "senate"), output=io.StringIO()
        )
    message = str(caught.value)
    assert message.startswith("invalid geometry: house:15:001:2022: ")
    assert "Polygon.coordinates.0.0.0\n" in message
    assert "Input should be less than or equal to 180 [type=less_than_equal" in message
    cause = caught.value.__cause__
    assert isinstance(cause, ValidationError)
    assert any(
        error["loc"] == ("Polygon", "coordinates", 0, 0, 0)
        and error["type"] == "less_than_equal"
        and error["input"] == 200
        for error in cause.errors()
    )


@pytest.mark.parametrize(
    ("percentage", "status", "shortfall", "exit_code"),
    [(98.99, "BELOW 99%", 0.01, 1), (99.0, "OK", 0.0, 0), (99.01, "OK", 0.0, 0)],
    ids=["below", "exactly", "above"],
)
def test_threshold_report_shortfall_and_cli_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    percentage: float,
    status: str,
    shortfall: float,
    exit_code: int,
) -> None:
    path = exported(tmp_path)
    house, senate = archive(tmp_path, "house"), archive(tmp_path, "senate")

    # Inject exact overlay results to pin the acceptance decision independently
    # of floating-point projection roundoff. The existing offline fixtures pin IoU.
    def fixed_agreement(left: object, right: object) -> float:
        return percentage

    monkeypatch.setattr(overlay, "_agreement", fixed_agreement)
    output = io.StringIO()
    results = overlay.compare_export(path, house, senate, output=output)
    assert len(results) == 76
    assert all(result.agreement == percentage for result in results)
    for result in results:
        assert result.shortfall == pytest.approx(shortfall, abs=1e-12)
        assert result.shortfall >= 0
    lines = output.getvalue().splitlines()[1:]
    assert len(lines) == 76
    for result, line in zip(results, lines, strict=True):
        assert line.startswith(f"{result.key}: agreement={percentage!r}%; {status}; ")
        assert f"shortfall={result.shortfall!r} pp;" in line

    monkeypatch.setattr(sys, "argv", ["overlay", str(path), str(house), str(senate)])
    with pytest.raises(SystemExit) as caught:
        overlay.main()
    assert caught.value.code == exit_code
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == output.getvalue()
