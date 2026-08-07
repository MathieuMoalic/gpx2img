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
- Internet access for automatic Geofabrik downloads (unless you provide `--osm-pbf`)

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Or with Nix + uv:

```bash
nix develop
uv sync --extra dev
```

With direnv + .env defaults:

```bash
direnv allow
```

Expected `.env` keys:

```bash
GPX2IMG_TEST_GPX=/absolute/path/to/test.gpx
GPX2IMG_MKGMAP_JAR=/absolute/path/to/mkgmap.jar
GPX2IMG_OUTPUT_DIR=output
```

## Usage

```bash
gpx2img \
  --gpx /path/to/route.gpx \
  --mkgmap-jar /path/to/mkgmap.jar \
  --output-dir /path/to/output
```

By default, `gpx2img` automatically:
1. computes the required zoom-11 tile coverage (including overlap),
2. resolves matching Geofabrik extract(s),
3. downloads/reuses cached `.osm.pbf` sources,
4. and builds tiles.

Default cache location:

```text
~/.cache/gpx2img/osm/
```

Optional flags:

```bash
--osm-cache /custom/cache/path
--refresh-osm
```

Manual offline/custom override is still supported:

```bash
gpx2img \
  --gpx /path/to/route.gpx \
  --osm-pbf /path/to/your.osm.pbf \
  --mkgmap-jar /path/to/mkgmap.jar
```

With `just` (recommended, runs through `nix develop`):

```bash
just build-auto /path/to/route.gpx /path/to/mkgmap.jar
```

Manual override variant:

```bash
just build /path/to/route.gpx /path/to/region.osm.pbf /path/to/mkgmap.jar
```

Run the web app (requires `mkgmap.jar`, `osmium`, and network access for automatic downloads unless using manual override):

```bash
just serve 0.0.0.0 8000
```

Open:

`http://localhost:8000`

Use the form:
- upload GPX
- set `mkgmap_jar`
- optional: set `osm_pbf` as a manual override
- click **Generate and download ZIP**

Optional defaults for the Web UI/API (manual override path):

```bash
export GPX2IMG_OSM_PBF=/absolute/path/to/region.osm.pbf
export GPX2IMG_MKGMAP_JAR=/absolute/path/to/mkgmap.jar
just serve
```

If you use `.env` + `direnv`, those fields are auto-prefilled in the Web UI.

Then POST multipart/form-data to /generate with fields:
- gpx_file: file
- osm_pbf: optional absolute path to OSM PBF on server
- mkgmap_jar: absolute path to mkgmap.jar on server
- buffer_km, overlap_degrees, levels, overview_levels (optional)
- refresh_osm (optional boolean)

This creates:

- `output/11/<x>/<y>.img`
- `output/manifest.json`
- `output/manifest.sha256`

## Dry run

Compute only bounds and tiles (no map build):

```bash
gpx2img \
  --gpx /path/to/route.gpx \
  --mkgmap-jar /path/to/mkgmap.jar \
  --dry-run
```

With `just`:

```bash
just dry-run-auto /path/to/route.gpx /path/to/mkgmap.jar
```

## Automatic OSM source behavior

- Uses `https://download.geofabrik.de/index-v1.json` with local caching.
- Reuses downloaded extracts by default; use `--refresh-osm` to force refresh.
- Resolves the source area from generated zoom-11 tile extents plus overlap (not raw GPX bbox).
- For cross-border routes, can resolve multiple extracts, crop, then merge with `osmium`.
- Validates download failures and avoids broken cache entries by writing to temporary files before atomic rename.

## Notes from watch validation

- The folder must be exactly `11/x/y.img` (single `11` level).
- Coordinate order is `x` then `y`.
- Long-route previews need meaningful geometry at far overview levels; this tool sets explicit mkgmap levels to help preserve context.
