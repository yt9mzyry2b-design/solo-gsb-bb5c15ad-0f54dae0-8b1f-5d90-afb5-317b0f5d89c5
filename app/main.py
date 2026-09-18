"""FastAPI application: Markdown link checker with SQLite persistence."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query

from .checker import check_files, normalize_path, summarize
from .db import Store
from .models import CheckOut, CheckRequest, CheckSummary

DB_PATH = os.environ.get("LINKCHECK_DB", "linkcheck.db")

app = FastAPI(
    title="Markdown Link Checker",
    version="1.0.0",
    description=(
        "Checks a submitted collection of Markdown files for broken cross-file "
        "links: missing targets, duplicate heading anchors, paths escaping the "
        "document root, and self-referencing links. Results are stored in "
        "SQLite and can be retrieved by check ID. No external services required."
    ),
)

_store: Store | None = None


def get_store() -> Store:
    """Lazily create the Store so importing the app has no side effects."""
    global _store
    if _store is None:
        _store = Store(DB_PATH)
    return _store


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/checks", response_model=CheckOut, status_code=201)
def create_check(req: CheckRequest, store: Store = Depends(get_store)) -> CheckOut:
    """Submit a Markdown file collection, run the check, persist and return it."""
    files: dict[str, str] = {}
    errors: list[str] = []
    for f in req.files:
        normalized = normalize_path(f.path)
        if not normalized:
            errors.append(f"path is empty or escapes the document root: {f.path!r}")
        elif normalized in files:
            errors.append(f"duplicate path after normalization: {f.path!r}")
        else:
            files[normalized] = f.content
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    diagnostics = check_files(files)
    check_id = uuid.uuid4().hex[:16]
    created_at = datetime.now(timezone.utc).isoformat()
    summary = summarize(diagnostics)
    store.save_check(check_id, created_at, len(files), summary, diagnostics)
    return CheckOut(
        check_id=check_id,
        created_at=created_at,
        file_count=len(files),
        diagnostic_count=len(diagnostics),
        summary=summary,
        diagnostics=[d.as_dict() for d in diagnostics],
    )


@app.get("/checks", response_model=list[CheckSummary])
def list_checks(
    limit: int = Query(default=50, ge=1, le=500),
    store: Store = Depends(get_store),
) -> list[dict]:
    """List recent checks (summaries only, newest first)."""
    return store.list_checks(limit)


@app.get("/checks/{check_id}", response_model=CheckOut)
def get_check(check_id: str, store: Store = Depends(get_store)) -> dict:
    """Retrieve a stored check result by its ID."""
    result = store.get_check(check_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"check not found: {check_id!r}")
    return result
