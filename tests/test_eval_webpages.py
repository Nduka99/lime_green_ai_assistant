"""X42: the web audit and the ground-truth sample. Invented pages."""

import json
from pathlib import Path

import pytest

from evaluation import __main__ as cli
from evaluation import sets, webpages
from limespec import config

PAGE = """<html><body><header><h1>Menu</h1></header><main>
<h1>Duro</h1>
<h2>Uses</h2><p>A general purpose base coat for renovation and conservation work,
suitable for most masonry backgrounds and applied by hand or by machine.</p>
<h3>Mixing</h3><p>Add <span>water</span>slowly.<br>Mix well.</p>
<div class="swatch">Datasheet SDS</div>
</main></body></html>"""
FLAT = "<html><body><main><h1>Ochre</h1><p>Find a supplier near you today.</p>"
FLAT += "</main></body></html>"


def test_page_types_follow_the_site_sections() -> None:
    assert webpages.page_type("products__lime-render__duro") == "product"
    assert webpages.page_type("warmshell-natural-insulation__aerogel") == "product"
    assert webpages.page_type("products__lime-render") == "other"
    assert webpages.page_type("products-by-colour__ochre") == "colour"
    assert webpages.page_type("support__knowledgebase__what-is-lime") == "knowledge"
    assert webpages.page_type("inspirations__exterior") == "knowledge"
    assert webpages.page_type("inspirations") == "other"
    assert webpages.page_type("support__case-studies__globe") == "case study"
    assert webpages.page_type("news__open-day") == "news"
    assert webpages.page_type("support__faq") == "other"


def test_the_audit_counts_lost_words_tiny_and_repeated_passages() -> None:
    found = webpages.audit({"duro": PAGE, "ochre": FLAT, "copy": FLAT})

    duro = found["pages"]["duro"]
    assert duro["lost"] == 2  # "water slowly." shown, "waterslowly." kept
    assert duro["levels"] == ["h1", "h2", "h3"]
    assert (duro["passages"], duro["tiny"], duro["repeated"]) == (2, 1, 0)
    assert found["pages"]["ochre"]["repeated"] == 0  # too short to count as repeated
    assert found["total"]["nested"] == 1
    assert webpages.structure_rich(PAGE) and not webpages.structure_rich(FLAT)


def test_the_sample_takes_rich_pages_then_fills_each_type() -> None:
    pages = {f"products__mortar__p{n}": FLAT for n in range(10)}
    pages |= {"products__render__rich": PAGE, f"news__n{1}": FLAT, "faq": FLAT}

    chosen = webpages.sample(pages, seed=1)

    assert chosen[0] == "products__render__rich"
    assert sum(webpages.page_type(s) == "product" for s in chosen) == 8
    assert {"news__n1", "faq"} <= set(chosen)
    assert chosen == webpages.sample(pages, seed=1)


def test_the_command_line_writes_the_audit_and_the_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "products__render__duro.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "news__day.html").write_text(FLAT, encoding="utf-8")
    monkeypatch.setattr(config, "PAGE_CACHE", tmp_path)

    assert cli.main(["web-audit", "--out", str(tmp_path / "a.json")]) == 0
    assert (
        cli.main(["web-sample", "--seed", "3", "--out", str(tmp_path / "s.json")]) == 0
    )

    assert json.loads((tmp_path / "a.json").read_text())["total"]["passages"] == 3
    rows = json.loads((tmp_path / "s.json").read_text())
    assert {r["type"] for r in rows} == {"product", "news"}

    (tmp_path / "products__render__ultra.html").write_text(PAGE, encoding="utf-8")
    held = ["web-sample", "--seed", "4", "--held-out", str(tmp_path / "s.json")]
    assert cli.main([*held, "--out", str(tmp_path / "h.json")]) == 0
    rows = json.loads((tmp_path / "h.json").read_text())
    assert rows == [{"slug": "products__render__ultra", "type": "product"}]


class Route:
    def __init__(self, url: str) -> None:
        self.request = type("Request", (), {"url": url})()
        self.done = ""

    def fulfill(self, body: str, content_type: str) -> None:
        self.done = f"cached {len(body)}"

    def continue_(self) -> None:
        self.done = "loaded"

    def abort(self) -> None:
        self.done = "blocked"


class Button:
    clicked = 0

    def is_visible(self) -> bool:
        return True

    def click(self) -> None:
        Button.clicked += 1


