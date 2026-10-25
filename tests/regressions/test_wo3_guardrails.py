"""WO #3: mechanical guard rails that let later work orders merge unattended.

- pyright runs in strict mode;
- a blanket `# type: ignore` or bare `# noqa` fails ruff (PGH003, PGH004);
- the import-linter contract fails if one section module imports another,
  while sections may still import app core.
"""

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BIN = Path(sys.executable).parent


def tool(name: str) -> str:
    found = shutil.which(name, path=str(BIN)) or shutil.which(name)
    assert found, f"{name} is not installed; run `uv sync`"
    return found


def pyproject() -> dict[str, Any]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_pyright_is_strict() -> None:
    assert pyproject()["tool"]["pyright"]["typeCheckingMode"] == "strict"


def test_makefile_check_runs_every_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for needle in ("ruff check", "ruff format --check", "pyright", "lint-imports", "pytest"):
        assert needle in makefile, needle
    assert "evals" in makefile
    assert "smoke" in makefile


def ruff(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    target = tmp_path / "planted.py"
    target.write_text(source, encoding="utf-8")
    return subprocess.run(
        [
            tool("ruff"),
            "check",
            "--no-cache",
            "--config",
            str(ROOT / "pyproject.toml"),
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_file_passes_ruff(tmp_path: Path) -> None:
    result = ruff(tmp_path, "X: int = 1\n")
    assert result.returncode == 0, result.stdout


def test_blanket_type_ignore_fails_ruff(tmp_path: Path) -> None:
    result = ruff(tmp_path, 'X: int = "a"  # type: ignore\n')
    assert result.returncode != 0
    assert "PGH003" in result.stdout


def test_bare_noqa_fails_ruff(tmp_path: Path) -> None:
    result = ruff(tmp_path, "import os  # noqa\n")
    assert result.returncode != 0
    assert "PGH004" in result.stdout


def test_okina_is_not_flagged_as_confusable(tmp_path: Path) -> None:
    result = ruff(tmp_path, 'PLACE = "Kauaʻi"  # Hawaiʻi county\n')
    assert result.returncode == 0, result.stdout


def lint_imports(tmp_path: Path, sections: dict[str, str]) -> subprocess.CompletedProcess[str]:
    shutil.copytree(ROOT / "app", tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__"))
    for name, source in sections.items():
        (tmp_path / "app" / "sections" / f"{name}.py").write_text(source, encoding="utf-8")
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    return subprocess.run(
        [tool("lint-imports"), "--config", "pyproject.toml", "--no-cache"],
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path), "PATH": str(BIN)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_sections_may_import_core(tmp_path: Path) -> None:
    result = lint_imports(
        tmp_path,
        {
            "alpha": "from app import main\n",
            "beta": "import app.main\n",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_section_importing_another_section_fails(tmp_path: Path) -> None:
    result = lint_imports(
        tmp_path,
        {
            "alpha": "X = 1\n",
            "beta": "from app.sections import alpha\n",
        },
    )
    assert result.returncode != 0, result.stdout
    assert "BROKEN" in result.stdout or "broken" in result.stdout
