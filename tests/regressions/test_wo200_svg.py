"""SVG preparation for #145; page integration and its complete-map gate remain step 4."""

import math
import xml.etree.ElementTree as ET
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, sync_playwright
from pydantic import ValidationError

from app.boundary_store import load_boundaries
from etl.boundaries import MultiPolygon, Polygon

Point = tuple[float, float]
NS = "{http://www.w3.org/2000/svg}"


def rectangle(w: float, s: float, e: float, n: float) -> list[Point]:
    return [(w, s), (e, s), (e, n), (w, n), (w, s)]


def polygon(*rings: list[Point]) -> Polygon:
    return Polygon(type="Polygon", coordinates=list(rings))


def render(
    shape: Polygon | MultiPolygon,
    label: str = "House 22",
    islands: tuple[tuple[str, Polygon | MultiPolygon | None], ...] = (),
) -> str:
    from app.svg import render_svg

    return render_svg(shape, label, islands)


def paths(svg: str) -> list[ET.Element]:
    return list(ET.fromstring(svg).iter(f"{NS}path"))


def points(path: ET.Element) -> list[Point]:
    # Parse every token, including any nan/inf; numeric-only regexes hide invalid output.
    tokens = path.attrib["d"].replace(",", " ").split()
    numbers = [float(token) for token in tokens if token not in {"M", "L", "Z"}]
    assert numbers and len(numbers) % 2 == 0
    assert all(math.isfinite(number) for number in numbers)
    result = list(zip(numbers[::2], numbers[1::2], strict=True))
    assert all(16 - 0.001 <= x <= 384.001 and 15.999 <= y <= 284.001 for x, y in result)
    return result


@pytest.mark.parametrize("wide", [True, False])
def test_combined_fit_shared_projection_padding_and_orientation(wide: bool) -> None:
    district = polygon(rectangle(-158, 20, -157, 21))
    outer = rectangle(-160, 19, -154, 22) if wide else rectangle(-159, 15, -156, 25)
    coast = polygon(outer, district.coordinates[0])
    svg = render(district, islands=(("Oʻahu", coast),))
    assert svg == render(district, islands=(("Oʻahu", coast),))
    root = ET.fromstring(svg)
    assert root.attrib["viewBox"].split() == ["0", "0", "400", "300"]
    layers = paths(svg)
    assert [p.attrib["aria-label"] for p in layers] == ["Oʻahu", "House 22"]
    coastline, selected = map(points, layers)
    assert coastline[-5:] == selected  # Multiple identical vertices across both layers.
    all_points = coastline + selected
    xs, ys = zip(*all_points, strict=True)
    assert min(xs) + max(xs) == pytest.approx(400, abs=0.002)
    assert min(ys) + max(ys) == pytest.approx(300, abs=0.002)
    if wide:
        assert (min(xs), max(xs)) == pytest.approx((16, 384), abs=0.002)
    else:
        assert (min(ys), max(ys)) == pytest.approx((16, 284), abs=0.002)
    sw, se, ne = selected[:3]
    assert sw[0] < se[0] and se[1] > ne[1]
    midpoint_lat = (outer[0][1] + outer[2][1]) / 2
    assert (se[0] - sw[0]) / (se[1] - ne[1]) == pytest.approx(
        math.cos(math.radians(midpoint_lat)), abs=0.0001
    )


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("reverse_shell", [False, True])
@pytest.mark.parametrize("reverse_hole", [False, True])
def test_browser_fill_holes_and_disconnected_parts(
    browser: Browser, multi: bool, reverse_shell: bool, reverse_hole: bool
) -> None:
    shell = rectangle(0, 0, 4, 4)[:: -1 if reverse_shell else 1]
    hole = rectangle(1, 1, 3, 3)[:: -1 if reverse_hole else 1]
    rings = [shell, hole]
    shape = (
        MultiPolygon(type="MultiPolygon", coordinates=[rings, [rectangle(6, 0, 8, 4)]])
        if multi
        else polygon(*rings)
    )
    svg = render(shape)
    page = browser.new_page()
    try:
        page.set_content(svg)
        # Chromium's fill hit testing uses the actual inherited SVG fill rule.
        assert page.locator("path").evaluate_all(
            """(elements, domainWidth) => {
            const hit = (x, y) => elements.some(p => p.isPointInFill(new DOMPoint(x, y)));
            const boxes = elements.map(p => p.getBBox());
            const left = Math.min(...boxes.map(b => b.x));
            const right = Math.max(...boxes.map(b => b.x + b.width));
            const top = Math.min(...boxes.map(b => b.y));
            const bottom = Math.max(...boxes.map(b => b.y + b.height));
            const x = v => left + v / domainWidth * (right-left);
            const y = v => bottom - v / 4 * (bottom-top);
            return [hit(x(0.5), y(2)), hit(x(2), y(2)), hit(x(5), y(2)), hit(x(7), y(2))];
        }""",
            8 if multi else 4,
        ) == ([True, False, False, True] if multi else [True, False, False, False])
    finally:
        page.close()
    for path in paths(svg):
        points(path)


