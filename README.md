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
GPX2IMG_OSM_PBF=/absolute/path/to/region.osm.pbf
GPX2IMG_MKGMAP_JAR=/absolute/path/to/mkgmap.jar
GPX2IMG_OUTPUT_DIR=output
```

## Usage

```bash
gpx2img \
  --gpx /path/to/route.gpx \
  --osm-pbf /path/to/region.osm.pbf \
  --mkgmap-jar /path/to/mkgmap.jar \
  --output-dir /path/to/output
```

With `just` (recommended, runs through `nix develop`):

```bash
just build /path/to/route.gpx /path/to/region.osm.pbf /path/to/mkgmap.jar
```

Run the web app (requires mkgmap and osm PBF accessible to the server):

```bash
just serve 0.0.0.0 8000
```

Open:

`http://localhost:8000`

Use the form:
- upload GPX
- set `osm_pbf` and `mkgmap_jar` paths (or set env vars below)
- click **Generate and download ZIP**

Optional defaults for the Web UI/API:

```bash
export GPX2IMG_OSM_PBF=/absolute/path/to/region.osm.pbf
export GPX2IMG_MKGMAP_JAR=/absolute/path/to/mkgmap.jar
just serve
```

If you use `.env` + `direnv`, those fields are auto-prefilled in the Web UI.

Then POST multipart/form-data to /generate with fields:
- gpx_file: file
- osm_pbf: absolute path to OSM PBF on server
- mkgmap_jar: absolute path to mkgmap.jar on server
- buffer_km, overlap_degrees, levels, overview_levels (optional)

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

With `just`:

```bash
just dry-run /path/to/route.gpx /path/to/region.osm.pbf /path/to/mkgmap.jar
```

## Notes from watch validation

- The folder must be exactly `11/x/y.img` (single `11` level).
- Coordinate order is `x` then `y`.
- Long-route previews need meaningful geometry at far overview levels; this tool sets explicit mkgmap levels to help preserve context.
