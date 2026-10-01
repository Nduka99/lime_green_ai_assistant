"""Site pages read as a visitor reads them (X42). Invented pages."""

import pytest

from limespec import webpage

ARTICLE = """<html><head><title>Lime Green</title></head><body>
<header><h1>Menu</h1></header>
<main>
<section class="kb-head"><p class="h1-style tyt">Knowledge base</p>
<p class="pub-date">15<sup>th</sup> June 2017</p><h1>What Is Lime?</h1></section>
<p class="maf-bc">Home &gt; Knowledge</p>
<p>Add <span>water</span>slowly.<br>Mix <a href="/x">well</a>.</p>
<h2>Uses</h2>
<p><strong>Walls</strong></p>
<p>For walls.<img alt="A wall pointed with lime mortar" src="a.jpg"><img alt="Wall"
src="b.jpg"></p>
<p><strong>Reasons to use it:</strong></p>
<ul><li><p>Breathable</p>and soft</li><li><strong>Strong</strong></li></ul>
<p class="h3-style">Mixing</p>
<blockquote>"Quoted text<!-- a note --> here"</blockquote>
<p class="page-lead">Downloads</p>
<p class="page-lead">A lead paragraph much longer than one line of the content
column, so it stays an ordinary paragraph however large its text is set.</p>
<dl><dt>Is it safe?</dt><dd>Yes.</dd></dl>
<p class="up-link"><a href="/kb">&lt; Back to knowledge base</a></p>
<div class="maf-content call"><p>Product advice and expert help</p></div>
</main></body></html>"""


def test_an_article_is_read_in_lines_with_its_heading_path() -> None:
    title, found = webpage.read_page(ARTICLE)

    assert title == "What Is Lime?"
    assert [(e["kind"], e["text"], e["section"]) for e in found] == [
        ("meta", "Knowledge base", []),
        ("meta", "15th June 2017", []),
        ("paragraph", "Add waterslowly.", []),
        ("paragraph", "Mix well.", []),
        ("heading", "Uses", []),
        ("heading", "Walls", ["Uses"]),
        ("paragraph", "For walls.", ["Uses", "Walls"]),
        ("figure", "A wall pointed with lime mortar", ["Uses", "Walls"]),
        ("paragraph", "Reasons to use it:", ["Uses", "Walls"]),
        ("list_item", "Breathable", ["Uses", "Walls"]),
        ("list_item", "and soft", ["Uses", "Walls"]),
        ("list_item", "Strong", ["Uses", "Walls"]),
        ("heading", "Mixing", ["Uses"]),
        ("paragraph", '"Quoted text here"', ["Uses", "Mixing"]),
        ("heading", "Downloads", ["Uses", "Mixing"]),
        (
            "paragraph",
            "A lead paragraph much longer than one line of the content column, so it "
            "stays an ordinary paragraph however large its text is set.",
            ["Uses", "Mixing", "Downloads"],
        ),
        ("heading", "Is it safe?", ["Uses", "Mixing"]),
        ("paragraph", "Yes.", ["Uses", "Mixing", "Is it safe?"]),
    ]
    levels = {e["text"]: e["level"] for e in found if e["kind"] == "heading"}
    assert levels == {
        "Uses": 2,
        "Walls": 3,
        "Mixing": 3,
        "Downloads": 4,
        "Is it safe?": 4,
    }


LISTING = """<html><head><title>Ochre</title></head><body><main>
<div class="cardbox product-feed">
<article class="card"><a class="portal-item" href="/duro"><h1 class="title">Duro</h1>
<div class="desc">A base coat.</div>
<button class="card-button">Product details</button>
</a></article>
<article class="card"><span class="portal-item no-link">
<h1 class="title">Simon Ayres</h1>
<div class="desc"><p>Managing Director</p></div></span></article>
<article class="card"><span class="portal-item no-link">
<div class="desc">Low carbon</div>
</span></article>
</div>
<div class="clr-grid"><a class="clr"><p class="name">York</p>
<p class="link">More &gt;</p></a></div>
<div class="ds"><div class="txt"><p>Click a button.</p></div>
<div class="bts"><a class="button" href="/sds.pdf">SDS</a></div></div>
<p class="links"><a class="button" href="/find">Find a supplier</a></p>
</main></body></html>"""


def test_cards_grids_and_downloads_are_read_as_lists_of_names() -> None:
    title, found = webpage.read_page(LISTING)

    assert title == "Ochre"  # no <h1> left once the cards are read: the page's title
    assert [(e["kind"], e["text"]) for e in found] == [
        ("list_item", "Duro"),
        ("list_item", "Simon Ayres"),
        ("list_item", "Managing Director"),
        ("list_item", "Low carbon"),
        ("list_item", "York"),
        ("list_item", "SDS"),
    ]


def test_a_callout_is_content_only_on_the_page_it_is_about() -> None:
    callout = '<section class="find-supplier"><h2>Find a supplier</h2></section>'
    own = f"<main><h1>Find a supplier</h1>{callout}</main>"
    elsewhere = f"<main><h1>About</h1><p>Founded in 2002.</p>{callout}</main>"

    assert webpage.read_page(own)[1] == [
        {"kind": "heading", "text": "Find a supplier", "level": 2, "section": []}
    ]
    assert [e["text"] for e in webpage.read_page(elsewhere)[1]] == ["Founded in 2002."]


def test_a_page_without_a_body_or_a_title_tag() -> None:
    with pytest.raises(ValueError):
        webpage.read_page("")
    assert webpage.read_page("<body><p>Text</p></body>") == (
        "",
        [{"kind": "paragraph", "text": "Text", "section": []}],
    )
