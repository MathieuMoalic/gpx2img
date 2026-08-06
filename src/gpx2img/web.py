from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .core import compile_tiles

app = FastAPI(title="gpx2img web")

# Environment-backed defaults are preferred; caller can also pass osm_pbf and mkgmap_jar paths.


@app.post("/generate")
async def generate(
    gpx_file: UploadFile = File(...),
    osm_pbf: Optional[str] = Form(None),
    mkgmap_jar: Optional[str] = Form(None),
    buffer_km: float = Form(1.0),
    overlap_degrees: float = Form(0.002),
    levels: str = Form("0:24,1:22,2:20,3:18,4:16"),
    overview_levels: str = Form("3:18,4:16"),
):
    # Save GPX to a temp dir and run compile_tiles in a threadpool to avoid blocking the event loop.
    td = Path(tempfile.mkdtemp(prefix="gpx2img-"))
    try:
        gpx_path = td / "upload.gpx"
        with gpx_path.open("wb") as f:
            f.write(await gpx_file.read())

        if osm_pbf is None or mkgmap_jar is None:
            raise HTTPException(status_code=400, detail="osm_pbf and mkgmap_jar form fields are required")

        output_dir = td / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        def work():
            return compile_tiles(
                gpx_path=gpx_path,
                osm_pbf_path=Path(osm_pbf),
                mkgmap_jar=Path(mkgmap_jar),
                output_dir=output_dir,
                buffer_km=buffer_km,
                overlap_degrees=overlap_degrees,
                dry_run=False,
                levels=levels,
                overview_levels=overview_levels,
            )

        manifest = await run_in_threadpool(work)

        # Zip the 11 folder and return
        eleven = output_dir / "11"
        if not eleven.exists():
            raise HTTPException(status_code=500, detail="No 11 directory produced")

        zip_path = td / "11.zip"
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=output_dir, base_dir="11")

        return FileResponse(str(zip_path), media_type="application/zip", filename="11.zip")
    finally:
        # Do not remove output immediately to allow the response to be served; cleanup could be added later.
        pass
