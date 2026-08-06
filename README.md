# gpx2img

Generate Zepp OS-compatible map tiles for Amazfit watches in this exact layout:

```text
11/<x>/<y>.img
```

The tool takes a GPX route, computes zoom-11 slippy tiles, extracts per-tile OSM data, compiles each tile with mkgmap, and writes `.img` files ready to upload to:

```text
/mnt/data/map/res/scl/11/<x>/<y>.img
```

## Requirements

- Python 3.11+
- `java`
- `osmium` CLI
- `mkgmap` JAR file (for example `mkgmap-r4924/mkgmap.jar`)
- A regional `.osm.pbf` covering your route

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
gpx2img \
  --gpx /path/to/route.gpx \
  --osm-pbf /path/to/region.osm.pbf \
  --mkgmap-jar /path/to/mkgmap.jar \
  --output-dir /path/to/output
```

This creates:

- `output/11/<x>/<y>.img`
- `output/manifest.json`
- `output/manifest.sha256`

## Dry run

Compute only bounds and tiles (no map build):

```bash
gpx2img \
  --gpx /path/to/route.gpx \
  --osm-pbf /path/to/region.osm.pbf \
  --mkgmap-jar /path/to/mkgmap.jar \
  --dry-run
```

## Notes from watch validation

- The folder must be exactly `11/x/y.img` (single `11` level).
- Coordinate order is `x` then `y`.
- Long-route previews need meaningful geometry at far overview levels; this tool sets explicit mkgmap levels to help preserve context.
