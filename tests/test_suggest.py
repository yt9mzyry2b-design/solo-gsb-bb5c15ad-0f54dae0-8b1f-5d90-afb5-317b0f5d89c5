from app.checker import MISSING_TARGET, check_files
from app.suggest import (
    AMBIGUOUS,
    AUTO_SUGGESTION,
    MAX_CANDIDATES,
    attach_suggestions,
    edit_distance,
)


def run(files):
    diagnostics = check_files(files)
    attach_suggestions(files, diagnostics)
    return diagnostics


def only_missing(diagnostics):
    (d,) = [d for d in diagnostics if d.type == MISSING_TARGET]
    return d


def test_edit_distance_characters():
    assert edit_distance("kitten", "sitting") == 3
    assert edit_distance("", "abc") == 3
    assert edit_distance("abc", "abc") == 0


def test_edit_distance_segments():
    assert edit_distance(["docs", "nope.md"], ["docs", "guide.md"]) == 1
    assert edit_distance(["docs", "nope.md"], ["README.md"]) == 2
    assert edit_distance([], ["a", "b"]) == 2


def test_missing_file_auto_suggestion():
    diags = run({
        "README.md": "# Home\n\n[gone](docs/nope.md)\n",
        "docs/guide.md": "# Guide\n",
    })
    d = only_missing(diags)
    assert d.suggestion.status == AUTO_SUGGESTION
    best = d.suggestion.candidates[0]
    assert best.path == "docs/guide.md"
    assert best.anchor is None
    assert (best.path_distance, best.anchor_distance, best.score) == (1, 0, 1)


def test_scores_are_reproducible_sums():
    diags = run({
        "README.md": "# Home\n\n[gone](docs/nope.md#usage)\n",
        "docs/guide.md": "# Guide\n\n## Usage\n",
        "notes.md": "# Notes\n",
    })
    d = only_missing(diags)
    for c in d.suggestion.candidates:
        assert c.score == c.path_distance + c.anchor_distance
    best = d.suggestion.candidates[0]
    assert (best.path, best.anchor) == ("docs/guide.md", "usage")
    assert best.score == 1  # 1 for the path, 0 for the exact anchor


def test_missing_anchor_suggests_closest_anchor_in_target_file():
    diags = run({
        "docs/guide.md": "# Guide\n\n## Usage\n\n[typo](#usag)\n",
        "README.md": "# Home\n",
    })
    d = only_missing(diags)
    best = d.suggestion.candidates[0]
    assert d.suggestion.status == AUTO_SUGGESTION
    assert (best.path, best.anchor) == ("docs/guide.md", "usage")
    assert (best.path_distance, best.anchor_distance, best.score) == (0, 1, 1)


def test_tied_best_candidates_are_ambiguous():
    diags = run({
        "README.md": "# Home\n\n[gone](docs/nope.md)\n",
        "docs/a.md": "# A\n",
        "docs/b.md": "# B\n",
    })
    d = only_missing(diags)
    assert d.suggestion.status == AMBIGUOUS
    assert [c.path for c in d.suggestion.candidates] == [
        "docs/a.md", "docs/b.md", "README.md",
    ]
    assert d.suggestion.candidates[0].score == 1  # tied, so not "auto"


def test_distant_single_candidate_is_ambiguous():
    diags = run({
        "README.md": "# Home\n\n[gone](deeply/nested/path/x.md)\n",
    })
    d = only_missing(diags)
    assert len(d.suggestion.candidates) == 1
    assert d.suggestion.candidates[0].score == 4  # unique but over threshold
    assert d.suggestion.status == AMBIGUOUS


def test_candidates_are_limited_to_three_and_sorted_by_path_on_ties():
    files = {"README.md": "# Home\n\n[gone](x.md)\n"}
    for name in ["e.md", "c.md", "a.md", "d.md", "b.md"]:
        files[name] = f"# {name}\n"
    d = only_missing(run(files))
    paths = [c.path for c in d.suggestion.candidates]
    assert len(paths) == MAX_CANDIDATES
    # all six files tie at score 1; ties break on the full path (codepoint order)
    assert paths == ["README.md", "a.md", "b.md"]


def test_fragment_penalty_when_candidate_has_no_anchors():
    diags = run({
        "README.md": "[gone](docs/nope.md#lost)\n",
        "empty.md": "no headings here\n",
    })
    d = only_missing(diags)
    (c,) = [c for c in d.suggestion.candidates if c.path == "empty.md"]
    assert c.anchor is None
    assert c.anchor_distance == len("lost")


def test_non_missing_diagnostics_have_no_suggestion():
    diags = run({"a.md": "# T\n\n[me](a.md)\n"})
    (d,) = diags
    assert d.type == "self_reference"
    assert d.suggestion is None
