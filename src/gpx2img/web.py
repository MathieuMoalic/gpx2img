from __future__ import annotations

import os
import shutil
import tempfile
from html import escape
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.concurrency import run_in_threadpool

from .core import compile_tiles

app = FastAPI(title="gpx2img web")

DEFAULT_OSM_PBF = os.getenv("GPX2IMG_OSM_PBF", "")
DEFAULT_MKGMAP_JAR = os.getenv("GPX2IMG_MKGMAP_JAR", "")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    default_osm = escape(DEFAULT_OSM_PBF)
    default_mkgmap = escape(DEFAULT_MKGMAP_JAR)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>gpx2img</title>
  <style>
    body {{ max-width: 760px; margin: 2rem auto; font-family: system-ui, sans-serif; line-height: 1.4; }}
    form {{ display: grid; gap: .8rem; }}
    label {{ display: grid; gap: .25rem; }}
    input, button {{ padding: .55rem; font: inherit; }}
    button {{ cursor: pointer; }}
    .muted {{ color: #555; font-size: .95rem; }}
    .hint {{ color: #666; font-size: .88rem; }}
    #status {{ white-space: pre-wrap; }}
  </style>
</head>
<body>
  <h1>GPX to Zepp 11 folder</h1>
  <p class="muted">Upload a GPX and download a ZIP containing <code>11/&lt;x&gt;/&lt;y&gt;.img</code>.</p>

  <form id="f">
    <label>GPX file
      <input name="gpx_file" type="file" accept=".gpx" required />
      <span class="hint">Route file you want to convert. All GPX points are used to compute tile coverage.</span>
    </label>
    <label>OSM PBF path (on server)
      <input name="osm_pbf" value="{default_osm}" placeholder="/absolute/path/to/region.osm.pbf" required />
      <span class="hint">Absolute path on this machine to the regional <code>.osm.pbf</code> source data used to build map tiles.</span>
    </label>
    <label>mkgmap.jar path (on server)
      <input name="mkgmap_jar" value="{default_mkgmap}" placeholder="/absolute/path/to/mkgmap.jar" required />
      <span class="hint">Absolute path on this machine to <code>mkgmap.jar</code>, the compiler that generates Garmin <code>.img</code> tiles.</span>
    </label>
    <label>Buffer km
      <input name="buffer_km" type="number" step="0.1" value="1.0" />
      <span class="hint">Extra distance added around GPX bounds before tile selection. Helps include nearby context and avoid edge misses.</span>
    </label>
    <label>Overlap degrees
      <input name="overlap_degrees" type="number" step="0.0001" value="0.002" />
      <span class="hint">Per-tile extraction overlap in lat/lon degrees to reduce clipping of ways at tile borders.</span>
    </label>
    <label>Levels
      <input name="levels" value="0:24,1:22,2:20,3:18,4:16" />
      <span class="hint">Passed to mkgmap <code>--levels</code>. Controls detail by level (lower number = more detail).</span>
    </label>
    <label>Overview levels
      <input name="overview_levels" value="3:18,4:16" />
      <span class="hint">Passed to mkgmap <code>--overview-levels</code>. Important for long-route far-zoom previews on watch.</span>
    </label>
    <button type="submit">Generate and download ZIP</button>
  </form>

  <p id="status" class="muted"></p>

  <script>
    const form = document.getElementById('f');
    const status = document.getElementById('status');
    form.addEventListener('submit', async (e) => {{
      e.preventDefault();
      status.textContent = 'Generating map...';
      const fd = new FormData(form);
      try {{
        const res = await fetch('/generate', {{ method: 'POST', body: fd }});
        if (!res.ok) {{
          status.textContent = await res.text();
          return;
        }}
        const blob = await res.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = '11.zip';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
        status.textContent = 'Done. Download started.';
      }} catch (err) {{
        status.textContent = String(err);
      }}
    }});
  </script>
</body>
</html>"""


@app.post("/generate")
async def generate(
    background_tasks: BackgroundTasks,
    gpx_file: UploadFile = File(...),
    osm_pbf: Optional[str] = Form(None),
    mkgmap_jar: Optional[str] = Form(None),
    buffer_km: float = Form(1.0),
    overlap_degrees: float = Form(0.002),
    levels: str = Form("0:24,1:22,2:20,3:18,4:16"),
    overview_levels: str = Form("3:18,4:16"),
):
    td = Path(tempfile.mkdtemp(prefix="gpx2img-"))
    try:
        gpx_path = td / "upload.gpx"
        with gpx_path.open("wb") as f:
            f.write(await gpx_file.read())

        osm_pbf = osm_pbf or DEFAULT_OSM_PBF
        mkgmap_jar = mkgmap_jar or DEFAULT_MKGMAP_JAR
        if not osm_pbf or not mkgmap_jar:
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

        await run_in_threadpool(work)

        eleven = output_dir / "11"
        if not eleven.exists():
            raise HTTPException(status_code=500, detail="No 11 directory produced")

        zip_path = td / "11.zip"
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=output_dir, base_dir="11")

        background_tasks.add_task(shutil.rmtree, td, True)
        return FileResponse(str(zip_path), media_type="application/zip", filename="11.zip")
    except Exception:
        shutil.rmtree(td, ignore_errors=True)
        raise
