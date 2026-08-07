from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import gpxpy

ZOOM = 11
MIN_LAT = -85.05112878
MAX_LAT = 85.05112878
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bounds:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


def normalize_lon(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


def _iter_gpx_points(gpx_path: Path) -> Iterable[tuple[float, float]]:
    with gpx_path.open("r", encoding="utf-8") as handle:
        gpx = gpxpy.parse(handle)

    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                yield point.latitude, point.longitude
    for route in gpx.routes:
        for point in route.points:
            yield point.latitude, point.longitude
    for point in gpx.waypoints:
        yield point.latitude, point.longitude


def _smallest_lon_interval(lons: list[float]) -> tuple[float, float]:
    if not lons:
        raise ValueError("No longitudes provided")
    if len(lons) == 1:
        lon = normalize_lon(lons[0])
        return lon, lon

    values = sorted((lon + 360.0) % 360.0 for lon in lons)
    max_gap = -1.0
    gap_start = values[0]
    gap_end = values[0]
    for i, current in enumerate(values):
        nxt = values[(i + 1) % len(values)]
        if i == len(values) - 1:
            nxt += 360.0
        gap = nxt - current
        if gap > max_gap:
            max_gap = gap
            gap_start = current
            gap_end = nxt

    span_start = gap_end
    span_end = gap_start + 360.0
    if span_end - span_start >= 359.999999:
        return -180.0, 180.0

    min_lon = normalize_lon(span_start)
    max_lon = normalize_lon(span_end)
    return min_lon, max_lon


def _lon_span(bounds: Bounds) -> float:
    if bounds.min_lon <= bounds.max_lon:
        return bounds.max_lon - bounds.min_lon
    return (180.0 - bounds.min_lon) + (bounds.max_lon + 180.0)


def _lon_center(bounds: Bounds) -> float:
    span = _lon_span(bounds)
    start = bounds.min_lon
    center = start + span / 2.0
    return normalize_lon(center)


def _interval_from_center(center: float, span: float) -> tuple[float, float]:
    if span >= 359.999999:
        return -180.0, 180.0
    half = span / 2.0
    start = center - half
    end = center + half
    return normalize_lon(start), normalize_lon(end)


def parse_gpx_bounds(gpx_path: Path) -> Bounds:
    lats: list[float] = []
    lons: list[float] = []
    for lat, lon in _iter_gpx_points(gpx_path):
        lats.append(lat)
        lons.append(lon)

    if not lats or not lons:
        raise ValueError("GPX has no route/track points")

    min_lon, max_lon = _smallest_lon_interval(lons)
    return Bounds(
        min_lat=min(lats),
        min_lon=min_lon,
        max_lat=max(lats),
        max_lon=max_lon,
    )


def expand_bounds(bounds: Bounds, buffer_km: float) -> Bounds:
    if buffer_km < 0:
        raise ValueError("buffer_km must be >= 0")

    lat_pad = buffer_km / 110.574
    mid_lat = (bounds.min_lat + bounds.max_lat) / 2.0
    cos_lat = max(abs(math.cos(math.radians(mid_lat))), 1e-6)
    lon_pad = buffer_km / (111.320 * cos_lat)
    lon_span = min(360.0, _lon_span(bounds) + 2 * lon_pad)
    lon_center = _lon_center(bounds)
    min_lon, max_lon = _interval_from_center(lon_center, lon_span)
    return Bounds(
        min_lat=max(MIN_LAT, bounds.min_lat - lat_pad),
        min_lon=min_lon,
        max_lat=min(MAX_LAT, bounds.max_lat + lat_pad),
        max_lon=max_lon,
    )


def latlon_to_tile(lat: float, lon: float, zoom: int = ZOOM) -> tuple[int, int]:
    lat = max(min(lat, MAX_LAT), MIN_LAT)
    lon = normalize_lon(lon)
    n = 2**zoom
    x = int(math.floor((lon + 180.0) / 360.0 * n))
    x = min(max(x, 0), n - 1)
    lat_rad = math.radians(lat)
    y = int(
        math.floor((1 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * n),
    )
    y = min(max(y, 0), n - 1)
    return x, y


def tile_bounds(x: int, y: int, zoom: int = ZOOM) -> Bounds:
    n = 2**zoom
    min_lon = x / n * 360.0 - 180.0
    max_lon = (x + 1) / n * 360.0 - 180.0
    max_lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    min_lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return Bounds(min_lat=min_lat, min_lon=min_lon, max_lat=max_lat, max_lon=max_lon)


def tile_extract_bounds(x: int, y: int, overlap_degrees: float, zoom: int = ZOOM) -> Bounds:
    tb = tile_bounds(x, y, zoom)
    return Bounds(
        min_lat=max(MIN_LAT, tb.min_lat - overlap_degrees),
        min_lon=max(-180.0, tb.min_lon - overlap_degrees),
        max_lat=min(MAX_LAT, tb.max_lat + overlap_degrees),
        max_lon=min(180.0, tb.max_lon + overlap_degrees),
    )


def required_osm_bounds(gpx_path: Path, buffer_km: float, overlap_degrees: float) -> Bounds:
    route = parse_gpx_bounds(gpx_path)
    buffered = expand_bounds(route, buffer_km)
    tiles = tiles_for_bounds(buffered, ZOOM)
    if not tiles:
        raise ValueError("No tiles generated for GPX bounds")

    bounds = [tile_extract_bounds(x, y, overlap_degrees, ZOOM) for x, y in tiles]
    return Bounds(
        min_lat=min(b.min_lat for b in bounds),
        min_lon=min(b.min_lon for b in bounds),
        max_lat=max(b.max_lat for b in bounds),
        max_lon=max(b.max_lon for b in bounds),
    )


def tiles_for_bounds(bounds: Bounds, zoom: int = ZOOM) -> set[tuple[int, int]]:
    _, y_max = latlon_to_tile(bounds.min_lat, 0.0, zoom)
    _, y_min = latlon_to_tile(bounds.max_lat, 0.0, zoom)
    ys = range(min(y_min, y_max), max(y_min, y_max) + 1)
    n = 2**zoom

    x_min, _ = latlon_to_tile(0.0, bounds.min_lon, zoom)
    x_max, _ = latlon_to_tile(0.0, bounds.max_lon, zoom)
    x_ranges: list[range]
    if bounds.min_lon <= bounds.max_lon:
        x_ranges = [range(min(x_min, x_max), max(x_min, x_max) + 1)]
    else:
        x_ranges = [range(x_min, n), range(0, x_max + 1)]

    return {(x, y) for xr in x_ranges for x in xr for y in ys}


def run_command(args: list[str], *, label: str) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Missing required binary while running {label}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        details = stderr or stdout or f"exit status {exc.returncode}"
        raise RuntimeError(f"{label} failed: {details}") from exc


def require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Missing required binary: {name}")


def mkgmap_command(mkgmap_jar: Path, args: list[str]) -> list[str]:
    classpath_dir = mkgmap_jar.parent
    lib_dir = classpath_dir / "lib"
    if lib_dir.exists():
        classpath = [str(classpath_dir / "mkgmap.jar"), str(lib_dir / "*")]
        return [
            "java",
            "-cp",
            ":".join(classpath),
            "uk.me.parabola.mkgmap.main.Main",
            *args,
        ]
    return ["java", "-jar", str(mkgmap_jar), *args]


def compile_tiles(
    *,
    gpx_path: Path,
    osm_pbf_path: Path | None,
    mkgmap_jar: Path,
    output_dir: Path,
    buffer_km: float,
    overlap_degrees: float,
    dry_run: bool,
    levels: str = "0:24,1:22,2:20,3:18,4:16",
    overview_levels: str = "3:18,4:16",
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    def emit(message: str) -> None:
        if progress is not None:
            progress(message)

    if not dry_run:
        require_binary("java")
        require_binary("osmium")

    if not gpx_path.exists():
        raise FileNotFoundError(f"Missing GPX: {gpx_path}")
    if not mkgmap_jar.exists():
        raise FileNotFoundError(f"Missing mkgmap jar: {mkgmap_jar}")
    if not dry_run:
        if osm_pbf_path is None:
            raise ValueError("osm_pbf_path is required unless --dry-run is used")
        if not osm_pbf_path.exists():
            raise FileNotFoundError(f"Missing OSM PBF: {osm_pbf_path}")

    route_bounds = parse_gpx_bounds(gpx_path)
    buffered = expand_bounds(route_bounds, buffer_km)
    tiles = sorted(tiles_for_bounds(buffered, ZOOM))
    LOGGER.info("Generating %d tiles", len(tiles))
    emit(f"Generating {len(tiles)} tiles")

    tile_root = output_dir / "11"
    tile_root.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    manifest_tiles: list[dict[str, object]] = []
    total = len(tiles)
    for idx, (x, y) in enumerate(tiles, start=1):
        tb = tile_bounds(x, y, ZOOM)
        bbox = tile_extract_bounds(x, y, overlap_degrees, ZOOM)
        bbox_arg = f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat}"
        osm_extract = work_dir / f"{x}_{y}.osm.pbf"
        mapname = f"{x:04d}{y:04d}"
        raw_img = work_dir / f"{mapname}.img"
        final_dir = tile_root / str(x)
        final_img = final_dir / f"{y}.img"

        if not dry_run:
            LOGGER.debug("Generating tile z11/%d/%d", x, y)
            emit(f"[{idx}/{total}] Extracting tile source data for z11/{x}/{y}")
            run_command(
                [
                    "osmium",
                    "extract",
                    "--overwrite",
                    "--bbox",
                    bbox_arg,
                    "--output",
                    str(osm_extract),
                    str(osm_pbf_path),
                ],
                label=f"osmium extract z11/{x}/{y}",
            )
            emit(f"[{idx}/{total}] Running mkgmap for z11/{x}/{y}")
            run_command(
                mkgmap_command(
                    mkgmap_jar,
                    [
                        f"--output-dir={work_dir}",
                        f"--mapname={mapname}",
                        "--description=OSM street map",
                        "--family-id=6324",
                        "--product-id=1",
                        f"--levels={levels}",
                        f"--overview-levels={overview_levels}",
                        str(osm_extract),
                    ],
                ),
                label=f"mkgmap z11/{x}/{y}",
            )
            final_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(raw_img), str(final_img))
            osm_extract.unlink(missing_ok=True)

        manifest_tiles.append(
            {
                "x": x,
                "y": y,
                "bbox": {
                    "min_lat": tb.min_lat,
                    "min_lon": tb.min_lon,
                    "max_lat": tb.max_lat,
                    "max_lon": tb.max_lon,
                },
                "path": str(Path("11") / str(x) / f"{y}.img"),
            },
        )

    manifest = {
        "gpx": str(gpx_path),
        "osm_pbf": str(osm_pbf_path) if osm_pbf_path is not None else None,
        "zoom": ZOOM,
        "buffer_km": buffer_km,
        "overlap_degrees": overlap_degrees,
        "tile_count": len(manifest_tiles),
        "tiles": manifest_tiles,
    }

    if not dry_run:
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        zip_hash_path = output_dir / "manifest.sha256"
        zip_hash_path.write_text(
            f"{hashlib.sha256(manifest_path.read_bytes()).hexdigest()}  manifest.json\n",
            encoding="utf-8",
        )

    return manifest
