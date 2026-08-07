from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from threading import Lock
from typing import Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .core import compile_tiles
from .osm_source import default_osm_cache_dir, resolve_osm_source

app = FastAPI(title="gpx2img web")

DEFAULT_OSM_PBF = os.getenv("GPX2IMG_OSM_PBF", "")
DEFAULT_MKGMAP_JAR = os.getenv("GPX2IMG_MKGMAP_JAR", "")


@dataclass
class JobState:
    status: str
    temp_dir: Path
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    zip_path: Path | None = None
    created_at: float = field(default_factory=time.time)


JOBS: dict[str, JobState] = {}
JOBS_LOCK = Lock()


def _append_log(job_id: str, message: str) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is not None:
            job.logs.append(message)


def _perform_generation(
    *,
    gpx_path: Path,
    output_dir: Path,
    mkgmap_jar: Path,
    buffer_km: float,
    overlap_degrees: float,
    levels: str,
    overview_levels: str,
    refresh_osm: bool,
    progress,
) -> None:
    work_dir = output_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    progress("Resolving OSM source")
    resolved_osm = resolve_osm_source(
        gpx_path=gpx_path,
        buffer_km=buffer_km,
        overlap_degrees=overlap_degrees,
        work_dir=work_dir,
        cache_dir=default_osm_cache_dir(),
        refresh_osm=refresh_osm,
        progress=progress,
    ).pbf_path

    progress("Compiling tiles with mkgmap")
    compile_tiles(
        gpx_path=gpx_path,
        osm_pbf_path=resolved_osm,
        mkgmap_jar=mkgmap_jar,
        output_dir=output_dir,
        buffer_km=buffer_km,
        overlap_degrees=overlap_degrees,
        dry_run=False,
        levels=levels,
        overview_levels=overview_levels,
        progress=progress,
    )


