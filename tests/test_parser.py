from app.parser import parse_markdown, slugify


def test_slugify_basic():
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("Foo_Bar baz") == "foo_bar-baz"
    assert slugify("Multiple   Spaces") == "multiple---spaces"


def test_slugify_strips_inline_markup():
    assert slugify("**Bold** and `code`") == "bold-and-code"
    assert slugify("[link](https://example.com) text") == "link-text"


def test_slugify_unicode():
    assert slugify("你好 世界") == "你好-世界"
    assert slugify("使用方法（推荐）") == "使用方法推荐"


def test_headings_get_github_style_deduped_slugs():
    pf = parse_markdown("a.md", "# Intro\n\n## Intro\n### Intro\n")
    assert [h.slug for h in pf.headings] == ["intro", "intro-1", "intro-2"]
    assert len(pf.duplicates) == 2
    assert pf.duplicates[0].line == 3
    assert pf.duplicates[0].anchor == "intro"
    assert pf.duplicates[0].first_line == 1
    assert pf.duplicates[0].assigned == "intro-1"


def test_heading_closing_hashes_and_markup():
    pf = parse_markdown("a.md", "# **Getting** Started ##\n")
    assert pf.headings[0].slug == "getting-started"
    assert pf.headings[0].text == "Getting Started"


def test_inline_links_with_title_and_angle_destination():
    pf = parse_markdown("a.md", 'See [docs](guide.md "Guide") and [sp](<my file.md>).\n')
    assert [(l.line, l.target) for l in pf.links] == [(1, "guide.md"), (1, "my file.md")]


def test_images_are_skipped():
    pf = parse_markdown("a.md", "![alt](img.png) [ok](a.md) ![ref][i]\n\n[i]: x.png\n")
    assert [l.target for l in pf.links] == ["a.md"]


def test_reference_links_full_collapsed_shortcut():
    content = "[full][g] [collapsed][] [g]\n\n[g]: guide.md\n[collapsed]: other.md\n"
    pf = parse_markdown("a.md", content)
    assert [l.target for l in pf.links] == ["guide.md", "other.md", "guide.md"]
    assert all(l.line == 1 for l in pf.links)


def test_undefined_shortcut_ref_is_not_a_link():
    pf = parse_markdown("a.md", "See [the guide] for details.\n")
    assert pf.links == []


def test_code_fences_and_inline_code_spans_are_ignored():
    content = "```\n[no](x.md)\n# not-a-heading\n```\n\n`[no](y.md)` [yes](z.md)\n"
    pf = parse_markdown("a.md", content)
    assert [l.target for l in pf.links] == ["z.md"]
    assert pf.links[0].line == 6
    assert pf.headings == []


def test_front_matter_is_ignored():
    content = "---\ntitle: [no](x.md)\n---\n\n[yes](z.md)\n"
    pf = parse_markdown("a.md", content)
    assert [l.target for l in pf.links] == ["z.md"]


def test_footnotes_are_ignored():
    content = "Text with note[^1].\n\n[^1]: not-a-link.md\n"
    assert parse_markdown("a.md", content).links == []


def test_link_inside_heading_is_found():
    pf = parse_markdown("a.md", "# See [the docs](docs.md)\n")
    assert pf.headings[0].slug == "see-the-docs"
    assert [l.target for l in pf.links] == ["docs.md"]
