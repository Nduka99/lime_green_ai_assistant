"""A site page read as a visitor reads it (X42): the main content's elements in
reading order, each with the path of headings above it, as `limespec.pdf` gives a
PDF's elements.

The text is laid out as a browser lays it out (the WHATWG `innerText` steps): runs
of text join inside inline elements, and a line ends where a block-level element
starts or ends and at `<br>`, so no text is lost because its tag was not expected.
What counts as the page's own content follows the main-content rule fixed before
the extractors were scored (X42 report): site furniture is removed by component,
cards that are not links are content, and a listing's link cards are read as the
names of what they list, with a card's description when no other page holds it
(X44 F3a). Callouts are content on a page that holds nothing else: the page they are
about (X43 A2). A slideshow of link cards lists related pages; a slideshow of text
slides (testimonials) is content (X44 F4).
"""

import re
from collections.abc import Callable, Sequence
from typing import Any

from bs4 import BeautifulSoup, Tag
from bs4.element import Comment, NavigableString

# Site furniture, by component (X42 main-content rule).
FURNITURE = ", ".join(
    [
        "header, nav, footer, form, script, style, noscript, svg",
        ".modal",  # login box
        ".maf-bc",  # breadcrumb trail
        ".tabs",  # product tab bar
        ".gal",  # photo gallery
        ".associated, .blog-highlight, .flickity-slideshow.cardbox",  # related cards
        ".blog-detail .maf-col-2",  # an article's sidebar: related cards
        ".page-content-section .maf-col-2",  # a page's side box (the FAQ's AI box)
        ".clr-col-1 p, .clr-col-2, .clr .link",  # colour-chart help, samples box
        ".ds .txt p:not(.page-lead)",  # download instructions
        ".card-button, .maf-input, p.up-link",  # card buttons, pickers, back links
    ]
)
CALLOUTS = ".sup-call, .caller-section, .con-callout, .find-supplier, .call"
TITLE_BLOCK = ".kb-head"  # a knowledge-base title block: a label, a date, the <h1>
# Elements that start and end a line (block-level in the site's CSS).
BLOCKS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "main",
    "ol",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
HEADING_TAG = re.compile(r"^h([1-6])$")
HEADING_STYLE = re.compile(r"^h([1-6])-style$")  # a paragraph styled as a heading
BOLD = {"strong", "b"}
LARGE = "page-lead"  # the site's class for larger text
LEAD_IN = (":", ";")  # a line ending so introduces what follows: not a heading
ONE_LINE = 100  # characters: a heading fits on one line of the content column
DESCRIBED = 5  # words: an image's alt text this long describes it (X42 truth rule)
WORDS = re.compile(r"\w+")
CUT = " .…"  # the site cuts a long card description short with an ellipsis
Held = Callable[[str], bool]  # whether some page already holds a text


def names_list(soup: BeautifulSoup, names: list[str]) -> Tag:
    """A <ul> holding one <li> per name."""
    found = soup.new_tag("ul")
    for name in names:
        item = soup.new_tag("li")
        item.string = name
        found.append(item)
    return found


def text_of(tag: Tag | None) -> str:
    return " ".join(tag.get_text(" ").split()) if tag else ""


def held_by(texts: Sequence[str]) -> Held:
    """Whether a text is already held by one of `texts`, compared as words in order,
    case folded, without the ellipsis that cuts a card's description short."""
    known = " " + " ".join(" ".join(WORDS.findall(t.casefold())) for t in texts) + " "

    def held(text: str) -> bool:
        words = " ".join(WORDS.findall(text.rstrip(CUT).casefold()))
        return bool(words) and f" {words} " in known

    return held


def listings(soup: BeautifulSoup, root: Tag, held: Held | None = None) -> None:
    """Cards and grids read as lists. Link cards left in the page's own column are its
    listing: their names, each followed by its description where `held` says no other
    page holds it (X44 F3a). A card that is not a link carries content: its title and
    text, each an item. Colour grids and download buttons are lists of names."""
    for box in root.select(".cardbox"):
        cards = box.select("article.card")
        names = []
        for card in cards:
            if card.select_one("a.portal-item"):
                names.append(text_of(card.select_one(".title")))
                description = text_of(card.select_one(".desc"))
                if held is not None and description and not held(description):
                    names.append(description)
            else:
                names += [
                    text_of(card.select_one(".title")),
                    text_of(card.select_one(".desc")),
                ]
        box.replace_with(names_list(soup, [name for name in names if name]))
    for grid in root.select(".clr-grid"):
        colours = names_list(soup, [text_of(n) for n in grid.select(".name")])
        # Each colour keeps its swatch picture, named by the colour (X43 B).
        for item, swatch in zip(
            colours.find_all("li"), grid.select(".clr"), strict=True
        ):
            picture = swatch.find("img")
            if picture is not None:
                picture["alt"] = text_of(item)
                item.append(picture)
        grid.replace_with(colours)
    for buttons in root.select(".ds .bts"):
        names = [text_of(button) for button in buttons.select("a")]
        buttons.replace_with(names_list(soup, names))
    for button in root.select("a.button"):
        button.decompose()  # link buttons point elsewhere


