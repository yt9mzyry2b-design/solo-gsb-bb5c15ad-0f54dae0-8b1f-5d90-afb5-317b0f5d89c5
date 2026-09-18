from app.checker import MISSING_TARGET, PATH_ESCAPE, attach_suggestions, check_files
from app.parser import parse_markdown
from app.suggest import (
    AUTO_SUGGEST_MAX_DISTANCE,
    MAX_SUGGESTIONS,
    edit_distance,
    suggest_fixes,
)

FILES = {
    "README.md": "# Project\n\n[broken](docs/guid.md#usag)\n",
    "docs/guide.md": "# Guide\n\n## Usage\n",
}


def _slugs(files):
    return {
        p: [h.slug for h in parse_markdown(p, c).headings]
        for p, c in files.items()
    }


def test_edit_distance_basics():
    assert edit_distance("guide.md", "guide.md") == 0
    assert edit_distance("guid.md", "guide.md") == 1
    assert edit_distance("usag", "usage") == 1
    assert edit_distance("", "abc") == 3
    assert edit_distance("abc", "") == 3
    assert edit_distance("kitten", "sitting") == 3


def test_close_match_is_auto_suggestion():
    s = suggest_fixes(FILES, _slugs(FILES), "docs/guid.md", "usag")
    assert s.kind == "auto_suggestion"
    best = s.candidates[0]
    assert best.path == "docs/guide.md"
    assert (best.score, best.path_distance, best.anchor_distance) == (2, 1, 1)
    assert best.anchor == "usage"


def test_distant_match_is_ambiguous():
    # path distance 1 + anchor distance 2 lands just above the threshold
    s = suggest_fixes(FILES, _slugs(FILES), "docs/guid.md", "usax")
    assert s.candidates[0].path == "docs/guide.md"
    assert s.candidates[0].score == AUTO_SUGGEST_MAX_DISTANCE + 1
    assert s.kind == "ambiguous"


def test_scores_are_reproducible():
    first = suggest_fixes(FILES, _slugs(FILES), "docs/guid.md", "usag").as_dict()
    second = suggest_fixes(FILES, _slugs(FILES), "docs/guid.md", "usag").as_dict()
    assert first == second


def test_ties_broken_by_full_path_and_capped_at_max():
    files = {f"{d}/x.md": f"# {d}\n" for d in "abcde"}
    s = suggest_fixes(files, _slugs(files), "z/x.md", None)
    assert len(s.candidates) == MAX_SUGGESTIONS == 3
    assert [c.path for c in s.candidates] == ["a/x.md", "b/x.md", "c/x.md"]
    assert all(c.score == 0 for c in s.candidates)


def test_no_fragment_means_zero_anchor_distance():
    s = suggest_fixes(FILES, _slugs(FILES), "docs/guid.md", None)
    best = s.candidates[0]
    assert best.anchor_distance == 0
    assert best.anchor == "guide"  # first slug of the candidate
    assert best.score == best.path_distance


def test_candidate_without_headings_has_no_anchor():
    files = {"img/logo.md": "no headings here\n", "notes.md": "# Notes\n"}
    s = suggest_fixes(files, _slugs(files), "img/log.md", None)
    best = s.candidates[0]
    assert best.path == "img/logo.md"
    assert best.anchor is None
    assert best.anchor_distance == 0


def test_missing_anchor_suggests_the_file_itself():
    # a broken "#fragment" is best fixed by another anchor of the same file
    files = {"only.md": "# Only\n\n[bad](#onl)\n"}
    s = suggest_fixes(files, _slugs(files), "only.md", "onl")
    assert s.kind == "auto_suggestion"
    best = s.candidates[0]
    assert (best.path, best.score, best.path_distance) == ("only.md", 1, 0)
    assert best.anchor == "only"


def test_empty_collection_yields_no_suggestion():
    assert suggest_fixes({}, {}, "x.md", None) is None


def test_attach_suggestions_only_touches_missing_target():
    files = {
        "README.md": "# Project\n\n[broken](docs/guid.md#usag)\n[esc](../out.md)\n",
        "docs/guide.md": "# Guide\n\n## Usage\n",
    }
    diags = check_files(files)
    attach_suggestions(files, diags)
    by_type = {d.type: d for d in diags}
    assert by_type[MISSING_TARGET].suggestion is not None
    assert by_type[MISSING_TARGET].suggestion.kind == "auto_suggestion"
    assert by_type[PATH_ESCAPE].suggestion is None


def test_attach_suggestions_without_candidates_leaves_none():
    files = {"only.md": "# Only\n\n[bad](#nope)\n"}
    (d,) = check_files(files)
    attach_suggestions(files, [d])
    assert d.type == MISSING_TARGET
    assert d.suggestion is not None  # the file itself is a candidate
    assert d.suggestion.candidates[0].path == "only.md"


def test_suggestion_as_dict_shape():
    files = {"a.md": "# A\n\n[x](sub/b.md#t)\n", "b.md": "# B\n\n## T\n"}
    diags = check_files(files)
    attach_suggestions(files, diags)
    (d,) = diags
    assert d.as_dict()["suggestion"] == {
        "kind": "auto_suggestion",
        "candidates": [
            {
                "path": "b.md",
                "score": 0,
                "path_distance": 0,
                "anchor_distance": 0,
                "anchor": "t",
            },
            {
                "path": "a.md",
                "score": 2,
                "path_distance": 1,
                "anchor_distance": 1,
                "anchor": "a",
            },
        ],
    }
