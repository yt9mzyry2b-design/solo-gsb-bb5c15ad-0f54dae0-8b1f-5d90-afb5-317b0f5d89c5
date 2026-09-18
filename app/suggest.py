"""Optional fix suggestions for ``missing_target`` diagnostics.

The scoring is deliberately simple and fully deterministic so users can
reproduce it by hand:

* **path distance** – edit distance between the ``/``-separated path
  segments of the broken target and a candidate file, where inserting,
  deleting or substituting one whole segment costs 1.
* **anchor distance** – character-level edit distance between the link's
  fragment and the closest anchor of the candidate file (0 when the link
  has no fragment; ``len(fragment)`` when the candidate has no anchors).
* **score** – path distance + anchor distance.

Every file in the submitted collection is a candidate. Candidates are
ordered by ``(score, full path)`` and truncated to ``MAX_CANDIDATES``.
The status is ``auto_suggestion`` when the best candidate is unique and
its score does not exceed ``AUTO_THRESHOLD``, otherwise ``ambiguous``.
"""
from __future__ import annotations

from dataclasses import dataclass

from .checker import MISSING_TARGET, Diagnostic, resolve_target
from .parser import ParsedFile, parse_markdown

AUTO_SUGGESTION = "auto_suggestion"
AMBIGUOUS = "ambiguous"

MAX_CANDIDATES = 3  # how many candidates are returned per diagnostic
AUTO_THRESHOLD = 2  # max score for a unique best candidate to be "auto"


@dataclass
class Candidate:
    path: str             # candidate file from the submitted collection
    anchor: str | None    # closest anchor in that file (None: link had no fragment)
    path_distance: int    # segment-level edit distance between the paths
    anchor_distance: int  # character-level edit distance between the fragments
    score: int            # path_distance + anchor_distance

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "anchor": self.anchor,
            "path_distance": self.path_distance,
            "anchor_distance": self.anchor_distance,
            "score": self.score,
        }


@dataclass
class Suggestion:
    status: str                  # AUTO_SUGGESTION | AMBIGUOUS
    candidates: list[Candidate]  # best first, at most MAX_CANDIDATES

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "candidates": [c.as_dict() for c in self.candidates],
        }


def edit_distance(a, b) -> int:
    """Levenshtein distance between two sequences.

    Used both for character sequences (anchors) and for lists of path
    segments; substituting, inserting or deleting one element costs 1.
    """
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        current = [i]
        for j, y in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,             # delete x
                current[j - 1] + 1,          # insert y
                previous[j - 1] + (x != y),  # keep or substitute
            ))
        previous = current
    return previous[-1]


def _closest_anchor(fragment: str, slugs: set[str]) -> tuple[int, str | None]:
    """(distance, anchor) of the candidate anchor closest to ``fragment``."""
    if not slugs:
        return len(fragment), None
    distance, slug = min((edit_distance(fragment, s), s) for s in sorted(slugs))
    return distance, slug


def suggest_target(
    parsed: dict[str, ParsedFile], source: str, raw_link: str
) -> Suggestion | None:
    """Rank the files in ``parsed`` as fix candidates for a broken link."""
    status, resolved, fragment = resolve_target(source, raw_link)
    if status != "ok" or resolved is None:
        return None
    target_segments = resolved.split("/")
    candidates = []
    for path, pf in parsed.items():
        path_distance = edit_distance(target_segments, path.split("/"))
        if fragment is not None:
            anchor_distance, anchor = _closest_anchor(fragment, pf.slugs)
        else:
            anchor_distance, anchor = 0, None
        candidates.append(Candidate(
            path=path,
            anchor=anchor,
            path_distance=path_distance,
            anchor_distance=anchor_distance,
            score=path_distance + anchor_distance,
        ))
    candidates.sort(key=lambda c: (c.score, c.path))
    top = candidates[:MAX_CANDIDATES]
    unique_best = len(top) == 1 or top[1].score > top[0].score
    status = (
        AUTO_SUGGESTION
        if unique_best and top[0].score <= AUTO_THRESHOLD
        else AMBIGUOUS
    )
    return Suggestion(status=status, candidates=top)


def attach_suggestions(files: dict[str, str], diagnostics: list[Diagnostic]) -> None:
    """Attach fix suggestions to every missing_target diagnostic, in place."""
    parsed = {path: parse_markdown(path, content) for path, content in files.items()}
    for d in diagnostics:
        if d.type != MISSING_TARGET:
            continue
        d.suggestion = suggest_target(parsed, d.source, d.link)
