"""Lightweight Markdown parsing: headings (anchors) and links.

The parser only understands the constructs that matter for link checking:

  * ATX headings (``# Title`` .. ``###### Title``) with GitHub-style slugs
  * inline links ``[text](dest "title")`` (images are skipped)
  * reference links ``[text][label]``, collapsed ``[label][]`` and
    shortcut ``[label]`` (only when the label is defined in the same file)
  * fenced code blocks (``` / ~~~), YAML front matter and inline code
    spans are ignored
  * footnote definitions/usages (``[^1]``) are ignored

Intentionally unsupported (treated as plain text): setext headings,
indented code blocks, multi-line link destinations, nested brackets.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Heading:
    line: int
    text: str  # plain-text rendering of the heading
    slug: str  # GitHub-style anchor, suffixed on collisions ("intro-1")
    base: str  # slug before de-duplication


@dataclass
class Link:
    line: int
    target: str  # raw destination as written in the document
    text: str


@dataclass
class DuplicateAnchor:
    line: int
    anchor: str  # the colliding base slug
    first_line: int  # where the anchor was first defined
    assigned: str  # the suffixed slug this heading actually got


@dataclass
class ParsedFile:
    path: str
    headings: list[Heading] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    duplicates: list[DuplicateAnchor] = field(default_factory=list)

    @property
    def slugs(self) -> set[str]:
        return {h.slug for h in self.headings}


_FENCE_RE = re.compile(r"^ {0,3}(```+|~~~+)")
_HEADING_RE = re.compile(r"^ {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_REF_DEF_RE = re.compile(r"^ {0,3}\[((?!\^)[^\]]+)\]:[ \t]*(<[^>]*>|\S+)")
_CODE_SPAN_RE = re.compile(r"(`+).*?\1")
_LINK_RE = re.compile(
    r"""
    (?P<image>!)?                               # optional image marker
    \[(?P<text>[^\]\n]*)\]                      # [text]
    (?:
        \(\s*(?P<dest><[^>\n]*>|[^\s()]+)       # (dest
            (?:\s+("[^"\n]*"|'[^'\n]*'|\([^()\n]*\)))?  # optional "title"
        \s*\)
      | \[(?P<label>[^\]\n]*)\]                 # [label] reference style
    )?                                          # ...or nothing: shortcut ref
    """,
    re.VERBOSE,
)


def _unwrap_code_span(match: re.Match) -> str:
    tick = match.group(1)
    return match.group(0)[len(tick):-len(tick)]


def _strip_inline(md: str) -> str:
    """Reduce inline Markdown to its plain-text rendering (best effort)."""
    md = _CODE_SPAN_RE.sub(_unwrap_code_span, md)
    md = re.sub(r"!\[([^\]]*)\]\([^()]*\)", r"\1", md)    # image -> alt text
    md = re.sub(r"\[([^\]]*)\]\([^()]*\)", r"\1", md)     # inline link -> text
    md = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", md)     # reference link -> text
    md = re.sub(r"\[([^\]]*)\]", r"\1", md)               # shortcut ref -> text
    md = re.sub(r"(\*\*|__|\*|_|~~)(.*?)\1", r"\2", md)   # emphasis
    md = re.sub(r"<[^>]+>", "", md)                       # html tags
    return md.replace("\\[", "[").replace("\\]", "]")


def slugify(text: str) -> str:
    """GitHub-style anchor slug for a heading's raw Markdown text.

    Lowercases, strips inline markup and punctuation, keeps word
    characters (including CJK), hyphens and underscores, and maps each
    whitespace character to a hyphen.
    """
    text = _strip_inline(text).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text)


def _norm_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip()).lower()


def _clean_dest(dest: str) -> str:
    dest = dest.strip()
    if dest.startswith("<") and dest.endswith(">"):
        dest = dest[1:-1]
    return dest


def parse_markdown(path: str, content: str) -> ParsedFile:
    """Parse one Markdown document into headings, links and duplicates."""
    parsed = ParsedFile(path=path)

    # Pass 0: drop front matter and fenced code blocks, keep line numbers.
    body: list[tuple[int, str]] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    in_front_matter = False
    for lineno, line in enumerate(content.splitlines(), start=1):
        if lineno == 1 and line.strip() == "---":
            in_front_matter = True
            continue
        if in_front_matter:
            if line.strip() in ("---", "..."):
                in_front_matter = False
            continue
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence, fence_char, fence_len = True, marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_len:
                in_fence = False
            continue
        if in_fence:
            continue
        body.append((lineno, line))

    # Pass 1: reference definitions (needed to resolve shortcut refs).
    ref_defs: dict[str, str] = {}
    for _, line in body:
        m = _REF_DEF_RE.match(line)
        if m:
            ref_defs.setdefault(_norm_label(m.group(1)), _clean_dest(m.group(2)))

    # Pass 2: headings (with GitHub-style de-duplicated slugs) and links.
    slug_counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for lineno, line in body:
        if _REF_DEF_RE.match(line):
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            raw_text = heading.group(1)
            base = slugify(raw_text)
            count = slug_counts.get(base, 0)
            slug = base if count == 0 else f"{base}-{count}"
            slug_counts[base] = count + 1
            if count == 0:
                first_seen[base] = lineno
            else:
                parsed.duplicates.append(
                    DuplicateAnchor(line=lineno, anchor=base,
                                    first_line=first_seen[base], assigned=slug)
                )
            parsed.headings.append(
                Heading(line=lineno, text=_strip_inline(raw_text).strip(),
                        slug=slug, base=base)
            )
        # Strip inline code spans so `[x](y)` inside `code` is not a link.
        scan = _CODE_SPAN_RE.sub("", line)
        for m in _LINK_RE.finditer(scan):
            if m.group("image"):
                continue
            dest = m.group("dest")
            if dest is not None:
                parsed.links.append(Link(line=lineno, target=_clean_dest(dest),
                                         text=m.group("text")))
                continue
            label = m.group("label")
            if not label:  # collapsed "[text][]" or shortcut "[text]"
                label = m.group("text")
            if label.startswith("^"):  # footnote
                continue
            target = ref_defs.get(_norm_label(label))
            if target is not None:
                parsed.links.append(Link(line=lineno, target=target,
                                         text=m.group("text")))
    return parsed
