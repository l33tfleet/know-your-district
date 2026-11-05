"""#201: every qualified district reaches the sole renderer with its own artifacts."""

import importlib
import json
import re
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from app.boundary_store import load_boundaries
from app.main import app
from app.page_state import PageState
from etl.boundaries import all_districts

ROOT = Path(__file__).resolve().parents[2]
headline = importlib.import_module("app.sections.10_headline")


def test_all_76_briefs_render_their_qualified_district_and_provenance() -> None:
    store = load_boundaries()
    client = TestClient(app)
    drawings: set[str] = set()
    for chamber in ("house", "senate"):
        raw = json.loads((ROOT / f"data/geo/{chamber}.geojson").read_text())
        shapes = {f["id"]: f["geometry"] for f in raw["features"]}
        for district in all_districts(chamber):
            boundary = store.district(district.fact_key)
            with patch.object(
                headline, "render_svg", return_value="trusted-renderer-output"
            ) as draw:
                context = headline.context(PageState(district=district))
            geometry, label, islands = draw.call_args.args
            assert json.loads(geometry.model_dump_json()) == shapes[district.fact_key]
            assert str(district.district) in label and chamber.title() in label
            assert islands == [(i.name, i.geometry) for i in boundary.islands]
            assert "trusted-renderer-output" in context.values()
            response = client.get(f"/brief/{chamber}/{district.district}")
            assert response.status_code == 200
            match = re.search(r'<header class="brief-headline">.*?</header>', response.text, re.S)
            assert match is not None
            header = ET.fromstring(match[0])
            image = header.find('.//*[@role="img"]')
            assert image is not None
            assert image.attrib["aria-label"] == "; ".join(
                [label, *(i.name for i in boundary.islands)]
            )
            paths = image.findall(".//{http://www.w3.org/2000/svg}path")
            assert len(paths) == 1 + sum(i.geometry is not None for i in boundary.islands)
            drawings.add(str(paths[-1].attrib["d"]))
            for island in boundary.islands:
                assert island.name in "".join(header.itertext())
            source = header.find('.//*[@class="boundary-source"]')
            assert source is not None
            provenance = boundary.attribution.provenance
            assert source.find(f'.//a[@href="{provenance.source_url}"]') is not None
            for value in (provenance.vintage, provenance.method, str(provenance.retrieved_on)):
                assert value in "".join(source.itertext())
            # Keep the attribution's words; explicitly correct Hawaiian spelling in UI.
            assert boundary.attribution.credit.replace("Hawaii", "Hawaiʻi") in "".join(
                source.itertext()
            )
            assert "spelling" in "".join(source.itertext())
    assert len(drawings) == 76