class Answer:
    def __init__(self, shown: bool) -> None:
        self.shown = shown
        self.marked = False

    def is_visible(self) -> bool:
        return self.shown

    def evaluate(self, script: str) -> None:
        self.marked = True


class Term:
    """An accordion term: clicking it opens its answer, or (`opens` false) not."""

    def __init__(self, answer: Answer, opens: bool) -> None:
        self.answer = answer
        self.opens = opens

    def is_visible(self) -> bool:
        return True

    def locator(self, selector: str) -> Answer:
        return self.answer

    def click(self) -> None:
        self.answer.shown = self.opens


class Page:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.terms = [
            Term(Answer(shown=False), opens=True),
            Term(Answer(shown=True), opens=True),
            Term(Answer(shown=False), opens=False),
        ]

    def route(self, pattern: str, handler: object) -> None:
        self.handler = handler

    def get_by_role(self, role: str, name: str) -> object:
        return type("Found", (), {"all": lambda self: [Button()]})()

    def locator(self, selector: str) -> object:
        terms = self.terms
        return type("Found", (), {"all": lambda self: terms})()

    def goto(self, url: str, wait_until: str) -> None:
        self.calls.append(url)

    def evaluate(self, script: str) -> object:
        return 1000 if "scrollHeight" in script else "Duro base coat"

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def screenshot(self, path: str, full_page: bool) -> None:
        Path(path).write_bytes(b"png")

    def close(self) -> None:
        pass


class Browser:
    def __init__(self) -> None:
        self.page = Page()

    def new_page(self, viewport: dict[str, int]) -> Page:
        return self.page

    def close(self) -> None:
        pass


def test_rendering_serves_the_cache_loads_assets_and_blocks_trackers() -> None:
    handle = webpages.router({"https://www.lime-green.co.uk/duro": "<html></html>"})
    routes = [
        Route("https://www.lime-green.co.uk/duro"),
        Route("https://www.lime-green.co.uk/css/site.css"),
        Route("https://cdnjs.cloudflare.com/ajax/libs/gsap.min.js"),
        Route("https://www.googletagmanager.com/gtag/js"),
        Route("https://websiteintegration.source.thenbs.com/widget"),
    ]
    for route in routes:
        handle(route)

    assert [r.done for r in routes] == [
        "cached 13", "loaded", "loaded", "blocked", "blocked"
    ]  # fmt: skip


def test_each_page_is_revealed_drawn_and_its_visible_text_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "REQUEST_DELAY_SECONDS", 0)
    browser = Browser()

    counts = webpages.render(["home"], {"home": PAGE}, tmp_path / "out", browser)

    assert counts == {"home": 3}
    assert browser.page.calls == [config.SITE]
    assert (tmp_path / "out" / "home.txt").read_text() == "Duro base coat"
    assert (tmp_path / "out" / "home.png").exists() and Button.clicked >= 1
    # only the hidden answer that opened on a click is shown with the others
    assert [term.answer.marked for term in browser.page.terms] == [True, False, False]


