from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

from fastapi import BackgroundTasks, UploadFile

from gpx2img import cli, web
from gpx2img.core import Bounds
from gpx2img.osm_source import OSMResolution


def _write_gpx(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="pytest">
  <trk><trkseg>
    <trkpt lat="52.2" lon="21.0"></trkpt>
    <trkpt lat="52.3" lon="21.1"></trkpt>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )


def test_cli_manual_osm_override_skips_auto_resolution(monkeypatch, tmp_path: Path) -> None:
    gpx = tmp_path / "route.gpx"
    _write_gpx(gpx)
    jar = tmp_path / "mkgmap.jar"
    jar.write_bytes(b"jar")
    osm = tmp_path / "manual.osm.pbf"
    osm.write_bytes(b"pbf")

    calls: dict[str, Path | None] = {}

    def fake_compile_tiles(**kwargs):
        calls["osm"] = kwargs["osm_pbf_path"]
        return {"ok": True}

    def fail_resolver(**kwargs):
        raise AssertionError("resolver should not be called with manual override")

    monkeypatch.setattr(cli, "compile_tiles", fake_compile_tiles)
    monkeypatch.setattr(cli, "resolve_osm_source", fail_resolver)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gpx2img",
            "--gpx",
            str(gpx),
            "--osm-pbf",
            str(osm),
            "--mkgmap-jar",
            str(jar),
            "--dry-run",
        ],
    )
    cli.main()
    assert calls["osm"] == osm


def test_cli_auto_mode_resolves_osm_when_no_override(monkeypatch, tmp_path: Path) -> None:
    gpx = tmp_path / "route.gpx"
    _write_gpx(gpx)
    jar = tmp_path / "mkgmap.jar"
    jar.write_bytes(b"jar")
    resolved = tmp_path / "resolved.osm.pbf"
    resolved.write_bytes(b"x" * 2048)
    out = tmp_path / "out"
    out.mkdir()

    def fake_resolve_osm_source(**kwargs):
        return OSMResolution(
            pbf_path=resolved,
            mode="single",
            region_ids=("europe/poland",),
            tile_count=1,
            required_bounds=Bounds(0.0, 0.0, 1.0, 1.0),
        )

    calls: dict[str, Path | None] = {}

    def fake_compile_tiles(**kwargs):
        calls["osm"] = kwargs["osm_pbf_path"]
        return {"ok": True}

    monkeypatch.setattr(cli, "resolve_osm_source", fake_resolve_osm_source)
    monkeypatch.setattr(cli, "compile_tiles", fake_compile_tiles)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gpx2img",
            "--gpx",
            str(gpx),
            "--mkgmap-jar",
            str(jar),
            "--output-dir",
            str(out),
        ],
    )
    cli.main()
    assert calls["osm"] == resolved


def test_web_generate_automatic_mode(monkeypatch, tmp_path: Path) -> None:
    resolved = tmp_path / "resolved.osm.pbf"
    resolved.write_bytes(b"x" * 2048)
    jar = tmp_path / "mkgmap.jar"
    jar.write_bytes(b"jar")

    def fake_resolve_osm_source(**kwargs):
        return OSMResolution(
            pbf_path=resolved,
            mode="single",
            region_ids=("europe/poland",),
            tile_count=3,
            required_bounds=Bounds(0.0, 0.0, 1.0, 1.0),
        )

    def fake_compile_tiles(**kwargs):
        output_dir = kwargs["output_dir"]
        tile = output_dir / "11" / "1"
        tile.mkdir(parents=True, exist_ok=True)
        (tile / "2.img").write_bytes(b"img")
        return {"ok": True}

    monkeypatch.setattr(web, "resolve_osm_source", fake_resolve_osm_source)
    monkeypatch.setattr(web, "compile_tiles", fake_compile_tiles)

    upload = UploadFile(
        filename="route.gpx",
        file=io.BytesIO(
            b"<?xml version='1.0'?><gpx version='1.1'><trk><trkseg><trkpt lat='52.2' lon='21.0'/></trkseg></trk></gpx>",
        ),
    )
    response = asyncio.run(
        web.generate(
            background_tasks=BackgroundTasks(),
            gpx_file=upload,
            osm_pbf=None,
            mkgmap_jar=str(jar),
            buffer_km=1.0,
            overlap_degrees=0.002,
            levels="0:24,1:22,2:20,3:18,4:16",
            overview_levels="3:18,4:16",
            refresh_osm=False,
        ),
    )
    assert response.media_type == "application/zip"
    assert response.path is not None
    with zipfile.ZipFile(response.path) as zf:
        assert "11/1/2.img" in zf.namelist()
