from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from shapely.geometry import box

from gpx2img.osm_source import GeofabrikRegion, GeofabrikResolver


class _StreamResponse:
    def __init__(self, *, status_code: int = 200, chunks: list[bytes] | None = None, error: Exception | None = None) -> None:
        self.status_code = status_code
        self._chunks = chunks or []
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad response", request=httpx.Request("GET", "https://example.com"), response=httpx.Response(self.status_code))

    def iter_bytes(self):
        if self._error is not None:
            raise self._error
        yield from self._chunks


class _FakeClient:
    def __init__(self, mapping: dict[str, _StreamResponse]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def stream(self, method: str, url: str):
        self.calls.append(url)
        resp = self.mapping.get(url)
        if resp is None:
            return _StreamResponse(status_code=404)
        return resp


def _region(region_id: str, parent: str | None, geom, depth: int, area: float | None = None) -> GeofabrikRegion:
    return GeofabrikRegion(
        id=region_id,
        name=region_id,
        parent=parent,
        pbf_url=f"https://download.geofabrik.de/{region_id}-latest.osm.pbf",
        geometry=geom,
        depth=depth,
        area=geom.area if area is None else area,
    )


def test_single_country_selection() -> None:
    required = box(20.8, 52.1, 21.2, 52.4)
    regions = [
        _region("europe", None, box(-20, 30, 40, 72), 0),
        _region("europe/poland", "europe", box(14, 49, 24, 55), 1),
    ]
    resolver = GeofabrikResolver(cache_dir=Path("/tmp/non-used"))
    chosen = resolver._choose_single_cover(regions, required)
    assert chosen is not None
    assert chosen.id == "europe/poland"


def test_subregion_is_preferred_when_it_covers() -> None:
    required = box(11.1, 48.0, 11.4, 48.3)
    regions = [
        _region("europe/germany", "europe", box(5, 47, 16, 55), 1),
        _region("europe/germany/bayern", "europe/germany", box(8.9, 47.2, 13.9, 50.7), 2),
    ]
    resolver = GeofabrikResolver(cache_dir=Path("/tmp/non-used"))
    chosen = resolver._choose_single_cover(regions, required)
    assert chosen is not None
    assert chosen.id == "europe/germany/bayern"


def test_boundary_case_prefers_parent_single_extract() -> None:
    required = box(10.9, 49.7, 13.1, 50.1)
    regions = [
        _region("europe/germany", "europe", box(5, 47, 16, 55), 1),
        _region("europe/germany/bayern", "europe/germany", box(8.9, 47.2, 13.0, 50.7), 2),
        _region("europe/germany/sachsen", "europe/germany", box(12.0, 50.0, 15.1, 51.8), 2),
    ]
    resolver = GeofabrikResolver(cache_dir=Path("/tmp/non-used"))
    chosen = resolver._choose_single_cover(regions, required)
    assert chosen is not None
    assert chosen.id == "europe/germany"


def test_cross_country_prefers_multi_over_huge_single() -> None:
    required = box(13.9, 50.8, 15.5, 51.4)
    regions = [
        _region("europe", None, box(-20, 30, 40, 72), 0),
        _region("europe/germany", "europe", box(5, 47, 14.8, 55), 1),
        _region("europe/poland", "europe", box(14, 49, 24, 55), 1),
    ]
    resolver = GeofabrikResolver(cache_dir=Path("/tmp/non-used"))
    single = resolver._choose_single_cover(regions, required)
    multi = resolver._choose_multi_cover(regions, required)
    picked = resolver._pick_best_strategy(single, multi)
    assert {r.id for r in picked} == {"europe/germany", "europe/poland"}


def test_pruning_removes_parent_child_duplication() -> None:
    required = box(10.0, 48.0, 10.5, 48.5)
    parent = _region("europe/germany", "europe", box(5, 47, 16, 55), 1)
    child = _region("europe/germany/bayern", "europe/germany", box(8.9, 47.2, 13.9, 50.7), 2)
    resolver = GeofabrikResolver(cache_dir=Path("/tmp/non-used"))
    pruned = resolver._prune_redundant([parent, child], required)
    assert [r.id for r in pruned] == ["europe/germany/bayern"]


def test_cached_download_reuse(tmp_path: Path) -> None:
    payload = b"x" * 2048
    client = _FakeClient({"https://example.com/a.osm.pbf": _StreamResponse(chunks=[payload])})
    resolver = GeofabrikResolver(cache_dir=tmp_path, client=client, pbf_ttl_seconds=999999)
    region = GeofabrikRegion("a", "a", None, "https://example.com/a.osm.pbf", box(0, 0, 1, 1), 0, 1)
    first = resolver._ensure_pbf(region, refresh=False)
    second = resolver._ensure_pbf(region, refresh=False)
    assert first == second
    assert client.calls.count("https://example.com/a.osm.pbf") == 1


def test_refresh_forces_redownload(tmp_path: Path) -> None:
    client = _FakeClient({"https://example.com/a.osm.pbf": _StreamResponse(chunks=[b"x" * 2048])})
    resolver = GeofabrikResolver(cache_dir=tmp_path, client=client, pbf_ttl_seconds=999999)
    region = GeofabrikRegion("a", "a", None, "https://example.com/a.osm.pbf", box(0, 0, 1, 1), 0, 1)
    resolver._ensure_pbf(region, refresh=False)
    resolver._ensure_pbf(region, refresh=True)
    assert client.calls.count("https://example.com/a.osm.pbf") == 2


def test_failed_download_raises_clear_error(tmp_path: Path) -> None:
    client = _FakeClient({"https://example.com/a.osm.pbf": _StreamResponse(status_code=500)})
    resolver = GeofabrikResolver(cache_dir=tmp_path, client=client)
    with pytest.raises(RuntimeError, match="Failed to download"):
        resolver._download_to(tmp_path / "x.osm.pbf", "https://example.com/a.osm.pbf", refresh=False)


def test_interrupted_download_does_not_leave_target(tmp_path: Path) -> None:
    client = _FakeClient({"https://example.com/a.osm.pbf": _StreamResponse(error=httpx.ReadTimeout("timeout"))})
    resolver = GeofabrikResolver(cache_dir=tmp_path, client=client)
    target = tmp_path / "x.osm.pbf"
    with pytest.raises(Exception):
        resolver._download_to(target, "https://example.com/a.osm.pbf", refresh=False)
    assert not target.exists()
    assert not list(tmp_path.glob("*.part-*"))


def test_load_regions_from_index_cache(tmp_path: Path) -> None:
    index = {
        "features": [
            {
                "properties": {"id": "europe", "name": "Europe", "parent": None, "urls": {"pbf": "https://example.com/europe.osm.pbf"}},
                "geometry": {"type": "Polygon", "coordinates": [[[-20, 30], [40, 30], [40, 72], [-20, 72], [-20, 30]]]},
            },
            {
                "properties": {"id": "europe/poland", "name": "Poland", "parent": "europe", "urls": {"pbf": "https://example.com/poland.osm.pbf"}},
                "geometry": {"type": "Polygon", "coordinates": [[[14, 49], [24, 49], [24, 55], [14, 55], [14, 49]]]},
            },
        ],
    }
    cache_file = tmp_path / "geofabrik-index-v1.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(index), encoding="utf-8")

    resolver = GeofabrikResolver(cache_dir=tmp_path, client=_FakeClient({}))
    regions = resolver._load_regions(refresh=False)
    by_id = {r.id: r for r in regions}
    assert by_id["europe/poland"].depth > by_id["europe"].depth