def rendered_lines(root: Tag, every_image: bool = False) -> list[dict[str, Any]]:
    """The text as a browser lays it out: each line with the block element that holds
    it, whether all of it is bold, and images as lines of their own with the file
    they show: those with a describing alt text, or with `every_image` all of them."""
    lines: list[dict[str, Any]] = []
    runs: list[tuple[str, bool]] = []

    def end_line(block: Tag) -> None:
        text = " ".join("".join(run for run, _ in runs).split())
        if text:
            bold = all(heavy for run, heavy in runs if run.strip())
            lines.append({"text": text, "block": block, "bold": bold, "figure": False})
        runs.clear()

    def walk(node: Tag, block: Tag, bold: bool) -> None:
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                runs.append((str(child), bold))
            elif isinstance(child, Tag) and child.name == "br":
                end_line(block)
            elif isinstance(child, Tag) and child.name == "img":
                alt = " ".join(str(child.get("alt") or "").split())
                source = str(child.get("data-src") or child.get("src") or "")
                if source and (every_image or len(alt.split()) >= DESCRIBED):
                    end_line(block)
                    lines.append({"text": alt, "block": block, "bold": False,
                                  "figure": True, "image": source})  # fmt: skip
            elif isinstance(child, Tag) and child.name in BLOCKS:
                end_line(block)
                walk(child, child, False)
                end_line(child)
            elif isinstance(child, Tag):
                walk(child, block, bold or child.name in BOLD)

    walk(root, root, False)
    end_line(root)
    return lines


def tagged_level(block: Tag) -> int | None:
    """A heading's level from its tag (h1-h6), or from a heading style on another
    element (the site styles some paragraphs as headings)."""
    tag = HEADING_TAG.match(block.name)
    if tag:
        return int(tag[1])
    for name in block.get("class") or []:
        style = HEADING_STYLE.match(name)
        if style:
            return int(style[1])
    return None


def item_list(block: Tag) -> Tag | None:
    """The list a line belongs to: its own <li>'s list, or None."""
    item = block if block.name == "li" else block.find_parent("li")
    return item.find_parent(["ul", "ol"]) if item else None


def elements(
    lines: list[dict[str, Any]], title_block: list[Tag]
) -> list[dict[str, Any]]:
    """Lines as elements, each with the headings above it. A tagged heading takes its
    level; a definition term, or a bold or large line that fits on one line and does
    not end as a lead-in, sits one level below the last tagged heading. Lines of the
    title block are metadata."""
    found: list[dict[str, Any]] = []
    path: list[tuple[int, str]] = []
    base = 1  # the last tagged heading's level (the title is level 1)
    for line in lines:
        block = line["block"]
        text = line["text"]
        section = [heading for _, heading in path]
        heavy = line["bold"] or LARGE in (block.get("class") or [])
        level = tagged_level(block)
        if any(tag is part for tag in [block, *block.parents] for part in title_block):
            found.append({"kind": "meta", "text": text, "section": section})
            continue
        if line["figure"]:
            figure = {"kind": "figure", "text": text, "section": section}
            found.append(figure | {"image": line["image"]})
            continue
        derived = block.name == "dt" or (
            heavy
            and len(text) <= ONE_LINE
            and not text.endswith(LEAD_IN)
            and not item_list(block)
        )
        if level is None and derived:
            level = base + 1
        elif level is not None:
            base = level
        if level is not None:
            path = [(n, heading) for n, heading in path if n < level]
            parents = [heading for _, heading in path]
            found.append(
                {"kind": "heading", "text": text, "level": level, "section": parents}
            )
            path.append((level, text))
            continue
        kind = "list_item" if item_list(block) else "paragraph"
        found.append({"kind": kind, "text": text, "section": section})
    return found


def read_page(
    raw_html: str, every_image: bool = False, held: Held | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """The page's title and its main content's elements in reading order; with
    `every_image`, every image of the main content is a figure, not only those whose
    alt text describes them; with `held`, a link card's description no other page
    holds is read after its name. A page left with no content once its callouts are
    removed is read with them: it is the page they are about."""
    title, found = read_main(raw_html, every_image, f"{FURNITURE}, {CALLOUTS}", held)
    if any(element["kind"] != "meta" for element in found):
        return title, found
    return read_main(raw_html, every_image, FURNITURE, held)


def read_main(
    raw_html: str, every_image: bool, furniture: str, held: Held | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """`read_page` with the given furniture removed."""
    soup = BeautifulSoup(raw_html, "html.parser")
    root = soup.find("main") or soup.body
    if root is None:
        raise ValueError("page has no <body>")
    for element in root.select(furniture):
        element.decompose()
    listings(soup, root, held)
    heading = root.find("h1")
    title = text_of(heading) if heading else text_of(soup.title)
    if heading:
        heading.decompose()  # the title is the page's, not a section's
    lines = rendered_lines(root, every_image)
    return title, elements(lines, root.select(TITLE_BLOCK))
