"""WO #52: the offline catalog loader's YAML dependency must ship in the lock."""

import tomllib
from pathlib import Path


def test_yaml_dependency_is_locked_for_runtime() -> None:
    root = Path(__file__).resolve().parents[2]
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    packages = {package["name"]: package for package in lock["package"]}
    assert "pyyaml" in packages, "The catalog YAML dependency is missing from uv.lock"
    project = packages["know-your-district"]
    assert {"name": "pyyaml"} in project["dependencies"]
    assert any(
        dependency["name"] == "pyyaml" for dependency in project["metadata"]["requires-dist"]
    )
