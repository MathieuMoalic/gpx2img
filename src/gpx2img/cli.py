from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .core import compile_tiles
from .osm_source import default_osm_cache_dir, resolve_osm_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpx2img",
        description="Generate Zepp OS map tiles in 11/x/y.img layout from a GPX route.",
    )
    parser.add_argument("--gpx", type=Path, required=True, help="Path to input GPX file")
    parser.add_argument(
        "--osm-pbf",
        type=Path,
        required=False,
        help="Optional manual OSM PBF override. If omitted, data is resolved from Geofabrik automatically.",
    )
    parser.add_argument("--mkgmap-jar", type=Path, required=True, help="Path to mkgmap jar")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Output directory that will contain 11/<x>/<y>.img",
    )
    parser.add_argument(
        "--buffer-km",
        type=float,
        default=1.0,
        help="Extra route buffer in kilometers before tile selection (default: 1.0)",
    )
    parser.add_argument(
        "--overlap-degrees",
        type=float,
        default=0.002,
        help="Per-tile extraction overlap in degrees to avoid edge clipping (default: 0.002)",
    )
    parser.add_argument(
        "--levels",
        type=str,
        default="0:24,1:22,2:20,3:18,4:16",
        help="mkgmap --levels value (default: '0:24,1:22,2:20,3:18,4:16')",
    )
    parser.add_argument(
        "--overview-levels",
        type=str,
        default="3:18,4:16",
        help="mkgmap --overview-levels value (default: '3:18,4:16')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only compute route bounds and tile list without running osmium/mkgmap",
    )
    parser.add_argument(
        "--osm-cache",
        type=Path,
        default=default_osm_cache_dir(),
        help="OSM cache directory for Geofabrik index/extracts (default: ~/.cache/gpx2img/osm)",
    )
    parser.add_argument(
        "--refresh-osm",
        action="store_true",
        help="Refresh Geofabrik index and source extract downloads instead of using cached files",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = build_parser()
    args = parser.parse_args()

    resolved_osm: Path | None = args.osm_pbf
    if resolved_osm is None and not args.dry_run:
        work_dir = args.output_dir / "_work"
        work_dir.mkdir(parents=True, exist_ok=True)
        resolution = resolve_osm_source(
            gpx_path=args.gpx,
            buffer_km=args.buffer_km,
            overlap_degrees=args.overlap_degrees,
            work_dir=work_dir,
            cache_dir=args.osm_cache,
            refresh_osm=args.refresh_osm,
        )
        resolved_osm = resolution.pbf_path

    manifest = compile_tiles(
        gpx_path=args.gpx,
        osm_pbf_path=resolved_osm,
        mkgmap_jar=args.mkgmap_jar,
        output_dir=args.output_dir,
        buffer_km=args.buffer_km,
        overlap_degrees=args.overlap_degrees,
        dry_run=args.dry_run,
        levels=args.levels,
        overview_levels=args.overview_levels,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