@pytest.mark.parametrize(
    "ring",
    [
        [(0, 0), (0, 1), (0, 2), (0, 0)],
        [(0, 0), (1, 0), (2, 0), (0, 0)],
        [(0, 0), (1, 1), (2, 2), (0, 0)],
        rectangle(0, 0, 1e-310, 1e-310),
        rectangle(0, 0, 1e-323, 1e-323),
    ],
)
def test_validated_degenerate_and_tiny_extents_stay_finite(ring: list[Point]) -> None:
    shape = polygon(ring)
    projected = points(paths(render(shape))[0])
    assert len(set(projected)) >= 3


def test_labels_are_escaped_and_accessible_with_unavailable_coastline() -> None:
    label = 'Hawaiʻi "<district>" & Lānaʻi'
    island = 'Oʻahu " onload="alert(1) <script>'
    svg = render(polygon(rectangle(0, 0, 1, 1)), label, ((island, None),))
    root = ET.fromstring(svg)
    assert root.attrib["role"] == "img"
    assert label in root.attrib["aria-label"] and island in root.attrib["aria-label"]
    assert len(paths(svg)) == 1
    assert paths(svg)[0].attrib["aria-label"] == label
    assert "&quot;" in svg and "&lt;" in svg and "&amp;" in svg
    assert all("onload" not in element.attrib for element in root.iter())
    assert not list(root.iter(f"{NS}script"))


@pytest.mark.parametrize("control", [chr(n) for n in (*range(32), 127)])
@pytest.mark.parametrize("island_label", [False, True])
def test_reject_label_controls(control: str, island_label: bool) -> None:
    shape = polygon(rectangle(0, 0, 1, 1))
    with pytest.raises(ValueError, match="control"):
        render(
            shape,
            "district" if island_label else control,
            ((control, None),) if island_label else (),
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 181])
def test_geometry_boundary_rejects_nonfinite_or_out_of_range(bad: float) -> None:
    with pytest.raises(ValidationError):
        polygon([(0, 0), (bad, 0), (0, 1), (0, 0)])


def test_shipped_district_geometries_render_without_loading_or_repair_in_renderer() -> None:
    store = load_boundaries()
    assert len(store.districts) == 76
    for boundary in store.districts.values():
        before = boundary.geometry.model_dump_json()
        svg = render(
            boundary.geometry,
            boundary.id,
            tuple((island.name, island.geometry) for island in boundary.islands),
        )
        assert ET.fromstring(svg).attrib["role"] == "img"
        for path in paths(svg):
            points(path)
        assert boundary.geometry.model_dump_json() == before


def test_ordered_islands_and_multipolygon_coastline_share_the_district_projection() -> None:
    ring = rectangle(-158, 20, -157, 21)
    shape = polygon(ring)
    coast = MultiPolygon(type="MultiPolygon", coordinates=[[ring], [rectangle(-160, 22, -159, 23)]])
    svg = render(shape, islands=(("Kauaʻi", coast), ("Niʻihau", None), ("Oʻahu", shape)))
    layers = paths(svg)
    assert [p.attrib["aria-label"] for p in layers] == ["Kauaʻi", "Oʻahu", "House 22"]
    assert points(layers[0])[:5] == points(layers[1]) == points(layers[2])
    assert "Niʻihau" in ET.fromstring(svg).attrib["aria-label"]
