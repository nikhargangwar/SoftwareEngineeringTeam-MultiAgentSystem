import contextlib
import io
import json
import queue
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from SoftwareEngineerTeam import run_swe_team


app = FastAPI(title="AI SWE Team API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist" / "ai-swe-team-console"


class RunRequest(BaseModel):
    repo: str = Field(..., min_length=3, description="GitHub repo in owner/name format")
    issue_id: int = Field(..., gt=0)


RUNS: dict[str, dict[str, Any]] = {}

STAGES = [
    {"step": 1, "name": "Issue Reader Agent", "description": "Fetches the GitHub issue, labels, and comments."},
    {"step": 2, "name": "Issue Analyzer Agent", "description": "Understands the task, severity, keywords, and likely approach."},
    {"step": 3, "name": "Repo Explorer Agent", "description": "Reads the repository tree and filters code files."},
    {"step": 4, "name": "File Locator Agent", "description": "Ranks the files most likely to need changes."},
    {"step": 5, "name": "Code Reader Agent", "description": "Loads source content for the selected files."},
    {"step": 6, "name": "Solution Designer Agent", "description": "Designs the implementation plan before code is written."},
    {"step": 7, "name": "Code Writer Agent", "description": "Generates complete updated file contents."},
    {"step": 8, "name": "Code Reviewer Agent", "description": "Reviews generated changes and keeps approved files."},
    {"step": 9, "name": "Test Writer Agent", "description": "Creates or updates tests for the fix."},
    {"step": 10, "name": "Git Commit Agent", "description": "Creates a branch and commits approved changes."},
    {"step": 11, "name": "PR Creator Agent", "description": "Opens a professional pull request and links the issue."},
]

STEP_RE = re.compile(r"STEP\s+(\d+):\s+(.+)", re.IGNORECASE)


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def public_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {}

    results = result.get("results", {})
    return {
        "success": result.get("success", False),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "pr": results.get("pr", {}),
        "analysis": results.get("analysis", {}),
        "files_changed": results.get("commit", {}).get("files_committed", []),
        "errors": result.get("errors", {}),
    }


class QueueWriter(io.TextIOBase):
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._buffer = ""

    def writable(self):
        return True

    def write(self, text: str):
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            publish_log(self.run_id, line.strip())
        return len(text)

    def flush(self):
        if self._buffer.strip():
            publish_log(self.run_id, self._buffer.strip())
        self._buffer = ""


def publish(run_id: str, event: str, data: dict[str, Any]):
    run = RUNS.get(run_id)
    if run:
        run["queue"].put({"event": event, "data": data})


def publish_log(run_id: str, line: str):
    if not line:
        return
    if "GITHUB_TOKEN" in line:
        return

    step_match = STEP_RE.search(line)
    if step_match:
        step = int(step_match.group(1))
        publish(run_id, "stage", {"step": step, "status": "running", "message": line})
        return

    publish(run_id, "log", {"line": line, "timestamp": time.time()})


def execute_run(run_id: str, repo: str, issue_id: int):
    RUNS[run_id]["status"] = "running"
    publish(run_id, "started", {"run_id": run_id, "repo": repo, "issue_id": issue_id, "stages": STAGES})

    try:
        writer = QueueWriter(run_id)
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            result = run_swe_team(issue_id, repo_full_name=repo)
        writer.flush()

        summary = public_summary(result)
        RUNS[run_id]["result"] = summary
        RUNS[run_id]["status"] = "completed" if summary.get("success") else "failed"
        publish(run_id, "completed", summary)
    except Exception as exc:
        RUNS[run_id]["status"] = "failed"
        publish(run_id, "failed", {"success": False, "errors": {"fatal": str(exc)}})
    finally:
        publish(run_id, "close", {"status": RUNS[run_id]["status"]})


@app.get("/api/stages")
def stages():
    return {"stages": STAGES}


@app.post("/api/runs")
def create_run(payload: RunRequest):
    if "/" not in payload.repo:
        raise HTTPException(status_code=422, detail="Repo must use owner/name format.")
    if any(run["status"] in {"queued", "running"} for run in RUNS.values()):
        raise HTTPException(status_code=409, detail="Another SWE team run is already active.")

    run_id = str(uuid.uuid4())
    RUNS[run_id] = {
        "status": "queued",
        "queue": queue.Queue(),
        "result": None,
        "repo": payload.repo,
        "issue_id": payload.issue_id,
    }

    thread = threading.Thread(
        target=execute_run,
        args=(run_id, payload.repo, payload.issue_id),
        daemon=True,
    )
    RUNS[run_id]["thread"] = thread
    thread.start()

    return {"run_id": run_id, "status": "queued"}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {
        "run_id": run_id,
        "status": run["status"],
        "repo": run["repo"],
        "issue_id": run["issue_id"],
        "result": run["result"],
    }


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str):
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")

    def stream():
        yield sse("connected", {"run_id": run_id, "status": run["status"]})
        while True:
            try:
                item = run["queue"].get(timeout=15)
            except queue.Empty:
                yield sse("heartbeat", {"timestamp": time.time()})
                continue

            yield sse(item["event"], item["data"])
            if item["event"] == "close":
                break

    return StreamingResponse(stream(), media_type="text/event-stream")


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=assets_dir),
            name="frontend-assets",
        )

    app.mount(
        "/",
        StaticFiles(directory=FRONTEND_DIST, html=True),
        name="frontend",
    )
