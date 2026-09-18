"""Optional fix suggestions for ``missing_target`` diagnostics.

For every missing target, each candidate file in the submitted collection
is scored by the sum of two edit distances:

* the basename of the broken link's resolved path vs. the basename of the
  candidate file (the *path segment* distance), and
* the link's fragment (``#anchor``) vs. each anchor slug of the candidate
  file, taking the best match (the *anchor* distance; 0 when the link has
  no fragment).

The score is fully reproducible: plain Levenshtein distance over the raw
strings, no weighting, no randomness. Candidates are sorted by total
distance, then by their full normalized path, and at most
``MAX_SUGGESTIONS`` are kept. When the single best candidate's total
distance does not exceed ``AUTO_SUGGEST_MAX_DISTANCE`` the suggestion is
marked ``auto_suggestion``, otherwise ``ambiguous``.
"""
from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass

MAX_SUGGESTIONS = 3
# Best-candidate total distance at or below which a suggestion is
# considered unambiguous. Configurable via the environment.
AUTO_SUGGEST_MAX_DISTANCE = int(os.environ.get("LINKCHECK_SUGGEST_MAX_DISTANCE", "2"))


@dataclass
class Candidate:
    path: str            # normalized path of the candidate file
    score: int           # path-segment distance + best anchor distance
    path_distance: int   # edit distance between the two basenames
    anchor_distance: int  # best edit distance between fragment and slugs
    anchor: str | None   # the candidate's closest slug, if it has any


@dataclass
class Suggestion:
    kind: str            # "auto_suggestion" | "ambiguous"
    candidates: list[Candidate]

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "candidates": [
                {
                    "path": c.path,
                    "score": c.score,
                    "path_distance": c.path_distance,
                    "anchor_distance": c.anchor_distance,
                    "anchor": c.anchor,
                }
                for c in self.candidates
            ],
        }


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two strings (insert/delete/substitute)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(
                prev[j] + 1,                      # delete ca
                cur[j - 1] + 1,                   # insert cb
                prev[j - 1] + (ca != cb),         # substitute / match
            ))
        prev = cur
    return prev[-1]


def suggest_fixes(
    files: dict[str, str],
    slugs_by_path: dict[str, list[str]],
    resolved: str,
    fragment: str | None,
) -> Suggestion | None:
    """Rank the submitted files as repair candidates for one missing target.

    ``resolved`` is the normalized path the link pointed at (the part before
    ``#`` when the diagnostic's resolved value carries a fragment) and
    ``fragment`` the decoded anchor, if any. Every file in the collection is
    a candidate — including the resolved file itself, whose own anchors are
    the natural fix for a broken ``#fragment``. Returns ``None`` only when
    the collection is empty.
    """
    target_base = posixpath.basename(resolved)
    scored: list[Candidate] = []
    for path in sorted(files):
        path_dist = edit_distance(target_base, posixpath.basename(path))
        anchor_dist = 0
        best_anchor: str | None = None
        slugs = slugs_by_path.get(path, [])
        if slugs:
            if fragment is not None:
                best_anchor = min(slugs, key=lambda s: (edit_distance(fragment, s), s))
                anchor_dist = edit_distance(fragment, best_anchor)
            else:
                best_anchor = slugs[0]
        scored.append(Candidate(
            path=path,
            score=path_dist + anchor_dist,
            path_distance=path_dist,
            anchor_distance=anchor_dist,
            anchor=best_anchor,
        ))
    if not scored:
        return None
    scored.sort(key=lambda c: (c.score, c.path))
    top = scored[:MAX_SUGGESTIONS]
    kind = (
        "auto_suggestion"
        if top[0].score <= AUTO_SUGGEST_MAX_DISTANCE
        else "ambiguous"
    )
    return Suggestion(kind=kind, candidates=top)
