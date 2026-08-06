set shell := ["bash", "-euo", "pipefail", "-c"]

default:
  @just --list

test:
  nix develop -c bash -lc 'PYTHONPATH=src pytest -q'

dry-run gpx osm_pbf mkgmap_jar output_dir="output" buffer_km="1.0" overlap_degrees="0.002":
  nix develop -c bash -lc 'PYTHONPATH=src python -m gpx2img.cli --gpx "{{gpx}}" --osm-pbf "{{osm_pbf}}" --mkgmap-jar "{{mkgmap_jar}}" --output-dir "{{output_dir}}" --buffer-km "{{buffer_km}}" --overlap-degrees "{{overlap_degrees}}" --dry-run'

build gpx osm_pbf mkgmap_jar output_dir="output" buffer_km="1.0" overlap_degrees="0.002":
  nix develop -c bash -lc 'PYTHONPATH=src python -m gpx2img.cli --gpx "{{gpx}}" --osm-pbf "{{osm_pbf}}" --mkgmap-jar "{{mkgmap_jar}}" --output-dir "{{output_dir}}" --buffer-km "{{buffer_km}}" --overlap-degrees "{{overlap_degrees}}"'

build-test:
  nix develop -c bash -lc 'PYTHONPATH=src python -m gpx2img.cli --gpx test.gpx --osm-pbf /home/mat/projects/gpx2img/wielkopolskie-260805.osm.pbf --mkgmap-jar /home/mat/projects/gpx2img/mkgmap-r4924/mkgmap.jar --output-dir output'
