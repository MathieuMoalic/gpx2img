from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from shapely.geometry import MultiPolygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .core import Bounds, ZOOM, expand_bounds, parse_gpx_bounds, tile_extract_bounds, tile_bounds, tiles_for_bounds

GEOFABRIK_INDEX_URL = "https://download.geofabrik.de/index-v1.json"
DEFAULT_INDEX_TTL_SECONDS = 24 * 3600
DEFAULT_PBF_TTL_SECONDS = 7 * 24 * 3600
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeofabrikRegion:
    id: str
    name: str
    parent: str | None
    pbf_url: str
    geometry: BaseGeometry
    depth: int
    area: float


@dataclass(frozen=True)
class OSMResolution:
    pbf_path: Path
    mode: str
    region_ids: tuple[str, ...]
    tile_count: int
    required_bounds: Bounds


def default_osm_cache_dir() -> Path:
    return Path.home() / ".cache" / "gpx2img" / "osm"


def required_tiles_and_bounds(gpx_path: Path, buffer_km: float, overlap_degrees: float) -> tuple[list[tuple[int, int]], Bounds]:
    route = parse_gpx_bounds(gpx_path)
    buffered = expand_bounds(route, buffer_km)
    tiles = sorted(tiles_for_bounds(buffered, ZOOM))
    if not tiles:
        raise ValueError("No zoom-11 tiles computed from GPX")

    expanded = [tile_extract_bounds(x, y, overlap_degrees, ZOOM) for x, y in tiles]
    required = Bounds(
        min_lat=min(b.min_lat for b in expanded),
        min_lon=min(b.min_lon for b in expanded),
        max_lat=max(b.max_lat for b in expanded),
        max_lon=max(b.max_lon for b in expanded),
    )
    return tiles, required


def required_osm_geometry(gpx_path: Path, buffer_km: float, overlap_degrees: float) -> tuple[BaseGeometry, list[tuple[int, int]], Bounds]:
    tiles, required_bounds = required_tiles_and_bounds(gpx_path, buffer_km, overlap_degrees)
    polys = []
    for x, y in tiles:
        tb = tile_bounds(x, y, ZOOM)
        b = tile_extract_bounds(x, y, overlap_degrees, ZOOM)
        if tb.max_lon >= 179.9 and b.max_lon >= 180.0:
            b = Bounds(b.min_lat, b.min_lon, b.max_lat, 180.0)
        if tb.min_lon <= -179.9 and b.min_lon <= -180.0:
            b = Bounds(b.min_lat, -180.0, b.max_lat, b.max_lon)
        polys.append(box(b.min_lon, b.min_lat, b.max_lon, b.max_lat))
    return unary_union(polys), tiles, required_bounds


