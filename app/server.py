"""Repocademy web app: FastAPI backend + a static single-page UI."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from repocademy import __version__
from repocademy.ask import ask
from repocademy.builder import build_course
from repocademy.fetch import FetchError, parse_repo_url
from repocademy.llm import get_llm
from repocademy.narrate import narrate_course

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DATA = Path(os.environ.get("REPOCADEMY_DATA", ROOT / "cache"))
SHOWCASE = ROOT / "showcase"

app = FastAPI(title="Repocademy", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

JOBS: dict[str, dict] = {}
BUILD_LOCK = threading.Lock()
LLM_LOCK = threading.Lock()


def course_path(slug: str) -> Path | None:
    if not slug.replace("_", "").replace("-", "").replace(".", "").isalnum():
        return None
    for base in (DATA / "courses", SHOWCASE):
        p = base / slug
        if (p / "course.json").exists():
            return p
    return None


def load_course(slug: str) -> dict:
    p = course_path(slug)
    if p is None:
        raise HTTPException(404, "Course not found")
    return json.loads((p / "course.json").read_text())


def summary(c: dict, showcase: bool) -> dict:
    return {"slug": c["slug"], "repo": c["repo"], "main_lang": c.get("main_lang"), "stats": c.get("stats", {}),
            "chapters": len(c["chapters"]), "questions": sum(len(ch["quiz"]) for ch in c["chapters"]),
            "exercises": sum(len(ch.get("exercises", [])) for ch in c["chapters"]),
            "minutes": sum(ch.get("minutes", 0) for ch in c["chapters"]), "showcase": showcase,
            "narration": c.get("narration", {}), "generated_at": c.get("generated_at"), "build_seconds": c.get("build_seconds")}


class BuildReq(BaseModel):
    url: str = Field(..., max_length=300)
    refresh: bool = False


class AskReq(BaseModel):
    question: str = Field(..., min_length=2, max_length=600)
    history: list[dict] = Field(default_factory=list, max_length=8)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/c/{slug}")
def course_page(slug: str):
    return FileResponse(STATIC / "index.html")


def _warm_up():
    """Load the chat model into memory once, so the first question doesn't pay the model load time."""
    llm = get_llm("chat")
    if llm is None:
        return
    try:
        with LLM_LOCK:
            llm.chat([{"role": "user", "content": "ok"}], max_tokens=1, purpose="chat")
    except Exception:
        pass


def _reset_stale_narration():
    """A restart kills narration threads; let those courses be narrated again instead of 'running' forever."""
    base = DATA / "courses"
    if not base.exists():
        return
    for f in base.glob("*/course.json"):
        try:
            c = json.loads(f.read_text())
        except ValueError:
            continue
        if c.get("narration", {}).get("status") == "running":
            c["narration"]["status"] = "interrupted"
            f.write_text(json.dumps(c))


@app.on_event("startup")
def _startup():
    _reset_stale_narration()
    if os.environ.get("REPOCADEMY_WARMUP", "1") != "0":
        threading.Thread(target=_warm_up, daemon=True).start()


@app.get("/api/health")
def health():
    llm, nar = get_llm("chat"), get_llm("narrate")
    return {"ok": True, "version": __version__, "llm": llm.label if llm else None,
            "narrate_llm": nar.label if nar else None}


@app.get("/api/courses")
def list_courses():
    out, seen = [], set()
    for base, show in ((SHOWCASE, True), (DATA / "courses", False)):
        if not base.exists():
            continue
        for p in sorted(base.iterdir()):
            f = p / "course.json"
            if f.exists() and p.name not in seen:
                try:
                    c = json.loads(f.read_text())
                except ValueError:
                    continue
                seen.add(p.name)
                out.append(summary(c, show))
    return out


@app.get("/api/courses/{slug}")
def get_course(slug: str):
    return load_course(slug)


def _run_build(job_id: str, url: str, refresh: bool):
    job = JOBS[job_id]

    def progress(stage, msg, data=None):
        job["stages"].append({"stage": stage, "msg": msg, "t": round(time.time() - job["t0"], 2), "data": data or {}})

    try:
        with BUILD_LOCK:
            progress("queued", "Starting…")
            c = build_course(url, DATA, progress=progress, refresh=refresh)
        job["slug"] = c["slug"]
        job["status"] = "done"
        if os.environ.get("REPOCADEMY_AUTO_NARRATE", "1") != "0" and c.get("narration", {}).get("status") in (None, "none"):
            threading.Thread(target=_run_narration, args=(c["slug"],), daemon=True).start()
    except FetchError as e:
        job["status"], job["error"] = "error", str(e)
    except Exception as e:  # pragma: no cover - surfaced to the UI
        job["status"], job["error"] = "error", f"Something went wrong while analysing: {type(e).__name__}: {e}"


def _run_narration(slug: str):
    llm = get_llm("narrate")
    p = course_path(slug)
    if llm is None or p is None or not str(p).startswith(str(DATA)):
        return
    course = json.loads((p / "course.json").read_text())
    stamp = course.get("generated_at")

    class Superseded(Exception):
        pass

    def save(c):
        try:  # the course was rebuilt meanwhile: never overwrite the new build with an old one
            if json.loads((p / "course.json").read_text()).get("generated_at") != stamp:
                raise Superseded
        except ValueError:
            pass
        tmp = p / "course.json.tmp"
        tmp.write_text(json.dumps(c))
        tmp.replace(p / "course.json")

    try:
        narrate_course(course, llm, save=save, lock=LLM_LOCK)
    except Superseded:
        pass


@app.post("/api/build")
def build(req: BuildReq):
    try:
        ref = parse_repo_url(req.url)
    except FetchError as e:
        raise HTTPException(400, str(e)) from e
    if not req.refresh:
        p = course_path(ref.slug)
        if p is not None:
            return {"job": None, "slug": ref.slug, "cached": True}
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "running", "stages": [], "slug": ref.slug, "error": None, "t0": time.time(), "url": ref.url}
    threading.Thread(target=_run_build, args=(job_id, ref.url, req.refresh), daemon=True).start()
    return {"job": job_id, "slug": ref.slug, "cached": False}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "Unknown job")
    return {k: v for k, v in j.items() if k != "t0"}


@app.post("/api/courses/{slug}/ask")
def ask_repo(slug: str, req: AskReq):
    course = load_course(slug)
    p = course_path(slug)
    llm = get_llm("chat")

    def gen():
        for ev in ask(course, p, req.question, llm, req.history, lock=LLM_LOCK):
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/courses/{slug}/narrate")
def narrate(slug: str):
    p = course_path(slug)
    if p is None:
        raise HTTPException(404, "Course not found")
    if get_llm("narrate") is None:
        raise HTTPException(409, "No language model available; the course uses templates only.")
    threading.Thread(target=_run_narration, args=(slug,), daemon=True).start()
    return {"started": True}
