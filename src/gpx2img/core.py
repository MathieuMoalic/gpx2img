from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import gpxpy

ZOOM = 11


@dataclass(frozen=True)
class Bounds:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


def parse_gpx_bounds(gpx_path: Path) -> Bounds:
    with gpx_path.open("r", encoding="utf-8") as handle:
        gpx = gpxpy.parse(handle)

    lats: list[float] = []
    lons: list[float] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                lats.append(point.latitude)
                lons.append(point.longitude)
    for route in gpx.routes:
        for point in route.points:
            lats.append(point.latitude)
            lons.append(point.longitude)
    for point in gpx.waypoints:
        lats.append(point.latitude)
        lons.append(point.longitude)

    if not lats or not lons:
        raise ValueError("GPX has no route/track points")

    return Bounds(
        min_lat=min(lats),
        min_lon=min(lons),
        max_lat=max(lats),
        max_lon=max(lons),
    )


def expand_bounds(bounds: Bounds, buffer_km: float) -> Bounds:
    if buffer_km < 0:
        raise ValueError("buffer_km must be >= 0")

    lat_pad = buffer_km / 110.574
    mid_lat = (bounds.min_lat + bounds.max_lat) / 2.0
    cos_lat = max(abs(math.cos(math.radians(mid_lat))), 1e-6)
    lon_pad = buffer_km / (111.320 * cos_lat)
    return Bounds(
        min_lat=max(-85.05112878, bounds.min_lat - lat_pad),
        min_lon=max(-180.0, bounds.min_lon - lon_pad),
        max_lat=min(85.05112878, bounds.max_lat + lat_pad),
        max_lon=min(180.0, bounds.max_lon + lon_pad),
    )


def latlon_to_tile(lat: float, lon: float, zoom: int = ZOOM) -> tuple[int, int]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    lon = ((lon + 180.0) % 360.0) - 180.0
    n = 2**zoom
    x = int(math.floor((lon + 180.0) / 360.0 * n))
    lat_rad = math.radians(lat)
    y = int(
        math.floor((1 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * n),
    )
    return x, y


def tile_bounds(x: int, y: int, zoom: int = ZOOM) -> Bounds:
    n = 2**zoom
    min_lon = x / n * 360.0 - 180.0
    max_lon = (x + 1) / n * 360.0 - 180.0
    max_lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    min_lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return Bounds(min_lat=min_lat, min_lon=min_lon, max_lat=max_lat, max_lon=max_lon)


def tiles_for_bounds(bounds: Bounds, zoom: int = ZOOM) -> set[tuple[int, int]]:
    x_min, y_max = latlon_to_tile(bounds.min_lat, bounds.min_lon, zoom)
    x_max, y_min = latlon_to_tile(bounds.max_lat, bounds.max_lon, zoom)
    xs = range(min(x_min, x_max), max(x_min, x_max) + 1)
    ys = range(min(y_min, y_max), max(y_min, y_max) + 1)
    return {(x, y) for x in xs for y in ys}


def run_command(args: list[str]) -> None:
    subprocess.run(args, check=True)


def require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Missing required binary: {name}")


def compile_tiles(
    *,
    gpx_path: Path,
    osm_pbf_path: Path,
    mkgmap_jar: Path,
    output_dir: Path,
    buffer_km: float,
    overlap_degrees: float,
    dry_run: bool,
    levels: str = "0:24,1:22,2:20,3:18,4:16",
    overview_levels: str = "3:18,4:16",
) -> dict[str, object]:
    if not dry_run:
        require_binary("java")
        require_binary("osmium")

    if not gpx_path.exists():
        raise FileNotFoundError(f"Missing GPX: {gpx_path}")
    if not osm_pbf_path.exists():
        raise FileNotFoundError(f"Missing OSM PBF: {osm_pbf_path}")
    if not mkgmap_jar.exists():
        raise FileNotFoundError(f"Missing mkgmap jar: {mkgmap_jar}")

    route_bounds = parse_gpx_bounds(gpx_path)
    buffered = expand_bounds(route_bounds, buffer_km)
    tiles = sorted(tiles_for_bounds(buffered, ZOOM))

    tile_root = output_dir / "11"
    tile_root.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    manifest_tiles: list[dict[str, object]] = []
    for x, y in tiles:
        tb = tile_bounds(x, y, ZOOM)
        bbox = Bounds(
            min_lat=tb.min_lat - overlap_degrees,
            min_lon=tb.min_lon - overlap_degrees,
            max_lat=tb.max_lat + overlap_degrees,
            max_lon=tb.max_lon + overlap_degrees,
        )
        bbox_arg = f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat}"
        osm_extract = work_dir / f"{x}_{y}.osm.pbf"
        mapname = f"{x:04d}{y:04d}"
        raw_img = work_dir / f"{mapname}.img"
        final_dir = tile_root / str(x)
        final_img = final_dir / f"{y}.img"

        if not dry_run:
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
            )
            run_command(
                [
                    "java",
                    "-jar",
                    str(mkgmap_jar),
                    f"--output-dir={work_dir}",
                    f"--mapname={mapname}",
                    "--description=OSM street map",
                    "--family-id=6324",
                    "--product-id=1",
                    f"--levels={levels}",
                    f"--overview-levels={overview_levels}",
                    str(osm_extract),
                ],
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
        "osm_pbf": str(osm_pbf_path),
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