class GeofabrikResolver:
    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        index_ttl_seconds: int = DEFAULT_INDEX_TTL_SECONDS,
        pbf_ttl_seconds: int = DEFAULT_PBF_TTL_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache_dir = (cache_dir or default_osm_cache_dir()).expanduser()
        self.index_ttl_seconds = index_ttl_seconds
        self.pbf_ttl_seconds = pbf_ttl_seconds
        self.client = client or httpx.Client(timeout=120.0, follow_redirects=True)

    def resolve(
        self,
        *,
        gpx_path: Path,
        buffer_km: float,
        overlap_degrees: float,
        work_dir: Path,
        refresh_osm: bool = False,
    ) -> OSMResolution:
        required_geom, tiles, required_bounds = required_osm_geometry(gpx_path, buffer_km, overlap_degrees)
        LOGGER.info("GPX requires %d zoom-11 tiles", len(tiles))
        LOGGER.info(
            "Required OSM bounds: %.6f,%.6f -> %.6f,%.6f",
            required_bounds.min_lat,
            required_bounds.min_lon,
            required_bounds.max_lat,
            required_bounds.max_lon,
        )

        regions = self._load_regions(refresh=refresh_osm)
        best_single = self._choose_single_cover(regions, required_geom)
        multi = self._choose_multi_cover(regions, required_geom)
        chosen = self._pick_best_strategy(best_single, multi)

        if len(chosen) == 1:
            region = chosen[0]
            pbf = self._ensure_pbf(region, refresh=refresh_osm)
            LOGGER.info("OSM source: %s", region.id)
            return OSMResolution(
                pbf_path=pbf,
                mode="single",
                region_ids=(region.id,),
                tile_count=len(tiles),
                required_bounds=required_bounds,
            )

        LOGGER.info("Route crosses multiple OSM extracts: %s", ", ".join(r.id for r in chosen))
        extracted_inputs: list[Path] = []
        for region in chosen:
            source = self._ensure_pbf(region, refresh=refresh_osm)
            extracted_inputs.extend(self._crop_to_required_parts(source, required_geom, work_dir, region.id))

        if not extracted_inputs:
            raise RuntimeError("Could not create cropped OSM extracts for merge")
        merged = work_dir / "resolved-source.osm.pbf"
        args = ["osmium", "merge", "--overwrite", "-o", str(merged), *[str(p) for p in extracted_inputs]]
        self._run(args, "Merging source extracts failed")
        self._validate_pbf_file(merged)
        return OSMResolution(
            pbf_path=merged,
            mode="merged",
            region_ids=tuple(r.id for r in chosen),
            tile_count=len(tiles),
            required_bounds=required_bounds,
        )

    def _pick_best_strategy(
        self,
        best_single: GeofabrikRegion | None,
        multi: list[GeofabrikRegion],
    ) -> list[GeofabrikRegion]:
        if best_single is None:
            if not multi:
                raise RuntimeError("No Geofabrik extract could cover required area")
            return multi
        if not multi:
            return [best_single]
        multi_area = sum(r.area for r in multi)
        if len(multi) > 1 and multi_area * 3 < best_single.area:
            return multi
        return [best_single]

    def _index_cache_path(self) -> Path:
        return self.cache_dir / "geofabrik-index-v1.json"

    def _load_regions(self, *, refresh: bool) -> list[GeofabrikRegion]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        index_path = self._index_cache_path()
        if refresh or self._is_stale(index_path, self.index_ttl_seconds):
            LOGGER.info("Downloading Geofabrik index")
            self._download_to(index_path, GEOFABRIK_INDEX_URL, refresh=True)

        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Invalid cached Geofabrik index at {index_path}: {exc}") from exc

        features = raw.get("features")
        if not isinstance(features, list):
            raise RuntimeError("Geofabrik index is missing a valid feature list")

        parsed: dict[str, tuple[str, str | None, str, BaseGeometry]] = {}
        for feature in features:
            props = feature.get("properties") or {}
            region_id = props.get("id")
            if not region_id:
                continue
            urls = props.get("urls") or {}
            pbf_url = urls.get("pbf")
            if not pbf_url:
                continue
            geom_obj = feature.get("geometry")
            if not geom_obj:
                continue
            try:
                geom = shape(geom_obj)
            except Exception:
                continue
            if geom.is_empty:
                continue
            parsed[region_id] = (
                props.get("name") or region_id,
                props.get("parent"),
                pbf_url,
                geom,
            )

        depth_cache: dict[str, int] = {}

        def depth_for(region_id: str) -> int:
            if region_id in depth_cache:
                return depth_cache[region_id]
            parent = parsed.get(region_id, ("", None, "", None))[1]
            if not parent or parent not in parsed:
                depth_cache[region_id] = 0
                return 0
            depth_cache[region_id] = depth_for(parent) + 1
            return depth_cache[region_id]

        regions = [
            GeofabrikRegion(
                id=region_id,
                name=values[0],
                parent=values[1],
                pbf_url=values[2],
                geometry=values[3],
                depth=depth_for(region_id),
                area=values[3].area,
            )
            for region_id, values in parsed.items()
        ]
        if not regions:
            raise RuntimeError("No usable regions found in Geofabrik index")
        return regions

    def _choose_single_cover(self, regions: list[GeofabrikRegion], required_geom: BaseGeometry) -> GeofabrikRegion | None:
        covers = [
            r for r in regions
            if r.geometry.covers(required_geom)
        ]
        if not covers:
            return None
        covers.sort(key=lambda r: (-r.depth, r.area, r.id))
        return covers[0]

    def _choose_multi_cover(self, regions: list[GeofabrikRegion], required_geom: BaseGeometry) -> list[GeofabrikRegion]:
        candidates = [r for r in regions if r.geometry.intersects(required_geom)]
        candidates.sort(key=lambda r: (-r.depth, r.area, r.id))
        selected: list[GeofabrikRegion] = []
        covered = box(0, 0, 1, 1).difference(box(0, 0, 1, 1))
        remaining = required_geom
        tolerance = 1e-12

        while not remaining.is_empty and remaining.area > tolerance:
            best: GeofabrikRegion | None = None
            best_key: tuple[float, int, float, float, str] | None = None
            for region in candidates:
                gain_geom = remaining.intersection(region.geometry)
                gain = gain_geom.area
                if gain <= tolerance:
                    continue
                ratio = gain / max(region.area, tolerance)
                key = (ratio, region.depth, gain, -region.area, region.id)
                if best_key is None or key > best_key:
                    best_key = key
                    best = region
            if best is None:
                break
            selected.append(best)
            covered = unary_union([covered, best.geometry])
            remaining = required_geom.difference(covered)

        if not selected:
            return []

        selected = self._prune_redundant(selected, required_geom)
        union_geom = unary_union([r.geometry for r in selected])
        if not union_geom.covers(required_geom):
            raise RuntimeError("Unable to cover required area with Geofabrik extracts")
        return sorted(selected, key=lambda r: r.id)

    def _prune_redundant(self, selected: list[GeofabrikRegion], required_geom: BaseGeometry) -> list[GeofabrikRegion]:
        pruned = list(selected)
        changed = True
        while changed:
            changed = False
            for region in sorted(pruned, key=lambda r: (-r.area, r.depth, r.id)):
                trial = [r for r in pruned if r.id != region.id]
                if not trial:
                    continue
                union_geom = unary_union([r.geometry for r in trial])
                if union_geom.covers(required_geom):
                    pruned = trial
                    changed = True
                    break
        return pruned

    def _ensure_pbf(self, region: GeofabrikRegion, *, refresh: bool) -> Path:
        parsed = urlparse(region.pbf_url)
        filename = Path(parsed.path).name or f"{region.id.replace('/', '-')}.osm.pbf"
        target = self.cache_dir / "extracts" / Path(region.id) / filename
        if not refresh and target.exists() and not self._is_stale(target, self.pbf_ttl_seconds):
            LOGGER.info("Using cached OSM extract: %s", target)
            return target
        LOGGER.info("Downloading: %s", region.pbf_url)
        self._download_to(target, region.pbf_url, refresh=refresh)
        self._validate_pbf_file(target)
        return target

    def _download_to(self, target: Path, url: str, *, refresh: bool) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + f".part-{os.getpid()}-{int(time.time())}")
        if tmp.exists():
            tmp.unlink()

        try:
            with self.client.stream("GET", url) as response:
                response.raise_for_status()
                with tmp.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        if chunk:
                            handle.write(chunk)
            if tmp.stat().st_size <= 0:
                raise RuntimeError("Downloaded file is empty")
            tmp.replace(target)
        except httpx.HTTPError as exc:
            if tmp.exists():
                tmp.unlink()
            raise RuntimeError(f"Failed to download {url}: {exc}") from exc
        except Exception as exc:
            if tmp.exists():
                tmp.unlink()
            raise RuntimeError(f"Failed to download {url}: {exc}") from exc

    def _validate_pbf_file(self, path: Path) -> None:
        if not path.exists():
            raise RuntimeError(f"Downloaded extract is missing: {path}")
        if path.stat().st_size < 1024:
            raise RuntimeError(f"Downloaded extract looks invalid (too small): {path}")

    def _is_stale(self, path: Path, ttl_seconds: int) -> bool:
        if not path.exists():
            return True
        age = time.time() - path.stat().st_mtime
        return age > ttl_seconds

    def _crop_to_required_parts(self, source: Path, required_geom: BaseGeometry, work_dir: Path, region_id: str) -> list[Path]:
        geoms: list[BaseGeometry]
        if isinstance(required_geom, MultiPolygon):
            geoms = list(required_geom.geoms)
        else:
            geoms = [required_geom]

        out_paths: list[Path] = []
        for i, geom in enumerate(geoms):
            min_lon, min_lat, max_lon, max_lat = geom.bounds
            bbox_arg = f"{min_lon},{min_lat},{max_lon},{max_lat}"
            safe_id = region_id.replace("/", "_")
            cropped = work_dir / f"{safe_id}-{i}.crop.osm.pbf"
            args = [
                "osmium",
                "extract",
                "--overwrite",
                "--bbox",
                bbox_arg,
                "--output",
                str(cropped),
                str(source),
            ]
            self._run(args, f"Cropping extract failed for {region_id}")
            if cropped.exists() and cropped.stat().st_size > 0:
                out_paths.append(cropped)
        return out_paths

    def _run(self, args: list[str], error_prefix: str) -> None:
        try:
            subprocess.run(args, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError("Missing required binary: osmium") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise RuntimeError(f"{error_prefix}: {stderr}") from exc


def resolve_osm_source(
    *,
    gpx_path: Path,
    buffer_km: float,
    overlap_degrees: float,
    work_dir: Path,
    cache_dir: Path | None = None,
    refresh_osm: bool = False,
) -> OSMResolution:
    resolver = GeofabrikResolver(cache_dir=cache_dir)
    return resolver.resolve(
        gpx_path=gpx_path,
        buffer_km=buffer_km,
        overlap_degrees=overlap_degrees,
        work_dir=work_dir,
        refresh_osm=refresh_osm,
    )
