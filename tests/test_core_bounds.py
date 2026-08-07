from __future__ import annotations

from pathlib import Path

from gpx2img.core import (
    ZOOM,
    expand_bounds,
    parse_gpx_bounds,
    required_osm_bounds,
    tile_extract_bounds,
    tiles_for_bounds,
)


def _write_gpx(path: Path, points: list[tuple[float, float]]) -> None:
    pts = "\n".join([f'<trkpt lat="{lat}" lon="{lon}"></trkpt>' for lat, lon in points])
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="pytest">
  <trk><name>t</name><trkseg>
    {pts}
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )


def test_antimeridian_gpx_bounds_are_not_worldwide(tmp_path: Path) -> None:
    gpx = tmp_path / "route.gpx"
    _write_gpx(gpx, [(10.0, 179.8), (10.1, -179.8)])

    bounds = parse_gpx_bounds(gpx)
    assert bounds.min_lon > bounds.max_lon
    tiles = tiles_for_bounds(bounds, ZOOM)
    assert 1 <= len(tiles) < 30


def test_required_bounds_cover_all_generated_tile_extracts(tmp_path: Path) -> None:
    gpx = tmp_path / "route.gpx"
    _write_gpx(gpx, [(52.2, 21.0), (52.25, 21.04)])

    required = required_osm_bounds(gpx, buffer_km=1.0, overlap_degrees=0.002)
    buffered = expand_bounds(parse_gpx_bounds(gpx), 1.0)
    route_tiles = sorted(tiles_for_bounds(buffered, ZOOM))
    for x, y in route_tiles:
        tb = tile_extract_bounds(x, y, overlap_degrees=0.002, zoom=ZOOM)
        assert required.min_lat <= tb.min_lat
        assert required.min_lon <= tb.min_lon
        assert required.max_lat >= tb.max_lat
        assert required.max_lon >= tb.max_lon
