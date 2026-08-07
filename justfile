set shell := ["bash", "-euo", "pipefail", "-c"]

default:
  @just --list

test:
  nix develop -c bash -lc 'PYTHONPATH=src python -m pytest -q'

dry-run gpx osm_pbf mkgmap_jar output_dir="output" buffer_km="1.0" overlap_degrees="0.002":
  nix develop -c bash -lc 'PYTHONPATH=src python -m gpx2img.cli --gpx "{{gpx}}" --osm-pbf "{{osm_pbf}}" --mkgmap-jar "{{mkgmap_jar}}" --output-dir "{{output_dir}}" --buffer-km "{{buffer_km}}" --overlap-degrees "{{overlap_degrees}}" --dry-run'

dry-run-auto gpx mkgmap_jar output_dir="output" buffer_km="1.0" overlap_degrees="0.002":
  nix develop -c bash -lc 'PYTHONPATH=src python -m gpx2img.cli --gpx "{{gpx}}" --mkgmap-jar "{{mkgmap_jar}}" --output-dir "{{output_dir}}" --buffer-km "{{buffer_km}}" --overlap-degrees "{{overlap_degrees}}" --dry-run'

build gpx osm_pbf mkgmap_jar output_dir="output" buffer_km="1.0" overlap_degrees="0.002":
  nix develop -c bash -lc 'PYTHONPATH=src python -m gpx2img.cli --gpx "{{gpx}}" --osm-pbf "{{osm_pbf}}" --mkgmap-jar "{{mkgmap_jar}}" --output-dir "{{output_dir}}" --buffer-km "{{buffer_km}}" --overlap-degrees "{{overlap_degrees}}"'

build-auto gpx mkgmap_jar output_dir="output" buffer_km="1.0" overlap_degrees="0.002":
  nix develop -c bash -lc 'PYTHONPATH=src python -m gpx2img.cli --gpx "{{gpx}}" --mkgmap-jar "{{mkgmap_jar}}" --output-dir "{{output_dir}}" --buffer-km "{{buffer_km}}" --overlap-degrees "{{overlap_degrees}}"'

serve host="0.0.0.0" port="8000":
  nix develop -c bash -lc 'PYTHONPATH=src python -m uvicorn gpx2img.web:app --host {{host}} --port {{port}} --reload --reload-dir src'

build-test:
  nix develop -c bash -lc 'PYTHONPATH=src python -m gpx2img.cli --gpx "${GPX2IMG_TEST_GPX:?Set GPX2IMG_TEST_GPX in .env}" --mkgmap-jar "${GPX2IMG_MKGMAP_JAR:?Set GPX2IMG_MKGMAP_JAR in .env}" --output-dir "${GPX2IMG_OUTPUT_DIR:-output}"'

update-server:
    ssh homeserver "cd /home/mat/nix; nix flake update gpx2img; up"
