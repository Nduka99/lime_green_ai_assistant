"""X42: the web audit and the ground-truth sample. Invented pages."""

import json
from pathlib import Path

import pytest

from evaluation import __main__ as cli
from evaluation import webpages
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


class Page:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def route(self, pattern: str, handler: object) -> None:
        self.handler = handler

    def get_by_role(self, role: str, name: str) -> object:
        return type("Found", (), {"all": lambda self: [Button()]})()

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
