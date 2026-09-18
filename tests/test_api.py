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


def post_files(client, files=FILES, suggest=None):
    payload = {"files": [{"path": p, "content": c} for p, c in files.items()]}
    if suggest is not None:
        payload["suggest"] = suggest
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


SUGGEST_FILES = {
    "README.md": "# Project\n\nSee the [guide](docs/guid.md#usag).\n",
    "docs/guide.md": "# Guide\n\n## Usage\n",
}


def test_suggest_true_attaches_suggestions(client):
    c, _ = client
    resp = post_files(c, SUGGEST_FILES, suggest=True)
    assert resp.status_code == 201
    body = resp.json()
    (diag,) = body["diagnostics"]
    assert diag["type"] == "missing_target"
    assert diag["suggestion"] == {
        "kind": "auto_suggestion",
        "candidates": [
            {
                "path": "docs/guide.md",
                "score": 2,
                "path_distance": 1,
                "anchor_distance": 1,
                "anchor": "usage",
            },
            {
                "path": "README.md",
                "score": 13,
                "path_distance": 6,
                "anchor_distance": 7,
                "anchor": "project",
            },
        ],
    }


def test_suggest_defaults_to_off(client):
    c, _ = client
    body = post_files(c, SUGGEST_FILES).json()
    (diag,) = body["diagnostics"]
    assert diag["suggestion"] is None
    # stored result stays consistent
    assert c.get(f"/checks/{body['check_id']}").json() == body


def test_suggestions_persist_and_roundtrip(client):
    c, _ = client
    body = post_files(c, SUGGEST_FILES, suggest=True).json()
    resp = c.get(f"/checks/{body['check_id']}")
    assert resp.status_code == 200
    assert resp.json() == body
    assert resp.json()["diagnostics"][0]["suggestion"]["kind"] == "auto_suggestion"


def test_suggest_only_marks_missing_target(client):
    c, _ = client
    body = post_files(c, FILES, suggest=True).json()
    assert body["diagnostic_count"] == 6
    for d in body["diagnostics"]:
        if d["type"] == "missing_target":
            assert d["suggestion"] is not None
            assert len(d["suggestion"]["candidates"]) <= 3
        else:
            assert d["suggestion"] is None
    by_link = {d["link"]: d for d in body["diagnostics"]}
    # docs/nope.md is far from every submitted file -> ambiguous
    far = by_link["docs/nope.md"]["suggestion"]
    assert far["kind"] == "ambiguous"
    assert [c["path"] for c in far["candidates"]] == ["docs/guide.md", "README.md"]
    assert [c["score"] for c in far["candidates"]] == [4, 6]
    # "#nope" resolves inside docs/guide.md; that file's own anchors are
    # the closest fix, then README.md
    anchor = by_link["#nope"]["suggestion"]
    assert anchor["kind"] == "ambiguous"
    assert [c["path"] for c in anchor["candidates"]] == ["docs/guide.md", "README.md"]
    assert [c["score"] for c in anchor["candidates"]] == [4, 11]
    assert anchor["candidates"][0]["anchor"] == "guide"
    assert anchor["candidates"][1]["anchor"] == "project"


def test_store_migrates_pre_suggestion_databases(tmp_path):
    import sqlite3

    db_path = str(tmp_path / "old.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE checks (
            id               TEXT PRIMARY KEY,
            created_at       TEXT NOT NULL,
            file_count       INTEGER NOT NULL,
            diagnostic_count INTEGER NOT NULL,
            summary          TEXT NOT NULL
        );
        CREATE TABLE diagnostics (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            check_id   TEXT NOT NULL REFERENCES checks(id) ON DELETE CASCADE,
            type       TEXT NOT NULL,
            source     TEXT NOT NULL,
            line       INTEGER NOT NULL,
            link       TEXT NOT NULL,
            resolved   TEXT,
            message    TEXT NOT NULL
        );
        """
    )
    conn.close()

    store = Store(db_path)  # must add the missing column, not crash
    store.save_check("c1", "2026-09-18T00:00:00+00:00", 1, {"missing_target": 1}, [])
    result = store.get_check("c1")
    assert result is not None
    assert result["diagnostics"] == []
