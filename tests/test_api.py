import pytest
from fastapi.testclient import TestClient

from app.db import Store
from app.main import app, get_store

FILES = {
    "README.md": (
        "# Project\n"
        "\n"
        "See the [guide](docs/guide.md#usage) or [missing page](docs/nope.md).\n"
        "[escape](../../outside.md)\n"
        "[loop](README.md)\n"
    ),
    "docs/guide.md": (
        "# Guide\n"
        "\n"
        "## Usage\n"
        "## Usage\n"
        "\n"
        "Back to [README](../README.md#project).\n"
        "[unknown anchor](#nope)\n"
        "[self](#usage-1)\n"
    ),
}

EXPECTED_DIAGNOSTICS = {
    ("missing_target", "README.md", 3, "docs/nope.md"),
    ("path_escape", "README.md", 4, "../../outside.md"),
    ("self_reference", "README.md", 5, "README.md"),
    ("duplicate_anchor", "docs/guide.md", 4, "#usage"),
    ("missing_target", "docs/guide.md", 7, "#nope"),
    ("self_reference", "docs/guide.md", 8, "#usage-1"),
}


@pytest.fixture()
def client(tmp_path):
    store = Store(str(tmp_path / "checks.db"))
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as c:
        yield c, store
    app.dependency_overrides.clear()


def post_files(client, files=FILES):
    payload = {"files": [{"path": p, "content": c} for p, c in files.items()]}
    return client.post("/checks", json=payload)


def test_create_check_returns_full_result(client):
    c, _ = client
    resp = post_files(c)
    assert resp.status_code == 201
    body = resp.json()
    assert body["file_count"] == 2
    assert body["diagnostic_count"] == 6
    assert body["summary"] == {
        "missing_target": 2,
        "duplicate_anchor": 1,
        "path_escape": 1,
        "self_reference": 2,
    }
    got = {(d["type"], d["source"], d["line"], d["link"]) for d in body["diagnostics"]}
    assert got == EXPECTED_DIAGNOSTICS
    for d in body["diagnostics"]:
        assert d["message"]
        assert isinstance(d["line"], int) and d["line"] >= 1


def test_get_check_by_id_roundtrip(client):
    c, _ = client
    body = post_files(c).json()
    resp = c.get(f"/checks/{body['check_id']}")
    assert resp.status_code == 200
    assert resp.json() == body


def test_get_unknown_check_returns_404(client):
    c, _ = client
    resp = c.get("/checks/does-not-exist")
    assert resp.status_code == 404


def test_results_persist_across_store_instances(client, tmp_path):
    c, _ = client
    check_id = post_files(c).json()["check_id"]
    reopened = Store(str(tmp_path / "checks.db"))  # same file, new instance
    result = reopened.get_check(check_id)
    assert result is not None
    assert result["diagnostic_count"] == 6


def test_list_checks(client):
    c, _ = client
    check_id = post_files(c).json()["check_id"]
    resp = c.get("/checks")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["check_id"] == check_id
    assert items[0]["diagnostic_count"] == 6
    assert "diagnostics" not in items[0]


def test_path_escaping_root_is_rejected(client):
    c, _ = client
    resp = post_files(c, {"../evil.md": "# x\n"})
    assert resp.status_code == 422


def test_duplicate_paths_after_normalization_are_rejected(client):
    c, _ = client
    resp = c.post("/checks", json={"files": [
        {"path": "a.md", "content": "# A\n"},
        {"path": "./a.md", "content": "# A\n"},
    ]})
    assert resp.status_code == 422


def test_empty_file_collection_is_rejected(client):
    c, _ = client
    resp = c.post("/checks", json={"files": []})
    assert resp.status_code == 422


def test_clean_collection_has_no_diagnostics(client):
    c, _ = client
    resp = post_files(c, {
        "README.md": "# Home\n\n[guide](docs/guide.md#usage)\n",
        "docs/guide.md": "# Guide\n\n## Usage\n",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["diagnostic_count"] == 0
    assert body["diagnostics"] == []


def test_health(client):
    c, _ = client
    assert c.get("/health").json() == {"status": "ok"}


def test_suggest_true_attaches_and_persists_suggestions(client):
    c, _ = client
    resp = c.post("/checks?suggest=true", json={
        "files": [{"path": p, "content": content} for p, content in FILES.items()]
    })
    assert resp.status_code == 201
    body = resp.json()
    by_link = {(d["source"], d["link"]): d for d in body["diagnostics"]}

    missing_file = by_link[("README.md", "docs/nope.md")]["suggestion"]
    assert missing_file["status"] == "auto_suggestion"
    best = missing_file["candidates"][0]
    assert best["path"] == "docs/guide.md"
    assert best["anchor"] is None
    assert best["score"] == best["path_distance"] + best["anchor_distance"] == 1

    missing_anchor = by_link[("docs/guide.md", "#nope")]["suggestion"]
    assert missing_anchor["status"] == "ambiguous"
    assert len(missing_anchor["candidates"]) <= 3

    for d in body["diagnostics"]:
        if d["type"] != "missing_target":
            assert d["suggestion"] is None

    # suggestions are persisted: GET returns the identical payload
    assert c.get(f"/checks/{body['check_id']}").json() == body


def test_suggest_defaults_to_off(client):
    c, _ = client
    body = post_files(c).json()
    assert all(d["suggestion"] is None for d in body["diagnostics"])


def test_suggest_explicit_false_overrides_env(client, monkeypatch):
    monkeypatch.setenv("LINKCHECK_SUGGEST", "1")
    c, _ = client
    body = c.post("/checks?suggest=false", json={
        "files": [{"path": p, "content": content} for p, content in FILES.items()]
    }).json()
    assert all(d["suggestion"] is None for d in body["diagnostics"])


def test_suggest_default_via_env(client, monkeypatch):
    monkeypatch.setenv("LINKCHECK_SUGGEST", "1")
    c, _ = client
    body = post_files(c).json()
    missing = [d for d in body["diagnostics"] if d["type"] == "missing_target"]
    assert missing
    assert all(d["suggestion"] is not None for d in missing)


def test_store_migrates_pre_suggestion_schema(tmp_path):
    import sqlite3

    from app.checker import check_files
    from app.suggest import attach_suggestions

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE checks (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
            file_count INTEGER NOT NULL, diagnostic_count INTEGER NOT NULL,
            summary TEXT NOT NULL
        );
        CREATE TABLE diagnostics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_id TEXT NOT NULL, type TEXT NOT NULL, source TEXT NOT NULL,
            line INTEGER NOT NULL, link TEXT NOT NULL, resolved TEXT,
            message TEXT NOT NULL
        );
    """)
    conn.close()

    store = Store(str(db))  # opening migrates the old schema
    files = {"a.md": "# A\n\n[gone](docs/gne.md)\n", "docs/guide.md": "# Guide\n"}
    diagnostics = check_files(files)
    attach_suggestions(files, diagnostics)
    store.save_check("c1", "2026-09-18T00:00:00+00:00", len(files),
                     {"missing_target": 1}, diagnostics)
    result = store.get_check("c1")
    assert result["diagnostics"][0]["suggestion"]["status"] == "auto_suggestion"
    best = result["diagnostics"][0]["suggestion"]["candidates"][0]
    assert best["path"] == "docs/guide.md"