def test_the_command_line_renders_a_sample_in_chromium(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import playwright.sync_api

    class Playwright:
        chromium = type("Chromium", (), {"launch": lambda self: Browser()})()

        def __enter__(self) -> "Playwright":
            return self

        def __exit__(self, *args: object) -> None:
            pass

    (tmp_path / "news__day.html").write_text(FLAT, encoding="utf-8")
    (tmp_path / "s.json").write_text(json.dumps([{"slug": "news__day"}]))
    monkeypatch.setattr(config, "PAGE_CACHE", tmp_path)
    monkeypatch.setattr(config, "REQUEST_DELAY_SECONDS", 0)
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", Playwright)
    out = tmp_path / "render"

    assert cli.main(["web-render", str(tmp_path / "s.json"), "--out", str(out)]) == 0
    assert (out / "news__day.txt").exists()


SHOWN = "\n".join(
    [
        "News",
        "  ",
        "Duro",
        "Uses",
        "Repointing",
        "More products >",
        "Rendering",
        "Mixing",
        "Add water slowly.",
        "Order the brochure",
    ]
)
OUTLINE = {
    "title": 1,
    "blocks": [
        ["meta", 0, 0],
        ["h", 2, 2],
        ["list", 3, 5, 2],
        ["h", 3, 6],
        ["p", 7, 7],
        ["alt", "A wall pointed with Duro lime mortar"],
        ["end", 2],
        ["p", 8, 8],
    ],
}


def test_an_outline_over_the_visible_lines_gives_blocks_with_section_paths() -> None:
    lines = webpages.visible_lines(SHOWN)

    truth = webpages.build_truth(OUTLINE, lines)

    assert len(lines) == 9 and webpages.outline_problems(OUTLINE, len(lines)) == []
    assert truth["title"] == "Duro"
    assert truth["headings"] == [
        {"level": 2, "text": "Uses"}, {"level": 3, "text": "Mixing"}
    ]  # fmt: skip
    assert truth["blocks"] == [
        {"kind": "meta", "text": "News", "path": []},
        {"kind": "list", "items": ["Repointing", "Rendering"], "path": ["Uses"]},
        {"kind": "p", "text": "Add water slowly.", "path": ["Uses", "Mixing"]},
        {
            "kind": "alt",
            "text": "A wall pointed with Duro lime mortar",
            "path": ["Uses", "Mixing"],
        },
        {"kind": "p", "text": "Order the brochure", "path": []},
    ]


def test_outline_slips_are_reported() -> None:
    slipped = {
        "title": 9,
        "blocks": [["p", 3, 4], ["h", 2, 4], ["list", 9, 11]],
    }

    assert webpages.outline_problems(slipped, 10) == [
        "line 10 beyond the page",
        "line 11 beyond the page",
        "line 4 after line 4",
        "title line 9 used again",
    ]


def test_the_command_line_writes_the_truth_and_keeps_the_visible_text(
    tmp_path: Path,
) -> None:
    render = tmp_path / "render"
    render.mkdir()
    (render / "duro.txt").write_text(SHOWN, encoding="utf-8")
    (render / "ochre.txt").write_text("Ochre", encoding="utf-8")
    outlines = tmp_path / "set" / "outlines"
    outlines.mkdir(parents=True)
    (outlines / "duro.json").write_text(json.dumps(OUTLINE))
    (outlines / "ochre.json").write_text(json.dumps({"title": 0, "blocks": []}))
    command = ["web-truth", str(render), "--set", str(tmp_path / "set")]

    assert cli.main(command) == 0
    truth = json.loads((tmp_path / "set" / "truth.json").read_text())
    assert sorted(truth) == ["duro", "ochre"]
    assert (tmp_path / "set" / "visible" / "duro.txt").read_text() == SHOWN

    (outlines / "ochre.json").write_text(json.dumps({"title": 3, "blocks": []}))
    (tmp_path / "set" / "truth.json").unlink()
    assert cli.main(command) == 1
    assert not (tmp_path / "set" / "truth.json").exists()


def test_words_fold_case_typography_and_compatibility_forms() -> None:
    assert webpages.tokens("Lime Green’s 25 kg – CO²") == [
        "lime", "green", "s", "25", "kg", "co2"
    ]  # fmt: skip
    assert webpages.squash("Add water, slowly.") == "addwaterslowly"


def test_the_current_extractor_reads_each_section_under_its_one_heading() -> None:
    reading = webpages.current_reading(PAGE)

    assert reading["title"] == "Duro"
    assert reading["headings"] == ["Uses", "Mixing"]
    assert [s["path"] for s in reading["sections"]] == [["Uses"], ["Mixing"]]
    # text right under the title: its section's heading is the title, not a heading
    assert webpages.current_reading(FLAT)["headings"] == []


def test_docling_reads_html_only() -> None:
    from docling.datamodel.base_models import InputFormat

    assert webpages.docling_converter().allowed_formats == [InputFormat.HTML]


MARKDOWN = """Knowledge base

# Duro

A base coat.

## Uses

- 
**Repointing** : brick
- Rendering
continued here

<!-- image -->

### Mixing
#1 rule: add water
## Colours
- Ochre"""


def test_markdown_is_read_as_headings_with_levels_and_texts_under_them() -> None:
    reading = webpages.markdown_reading(MARKDOWN)

    assert reading["title"] == "Duro"
    assert reading["headings"] == ["Uses", "Mixing", "Colours"]
    assert reading["sections"] == [
        {"path": [], "texts": ["Knowledge base", "A base coat."]},
        {
            "path": ["Uses"],
            "texts": ["**Repointing** : brick", "Rendering continued here"],
        },
        {"path": ["Uses", "Mixing"], "texts": ["#1 rule: add water"]},
        {"path": ["Colours"], "texts": ["Ochre"]},
    ]


def test_docling_and_trafilatura_readings_come_through_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import trafilatura

    class Converter:
        def convert(self, source: object) -> object:
            self.source = source
            document = type("Document", (), {"export_to_markdown": lambda s: MARKDOWN})
            return type("Result", (), {"document": document()})()

    asked = {}

    def extract(raw: str, output_format: str) -> str | None:
        asked["format"] = output_format
        return None if "empty" in raw else MARKDOWN

    monkeypatch.setattr(trafilatura, "extract", extract)

    assert webpages.docling_reading(PAGE, Converter())["title"] == "Duro"
    assert webpages.trafilatura_reading(PAGE)["headings"][0] == "Uses"
    assert webpages.trafilatura_reading("empty")["sections"] == []
    assert asked["format"] == "markdown"


TRUTH_PAGE = {
    "title": "Duro",
    "headings": [{"level": 2, "text": "Uses"}, {"level": 3, "text": "Mixing"}],
    "blocks": [
        {"kind": "meta", "text": "Knowledge base", "path": []},
        {"kind": "p", "text": "A base coat.", "path": []},
        {"kind": "list", "items": ["Repointing", "Rendering"], "path": ["Uses"]},
        {"kind": "p", "text": "Add water slowly.", "path": ["Uses", "Mixing"]},
        {"kind": "p", "text": "Keep it damp for days.", "path": ["Uses", "Mixing"]},
        {"kind": "alt", "text": "A wall pointed with Duro", "path": []},
    ],
}
READING = {
    "title": "Duro",
    "headings": ["Mixing", "Extra"],
    "sections": [
        {"path": ["Duro"], "texts": ["Knowledge base A base coat. Repointing"]},
        {
            "path": ["Uses", "Mixing"],
            "texts": ["Rendering", "Add water", "slowly. Menu"],
        },
    ],
}


def test_a_reading_is_scored_against_the_page_truth() -> None:
    found = webpages.page_score(TRUTH_PAGE, READING)

    # Words: 18 shown, 14 kept; "extra" and "menu" are not on the page, the alt
    # text's words would have counted as right. The list is split between two
    # sections and goes to the first of the tied ones (path "Duro": wrong); "Add
    # water slowly." is held under both its headings; "Keep it damp" is lost.
    assert found == {
        "words": 18,
        "found": 12,
        "kept": 14,
        "right": 12,
        "headings": 2,
        "headings_found": 1,
        "tested": 3,
        "placed": 1,
        "lists": 1,
        "lists_whole": 0,
        "alts": 1,
        "alts_kept": 0,
    }
    scored = webpages.scores({"duro": TRUTH_PAGE}, {"duro": READING})
    assert scored["rates"]["recall"] == 12 / 18
    assert scored["rates"]["section_paths"] == 1 / 3


def test_a_block_is_held_by_the_section_holding_its_text_or_most_of_its_words() -> None:
    sections = [
        {"path": ["Uses"], "texts": ["Add water"]},
        {"path": ["Mixing"], "texts": ["water slowly then mix"]},
    ]

    assert webpages.holder("Mix", sections) == sections[1]
    assert webpages.holder("Add water slowly then", sections) == sections[1]
    assert webpages.holder("Add water slowly", sections) == sections[0]  # a tie
    assert webpages.holder("Ochre", sections) is None
    assert webpages.in_order(["a", "c"], "abc") and not webpages.in_order(
        ["c", "a"], "abc"
    )


def test_the_command_line_scores_each_arm_on_the_registered_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trafilatura

    (tmp_path / "products__render__duro.html").write_text(PAGE, encoding="utf-8")
    monkeypatch.setattr(config, "PAGE_CACHE", tmp_path)
    folder = tmp_path / "eval" / "web-pages"
    folder.mkdir(parents=True)
    truth = {"products__render__duro": TRUTH_PAGE}
    (folder / "truth.json").write_text(json.dumps(truth))
    registry = tmp_path / "sets.json"
    sets.register("web-pages", "", tmp_path / "eval", registry)

    class Converter:
        def convert(self, source: object) -> object:
            document = type("Document", (), {"export_to_markdown": lambda s: MARKDOWN})
            return type("Result", (), {"document": document()})()

    monkeypatch.setattr(webpages, "docling_converter", Converter)
    monkeypatch.setattr(trafilatura, "extract", lambda raw, output_format: MARKDOWN)
    common = ["--root", str(tmp_path / "eval"), "--registry", str(registry)]

    for arm in webpages.ARMS:
        out = tmp_path / f"{arm}.json"
        assert cli.main([*common, "web-score", arm, "--out", str(out)]) == 0
        saved = json.loads(out.read_text())
        assert set(saved) == {"rates", "total", "pages", "readings"}


def test_a_truth_is_corrected_by_the_card_rule_as_a_new_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    listing = """<main><h1>Products</h1><div class="cardbox">
    <article class="card"><a class="portal-item" href="/silic8">
    <h1 class="title">Silic8</h1><div class="desc">We use no acrylics.</div></a>
    </article>
    <article class="card"><a class="portal-item" href="/duro">
    <h1 class="title">Duro</h1><div class="desc">A base coat.</div></a></article>
    <article class="card"><a class="portal-item" href="/solo">
    <h1 class="title">Solo</h1></a></article>
    </div></main>"""
    duro = "<main><h1>Duro</h1><p>A base coat.</p></main>"
    (tmp_path / "products.html").write_text(listing, encoding="utf-8")
    (tmp_path / "products__duro.html").write_text(duro, encoding="utf-8")
    monkeypatch.setattr(config, "PAGE_CACHE", tmp_path)
    folder = tmp_path / "eval" / "web-pages"
    folder.mkdir(parents=True)
    names = {"kind": "list", "items": ["Silic8", "Duro", "Solo"], "path": []}
    page = {"title": "Products", "headings": [], "blocks": [names]}
    other = {"title": "Duro", "headings": [], "blocks": [{"kind": "p", "text": "x"}]}
    truth = {"products": page, "products__duro": other}
    (folder / "truth.json").write_text(json.dumps(truth))
    registry = tmp_path / "sets.json"
    sets.register("web-pages", "", tmp_path / "eval", registry)
    common = ["--root", str(tmp_path / "eval"), "--registry", str(registry)]
    out = tmp_path / "eval" / "web-pages-v2"

    command = [*common, "web-truth-cards", "--set", "web-pages", "--out-set", str(out)]
    assert cli.main(command) == 0

    found = json.loads((out / "truth.json").read_text())
    assert found["products"]["blocks"][0]["items"] == [
        "Silic8",
        "We use no acrylics.",  # no other page holds it
        "Duro",
        "Solo",
    ]
    assert "2 pages, 1 card descriptions added" in capsys.readouterr().out
    reading = webpages.fixed_reading(listing, webpages.site_held(webpages_pages()))
    assert reading["sections"][0]["texts"][:2] == ["Silic8", "We use no acrylics."]


def webpages_pages() -> dict[str, str]:
    return {"duro": "<main><h1>Duro</h1><p>A base coat.</p></main>"}


def holder_texts() -> dict[str, str]:
    """Two site pages' text by URL: the fact's own page and one repeating a part."""
    return {
        "https://www.lime-green.co.uk/duro": "A base coat. Repointing Rendering",
        "https://www.lime-green.co.uk/other": "Repointing and Rendering",
    }


def test_facts_are_asked_by_title_and_headings_with_their_holder_pages() -> None:
    items = webpages.fact_items({"duro": TRUTH_PAGE}, holder_texts())

    assert [item["question"] for item in items] == [
        "What does the Duro page say?",
        "What does the Duro page say about Uses?",
        "What does the Duro page say about Uses › Mixing?",
        "What does the Duro page say about Uses › Mixing?",
    ]
    assert items[0]["evidence"] == ["A base coat."]
    assert items[1]["evidence"] == ["Repointing", "Rendering"]
    assert len(items[1]["holders"]) == 2 and items[2]["holders"] == []


def test_a_fact_is_found_in_a_holder_page_passage_quoting_its_evidence() -> None:
    from limespec.models import Passage

    item = webpages.fact_items({"duro": TRUTH_PAGE}, holder_texts())[1]
    other = "https://www.lime-green.co.uk/other"
    elsewhere = Passage(
        1, "https://example.test/x", "X", "", "Repointing Rendering", ""
    )
    held = Passage(2, other, "Other", "", "Uses\nRepointing\nRendering", "")

    found = webpages.fact_result(item, [elsewhere, held], [held])

    assert found["success"] == 1.0 and found["reciprocal"] == 0.5
    assert found["ceiling"] == 1.0
    missed = webpages.fact_result(item, [elsewhere], [])
    assert (missed["success"], missed["reciprocal"], missed["ceiling"]) == (0, 0, 0)


def test_the_command_line_builds_web_facts_and_scores_and_compares_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    from limespec import assistant, store
    from limespec.models import Passage

    (tmp_path / "duro.html").write_text(PAGE, encoding="utf-8")
    monkeypatch.setattr(config, "PAGE_CACHE", tmp_path)
    root = tmp_path / "eval"
    (root / "web-pages").mkdir(parents=True)
    mixing = {"kind": "p", "text": "Mix well.", "path": ["Uses", "Mixing"]}
    truth = {"duro": TRUTH_PAGE | {"blocks": [mixing]}}
    (root / "web-pages" / "truth.json").write_text(json.dumps(truth))
    registry = tmp_path / "sets.json"
    sets.register("web-pages", "", root, registry)
    common = ["--root", str(root), "--registry", str(registry)]

    assert cli.main([*common, "web-facts", "--out-set", str(root / "web-facts")]) == 0
    assert "1 facts" in capsys.readouterr().out
    sets.register("web-facts", "", root, registry)

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    url = "https://www.lime-green.co.uk/duro"
    rows = [Passage(1, url, "Duro", "Mixing", "Mixing\nMix well.", "")]
    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "search", lambda conn, version, question, e, r: rows)
    monkeypatch.setattr(store, "document_passages", lambda conn, version, url: rows)
    monkeypatch.setattr(store, "passage_count", lambda conn, version: 3)
    run = tmp_path / "run.json"

    command = [*common, "web-retrieval", "--version", "18", "--out", str(run)]
    assert cli.main(command) == 0
    saved = json.loads(run.read_text())
    assert saved["passages"] == 3 and saved["summary"]["success"] == 1.0
    assert cli.main(["web-compare", str(run), str(run)]) == 0
    assert "difference +0.000" in capsys.readouterr().out