def _run_job(
    *,
    job_id: str,
    gpx_path: Path,
    temp_dir: Path,
    mkgmap_jar: Path,
    buffer_km: float,
    overlap_degrees: float,
    levels: str,
    overview_levels: str,
    refresh_osm: bool,
) -> None:
    output_dir = temp_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        with JOBS_LOCK:
            JOBS[job_id].status = "running"
        _append_log(job_id, "Job started")
        _perform_generation(
            gpx_path=gpx_path,
            output_dir=output_dir,
            mkgmap_jar=mkgmap_jar,
            buffer_km=buffer_km,
            overlap_degrees=overlap_degrees,
            levels=levels,
            overview_levels=overview_levels,
            refresh_osm=refresh_osm,
            progress=lambda msg: _append_log(job_id, msg),
        )
        zip_path = temp_dir / "11.zip"
        _append_log(job_id, "Packaging ZIP archive")
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=output_dir, base_dir="11")
        with JOBS_LOCK:
            job = JOBS[job_id]
            job.status = "done"
            job.zip_path = zip_path
        _append_log(job_id, "Done")
    except Exception as exc:
        with JOBS_LOCK:
            job = JOBS[job_id]
            job.status = "error"
            job.error = str(exc)
        _append_log(job_id, f"Error: {exc}")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>gpx2img</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect x='4' y='8' width='56' height='48' rx='4' fill='%23e6f4ea' stroke='%232f6f44' stroke-width='3'/%3E%3Cpath d='M18 10v44M34 10v44M50 10v44' stroke='%2394c7a0' stroke-width='3'/%3E%3Cpath d='M14 42c8-12 14-18 22-20 6-2 10 1 14 5' fill='none' stroke='%231b5e20' stroke-width='4' stroke-linecap='round'/%3E%3Ccircle cx='14' cy='42' r='3' fill='%23d32f2f'/%3E%3Ccircle cx='50' cy='27' r='3' fill='%23d32f2f'/%3E%3C/svg%3E" />
  <style>
    body { max-width: 760px; margin: 2rem auto; font-family: system-ui, sans-serif; line-height: 1.4; }
    form { display: grid; gap: .8rem; }
    label { display: grid; gap: .25rem; }
    input, button { padding: .55rem; font: inherit; }
    button { cursor: pointer; }
    .muted { color: #555; font-size: .95rem; }
    .hint { color: #666; font-size: .88rem; }
    #status { white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: #f7f7f7; padding: .8rem; border-radius: .4rem; min-height: 6rem; }
  </style>
</head>
<body>
  <h1>GPX to Zepp 11 folder</h1>
  <p class="muted">Upload a GPX and download a ZIP containing <code>11/&lt;x&gt;/&lt;y&gt;.img</code>.</p>
  <p class="muted">OSM data source: <strong>Automatic (Geofabrik)</strong></p>

  <form id="f">
    <label>GPX file
      <input name="gpx_file" type="file" accept=".gpx" required />
      <span class="hint">Route file you want to convert.</span>
    </label>
    <label>Buffer km
      <input name="buffer_km" type="number" step="0.1" value="1.0" />
    </label>
    <label>Overlap degrees
      <input name="overlap_degrees" type="number" step="0.0001" value="0.002" />
    </label>
    <label>Levels
      <input name="levels" value="0:24,1:22,2:20,3:18,4:16" />
    </label>
    <label>Overview levels
      <input name="overview_levels" value="3:18,4:16" />
    </label>
    <label>
      <input name="refresh_osm" type="checkbox" value="true" />
      Refresh OSM cache before generation
    </label>
    <button type="submit">Generate and download ZIP</button>
  </form>

  <h3>Progress</h3>
  <p id="status" class="muted">Idle.</p>

  <script>
    const form = document.getElementById('f');
    const status = document.getElementById('status');
    let pollTimer = null;

    function setStatus(lines) {
      status.textContent = lines.length ? lines.join('\\n') : 'Working...';
    }

    async function pollJob(jobId) {
      const res = await fetch(`/jobs/${jobId}`);
      const data = await res.json();
      setStatus(data.logs || []);
      if (data.status === 'done') {
        clearInterval(pollTimer);
        const dl = await fetch(`/jobs/${jobId}/download`);
        const blob = await dl.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = '11.zip';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
      }
      if (data.status === 'error') {
        clearInterval(pollTimer);
      }
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (pollTimer) {
        clearInterval(pollTimer);
      }
      setStatus(['Uploading GPX...', 'Queueing generation job...']);
      const fd = new FormData(form);
      try {
        const res = await fetch('/generate-job', { method: 'POST', body: fd });
        if (!res.ok) {
          status.textContent = await res.text();
          return;
        }
        const payload = await res.json();
        pollTimer = setInterval(() => pollJob(payload.job_id), 1000);
        await pollJob(payload.job_id);
      } catch (err) {
        status.textContent = String(err);
      }
    });
  </script>
</body>
</html>"""


@app.post("/generate")
async def generate(
    background_tasks: BackgroundTasks,
    gpx_file: UploadFile = File(...),
    mkgmap_jar: Optional[str] = Form(None),
    buffer_km: float = Form(1.0),
    overlap_degrees: float = Form(0.002),
    levels: str = Form("0:24,1:22,2:20,3:18,4:16"),
    overview_levels: str = Form("3:18,4:16"),
    refresh_osm: bool = Form(False),
):
    td = Path(tempfile.mkdtemp(prefix="gpx2img-"))
    try:
        gpx_path = td / "upload.gpx"
        with gpx_path.open("wb") as f:
            f.write(await gpx_file.read())

        jar = Path((mkgmap_jar or DEFAULT_MKGMAP_JAR).strip())
        if not str(jar):
            raise HTTPException(status_code=400, detail="mkgmap_jar form field is required")

        output_dir = td / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        def work():
            _perform_generation(
                gpx_path=gpx_path,
                output_dir=output_dir,
                mkgmap_jar=jar,
                buffer_km=buffer_km,
                overlap_degrees=overlap_degrees,
                levels=levels,
                overview_levels=overview_levels,
                refresh_osm=refresh_osm,
                progress=lambda _msg: None,
            )

        await run_in_threadpool(work)

        eleven = output_dir / "11"
        if not eleven.exists():
            raise HTTPException(status_code=500, detail="No 11 directory produced")

        zip_path = td / "11.zip"
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=output_dir, base_dir="11")
        background_tasks.add_task(shutil.rmtree, td, True)
        return FileResponse(str(zip_path), media_type="application/zip", filename="11.zip")
    except HTTPException:
        shutil.rmtree(td, ignore_errors=True)
        raise
    except RuntimeError as exc:
        shutil.rmtree(td, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        shutil.rmtree(td, ignore_errors=True)
        raise


@app.post("/generate-job")
async def generate_job(
    background_tasks: BackgroundTasks,
    gpx_file: UploadFile = File(...),
    buffer_km: float = Form(1.0),
    overlap_degrees: float = Form(0.002),
    levels: str = Form("0:24,1:22,2:20,3:18,4:16"),
    overview_levels: str = Form("3:18,4:16"),
    refresh_osm: bool = Form(False),
):
    if not DEFAULT_MKGMAP_JAR:
        raise HTTPException(status_code=400, detail="Server is missing GPX2IMG_MKGMAP_JAR")

    td = Path(tempfile.mkdtemp(prefix="gpx2img-job-"))
    gpx_path = td / "upload.gpx"
    with gpx_path.open("wb") as f:
        f.write(await gpx_file.read())

    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = JobState(status="queued", temp_dir=td, logs=["Upload received", "Job queued"])

    background_tasks.add_task(
        _run_job,
        job_id=job_id,
        gpx_path=gpx_path,
        temp_dir=td,
        mkgmap_jar=Path(DEFAULT_MKGMAP_JAR),
        buffer_km=buffer_km,
        overlap_degrees=overlap_degrees,
        levels=levels,
        overview_levels=overview_levels,
        refresh_osm=refresh_osm,
    )
    return JSONResponse({"job_id": job_id})


@app.get("/jobs/{job_id}")
async def job_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job id")
        return JSONResponse(
            {
                "job_id": job_id,
                "status": job.status,
                "logs": job.logs,
                "error": job.error,
                "ready": job.status == "done" and job.zip_path is not None,
            },
        )


@app.get("/jobs/{job_id}/download")
async def job_download(background_tasks: BackgroundTasks, job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job id")
        if job.status == "error":
            raise HTTPException(status_code=409, detail=job.error or "Job failed")
        if job.status != "done" or job.zip_path is None:
            raise HTTPException(status_code=409, detail="Job is not finished yet")
        zip_path = job.zip_path
        temp_dir = job.temp_dir
    background_tasks.add_task(shutil.rmtree, temp_dir, True)
    return FileResponse(str(zip_path), media_type="application/zip", filename="11.zip")


def serve_main() -> None:
    parser = argparse.ArgumentParser(
        prog="gpx2img-web",
        description="Run gpx2img web server.",
    )
    parser.add_argument("--host", default=os.getenv("GPX2IMG_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("GPX2IMG_PORT", "8000")))
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (development only).",
    )
    args = parser.parse_args()
    uvicorn.run("gpx2img.web:app", host=args.host, port=args.port, reload=args.reload)
