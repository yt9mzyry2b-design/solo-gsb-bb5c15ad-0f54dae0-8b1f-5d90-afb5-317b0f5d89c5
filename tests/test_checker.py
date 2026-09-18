from app.checker import (
    DUPLICATE_ANCHOR,
    MISSING_TARGET,
    PATH_ESCAPE,
    SELF_REFERENCE,
    check_files,
    normalize_path,
    resolve_target,
    summarize,
)


def test_normalize_path():
    assert normalize_path("docs/a.md") == "docs/a.md"
    assert normalize_path("./docs//a.md") == "docs/a.md"
    assert normalize_path("docs\\a.md") == "docs/a.md"
    assert normalize_path("/abs.md") == "abs.md"
    assert normalize_path("../up.md") is None
    assert normalize_path("docs/../../up.md") is None


def test_resolve_external_and_placeholder():
    assert resolve_target("a.md", "https://example.com/x")[0] == "external"
    assert resolve_target("a.md", "mailto:a@b.c")[0] == "external"
    assert resolve_target("a.md", "//cdn.example.com/x")[0] == "external"
    assert resolve_target("a.md", "#")[0] == "skip"
    assert resolve_target("a.md", "")[0] == "skip"


def test_resolve_relative_and_fragment():
    assert resolve_target("docs/a.md", "../README.md#Intro") == ("ok", "README.md", "Intro")
    assert resolve_target("docs/a.md", "#local") == ("ok", "docs/a.md", "local")
    assert resolve_target("docs/a.md", "sub/page.md") == ("ok", "docs/sub/page.md", None)
    assert resolve_target("docs/a.md", "/root.md") == ("ok", "root.md", None)


def test_resolve_escape_and_percent_decoding():
    assert resolve_target("docs/a.md", "../../etc.md")[0] == "escape"
    assert resolve_target("a.md", "my%20file.md") == ("ok", "my file.md", None)
    assert resolve_target("a.md", "b.md#my%20anchor") == ("ok", "b.md", "my anchor")


def test_missing_file_and_missing_anchor():
    # links sit under "## Other"; "#t" points to a different section (valid)
    files = {"a.md": "# T\n\n## Other\n\n[no](missing.md) [bad](#nope) [ok](#t)\n"}
    diags = check_files(files)
    got = sorted((d.type, d.link, d.line) for d in diags)
    assert got == [(MISSING_TARGET, "#nope", 5), (MISSING_TARGET, "missing.md", 5)]
    anchor_diag = next(d for d in diags if d.link == "#nope")
    assert anchor_diag.resolved == "a.md#nope"


def test_valid_cross_file_links_produce_no_diagnostics():
    files = {
        "README.md": "# Home\n\n[guide](docs/guide.md#usage)\n",
        "docs/guide.md": "# Guide\n\n## Usage\n\n[home](../README.md#home)\n",
    }
    assert check_files(files) == []


def test_path_escape():
    files = {"docs/a.md": "# A\n\n[out](../../secret.md)\n"}
    (d,) = check_files(files)
    assert d.type == PATH_ESCAPE
    assert (d.source, d.line, d.link) == ("docs/a.md", 3, "../../secret.md")
    assert d.resolved is None


def test_self_reference_to_file_and_to_own_section():
    files = {
        "a.md": "# Top\n\n[self](a.md)\n\n## Sec\n\n[loop](#sec)\n[ok](#top)\n",
    }
    diags = check_files(files)
    got = sorted((d.line, d.link) for d in diags)
    assert got == [(3, "a.md"), (7, "#sec")]
    assert all(d.type == SELF_REFERENCE for d in diags)


def test_duplicate_anchor_reported_and_suffixed_slug_resolves():
    # the link sits under "# Other" so referencing "#dup-1" is not a self-loop
    files = {"a.md": "# Dup\n\n# Dup\n\n# Other\n\n[ref](#dup-1)\n"}
    (d,) = check_files(files)
    assert d.type == DUPLICATE_ANCHOR
    assert (d.source, d.line, d.link) == ("a.md", 3, "#dup")
    assert "first defined at line 1" in d.message


def test_percent_encoded_and_backslash_paths_match_submitted_names():
    files = {
        "a.md": "# A\n\n[sp](my%20file.md) [win](sub\\b.md)\n",
        "my file.md": "# B\n",
        "sub/b.md": "# C\n",
    }
    assert check_files(files) == []


def test_external_links_are_not_checked():
    files = {"a.md": "# A\n\n[x](https://example.com/gone) [m](mailto:a@b.c)\n"}
    assert check_files(files) == []


def test_summarize_includes_all_types():
    files = {
        "a.md": "# T\n# T\n\n[x](gone.md) [up](../out.md) [me](a.md)\n",
    }
    summary = summarize(check_files(files))
    assert summary == {
        "missing_target": 1,
        "duplicate_anchor": 1,
        "path_escape": 1,
        "self_reference": 1,
    }
