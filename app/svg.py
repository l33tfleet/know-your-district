"""Pure SVG rendering of validated district and optional coastline geometry.

Loading, membership, unavailable-coastline status and attribution belong to the
caller (app.boundary_store). Page integration and the complete-map acceptance
check remain step 4 of #145; this module only prepares its drawing layer.
"""

from collections.abc import Callable, Sequence
from html import escape
from math import cos, radians

from etl.boundaries import MultiPolygon, Polygon, Position, Rings


def _polygons(shape: Polygon | MultiPolygon) -> list[Rings]:
    return [shape.coordinates] if isinstance(shape, Polygon) else shape.coordinates


def _label(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("SVG labels must not contain ASCII control characters or DEL")
    if any(0xD800 <= ord(char) <= 0xDFFF or ord(char) in {0xFFFE, 0xFFFF} for char in value):
        raise ValueError("SVG labels must not contain XML-forbidden characters")
    return escape(value, quote=True)


def _projection(shapes: Sequence[Polygon | MultiPolygon]) -> Callable[[Position], Position]:
    positions = [
        p for shape in shapes for rings in _polygons(shape) for ring in rings for p in ring
    ]
    west = min(p[0] for p in positions)
    east = max(p[0] for p in positions)
    south = min(p[1] for p in positions)
    north = max(p[1] for p in positions)
    longitude_factor = cos(radians(south + (north - south) / 2))
    # Normalize before scaling: 368 / a subnormal extent would overflow.
    extent = max(east - west, north - south)
    width = ((east - west) / extent) * longitude_factor
    height = (north - south) / extent
    scale = min(368 / width if width else float("inf"), 268 / height if height else float("inf"))
    left = (400 - width * scale) / 2
    top = (300 - height * scale) / 2

    def project(position: Position) -> Position:
        lon, lat = position
        return (
            left + ((lon - west) / extent) * longitude_factor * scale,
            top + ((north - lat) / extent) * scale,
        )

    return project


def _path(
    shape: Polygon | MultiPolygon,
    label: str,
    project: Callable[[Position], Position],
    fill: str,
) -> str:
    commands: list[str] = []
    for rings in _polygons(shape):
        for ring in rings:
            for index, position in enumerate(ring):
                x, y = project(position)
                commands.append(f"{'M' if index == 0 else 'L'} {x:.6f} {y:.6f}")
            commands.append("Z")
    return (
        f'<path aria-label="{label}" fill="{fill}" fill-rule="evenodd" d="{" ".join(commands)}"/>'
    )


def render_svg(
    geometry: Polygon | MultiPolygon,
    district_label: str,
    islands: Sequence[tuple[str, Polygon | MultiPolygon | None]],
) -> str:
    """Fit all layers together in a north-up, padded 400 by 300 drawing.

    Inputs are structurally validated geometry and ordered island label/shape
    pairs. None explicitly means unavailable coastline; the district still draws.
    Labels are escaped here at the markup boundary; attribution is caller-owned.
    """
    district = _label(district_label)
    layers = [(_label(name), shape) for name, shape in islands]
    project = _projection([geometry, *(shape for _, shape in layers if shape is not None)])
    name = "; ".join([district, *(label for label, _ in layers)])
    paths = [
        _path(shape, label, project, "#e2e8f0") for label, shape in layers if shape is not None
    ]
    paths.append(_path(geometry, district, project, "#2563eb"))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" '
        f'role="img" aria-label="{name}">{"".join(paths)}</svg>'
    )