def test_a_file_scoring_several_sets_is_compared_on_the_named_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = {"id": "t1", "set": "x9-tables", "cluster": "a", "success": 1.0}
    summary = {"x9-tables": {"success": 1.0}, "conv-v1": {"success": 0.5}}
    run = tmp_path / "lookups.json"
    run.write_text(json.dumps({"summary": summary, "results": [result]}))

    assert cli.main(["web-compare", str(run), str(run), "--set", "x9-tables"]) == 0
    assert "Success@8 1.000 vs 1.000" in capsys.readouterr().out


def test_a_customer_link_must_be_an_online_source_the_rendered_page_holds() -> None:
    shown = "Uses\nRepointing brick\nRendering"
    good = "https://www.lime-green.co.uk/duro#:~:text=Uses,Rendering"

    assert webpages.link_problems(good, shown) == []
    assert webpages.link_problems(good, None) == []
    assert webpages.link_problems(
        "https://www.lime-green.co.uk/duro#:~:text=Rendering,Uses", shown
    ) == ["a text directive the rendered page does not hold"]
    assert webpages.link_problems(
        "https://www.lime-green.co.uk/duro#:~:text=Plaster", shown
    ) == ["a text directive the rendered page does not hold"]
    assert webpages.link_problems("http://example.test/a b.pdf#page=2", None) == [
        "not an online source address",
        "a character an address cannot hold",
    ]


def test_the_command_line_checks_every_passage_link_of_a_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    from limespec import assistant, store
    from limespec.models import Passage

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    site = "https://www.lime-green.co.uk/"
    rows = [
        Passage(1, site + "duro", "Duro", "Uses", "Uses\nRepointing brick", ""),
        Passage(2, site + "Documents/a b.pdf", "A", "", "Lime", "", 3),
        Passage(3, site + "duro", "Duro", "Image", "", "", image="p"),  # no words
    ]
    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "searchable_passages", lambda conn, version: rows)
    render = tmp_path / "render"
    render.mkdir()
    (render / "duro.txt").write_text("Uses\nRepointing", encoding="utf-8")
    out = tmp_path / "links.json"

    command = ["web-links", "--version", "18", "--rendered", str(render)]
    assert cli.main([*command, "--out", str(out)]) == 0
    saved = json.loads(out.read_text())
    assert saved["links"] == 4
    assert [p["problem"] for p in saved["problems"]] == [
        "a text directive the rendered page does not hold"
    ]
    assert "4 links from 3 passages" in capsys.readouterr().out
