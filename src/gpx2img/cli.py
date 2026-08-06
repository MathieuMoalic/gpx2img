from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import compile_tiles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpx2img",
        description="Generate Zepp OS map tiles in 11/x/y.img layout from a GPX route.",
    )
    parser.add_argument("--gpx", type=Path, required=True, help="Path to input GPX file")
    parser.add_argument("--osm-pbf", type=Path, required=True, help="Path to regional OSM PBF")
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
        "--dry-run",
        action="store_true",
        help="Only compute route bounds and tile list without running osmium/mkgmap",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    manifest = compile_tiles(
        gpx_path=args.gpx,
        osm_pbf_path=args.osm_pbf,
        mkgmap_jar=args.mkgmap_jar,
        output_dir=args.output_dir,
        buffer_km=args.buffer_km,
        overlap_degrees=args.overlap_degrees,
        dry_run=args.dry_run,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

