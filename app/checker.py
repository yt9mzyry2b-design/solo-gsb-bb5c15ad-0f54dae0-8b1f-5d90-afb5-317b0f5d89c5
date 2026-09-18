"""Cross-file link resolution and diagnostics.

All paths are normalized to repo-relative POSIX form. A link target is
resolved against the directory of its source file; fragments are matched
against the GitHub-style slugs generated from the target file's headings.
"""
from __future__ import annotations

import bisect
import posixpath
import re
from dataclasses import dataclass
from urllib.parse import unquote

from .parser import ParsedFile, parse_markdown

MISSING_TARGET = "missing_target"
DUPLICATE_ANCHOR = "duplicate_anchor"
PATH_ESCAPE = "path_escape"
SELF_REFERENCE = "self_reference"

DIAGNOSTIC_TYPES = (MISSING_TARGET, DUPLICATE_ANCHOR, PATH_ESCAPE, SELF_REFERENCE)

# URI scheme of at least 2 chars (http:, https:, mailto: ...). Requiring 2+
# avoids mistaking a Windows drive letter ("c:") for a scheme.
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]{1,31}:")


@dataclass
class Diagnostic:
    type: str
    source: str          # file containing the offending link/heading
    line: int            # 1-based line number in the source file
    link: str            # the link exactly as written ("#anchor" for duplicates)
    message: str
    resolved: str | None = None  # normalized target path, if resolvable

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "source": self.source,
            "line": self.line,
            "link": self.link,
            "resolved": self.resolved,
            "message": self.message,
        }


def normalize_path(path: str) -> str | None:
    """Normalize a repo-relative path to canonical POSIX form.

    Returns ``None`` when the path escapes the document root via ``..``.
    """
    p = path.replace("\\", "/").lstrip("/")
    p = posixpath.normpath(p)
    if p in ("", "."):
        return ""
    if p == ".." or p.startswith("../"):
        return None
    return p


def resolve_target(source: str, raw_target: str) -> tuple[str, str | None, str | None]:
    """Resolve a link target written in ``source``.

    Returns ``(status, resolved_path, fragment)`` where status is one of:

    * ``skip``     – placeholder targets ("", "#"), nothing to check
    * ``external`` – has a URI scheme or ``//`` host, not verified offline
    * ``escape``   – resolves outside the submitted document root
    * ``ok``       – normalized repo-relative path (+ optional fragment)
    """
    target = raw_target.strip()
    if not target or target == "#":
        return ("skip", None, None)
    if _SCHEME_RE.match(target) or target.startswith("//"):
        return ("external", None, None)
    path_part, sep, frag = target.partition("#")
    fragment = unquote(frag) if sep else None
    if fragment == "":
        fragment = None
    path_part = unquote(path_part).replace("\\", "/")
    if path_part == "":
        return ("ok", source, fragment)
    if path_part.startswith("/"):
        joined = path_part  # root-relative within the submitted set
    else:
        joined = posixpath.join(posixpath.dirname(source), path_part)
    normalized = normalize_path(joined)
    if normalized is None:
        return ("escape", None, fragment)
    return ("ok", normalized, fragment)


def _enclosing_slug(parsed: ParsedFile, line: int) -> str | None:
    """Slug of the nearest heading at or above ``line`` (the link's section)."""
    lines = [h.line for h in parsed.headings]
    idx = bisect.bisect_right(lines, line) - 1
    return parsed.headings[idx].slug if idx >= 0 else None


def check_files(files: dict[str, str]) -> list[Diagnostic]:
    """Check a collection of Markdown files ({normalized_path: content})."""
    parsed = {path: parse_markdown(path, content) for path, content in files.items()}
    diagnostics: list[Diagnostic] = []

    for path, pf in parsed.items():
        for dup in pf.duplicates:
            diagnostics.append(Diagnostic(
                type=DUPLICATE_ANCHOR,
                source=path,
                line=dup.line,
                link=f"#{dup.anchor}",
                resolved=path,
                message=(
                    f"duplicate anchor '#{dup.anchor}' (first defined at line "
                    f"{dup.first_line}); this heading is reachable as '#{dup.assigned}'"
                ),
            ))

    for path, pf in parsed.items():
        for link in pf.links:
            status, resolved, fragment = resolve_target(path, link.target)
            if status in ("skip", "external"):
                continue
            if status == "escape":
                diagnostics.append(Diagnostic(
                    type=PATH_ESCAPE,
                    source=path,
                    line=link.line,
                    link=link.target,
                    resolved=None,
                    message=f"link escapes the submitted document root: {link.target!r}",
                ))
                continue
            if resolved == path and (
                fragment is None or fragment == _enclosing_slug(pf, link.line)
            ):
                what = "the file itself" if fragment is None else f"its own section '#{fragment}'"
                diagnostics.append(Diagnostic(
                    type=SELF_REFERENCE,
                    source=path,
                    line=link.line,
                    link=link.target,
                    resolved=resolved,
                    message=f"link points to {what}",
                ))
                continue
            target_file = parsed.get(resolved)
            if target_file is None:
                diagnostics.append(Diagnostic(
                    type=MISSING_TARGET,
                    source=path,
                    line=link.line,
                    link=link.target,
                    resolved=resolved,
                    message=f"target file not found: {resolved!r}",
                ))
                continue
            if fragment is not None and fragment not in target_file.slugs:
                diagnostics.append(Diagnostic(
                    type=MISSING_TARGET,
                    source=path,
                    line=link.line,
                    link=link.target,
                    resolved=f"{resolved}#{fragment}",
                    message=f"anchor '#{fragment}' not found in {resolved!r}",
                ))

    diagnostics.sort(key=lambda d: (d.source, d.line, d.type, d.link))
    return diagnostics


def summarize(diagnostics: list[Diagnostic]) -> dict[str, int]:
    """Per-type counts, always including every known type."""
    summary = {t: 0 for t in DIAGNOSTIC_TYPES}
    for d in diagnostics:
        summary[d.type] = summary.get(d.type, 0) + 1
    return summary
