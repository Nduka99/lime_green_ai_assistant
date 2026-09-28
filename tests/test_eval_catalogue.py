"""Labelling collected sources by format and topic. Every page and file is invented."""

import json
from pathlib import Path

import pytest

from evaluation import __main__ as cli
from evaluation import catalogue
from limespec import acquire, config

SITE = "https://example.test/"


@pytest.mark.parametrize(
    ("slug", "fmt", "topic"),
    [
        ("products__lime-render__duro", "page:product", "lime-render"),
        ("products", "page:product", "company"),
        ("warmshell-natural-insulation__about", "page:product", "insulation"),
        ("products-by-colour__ochre", "page:colour", "colours"),
        ("support__case-studies__tower", "page:case-study", "case-studies"),
        ("support__knowledgebase__breathability", "page:knowledge", "building-science"),
        ("support__faq", "page:knowledge", "faq"),
        ("news__plastic", "page:news", "news"),
        ("inspirations__kitchens", "page:news", "news"),
        ("about-lime-green", "page:company", "company"),
    ],
)
def test_a_page_is_labelled_from_its_url_path(slug: str, fmt: str, topic: str) -> None:
    assert (catalogue.page_format(slug), catalogue.page_topic(slug)) == (fmt, topic)


@pytest.mark.parametrize(
    ("texts", "url", "fmt"),
    [
        (["SDS"], SITE + "d/x.pdf", "pdf:safety"),
        (["UK DoC"], SITE + "d/x.pdf", "pdf:performance"),
        (["Data Sheet"], SITE + "d/x.pdf", "pdf:technical"),
        ([""], SITE + "d/Installation%20Guide%20-%20IWI.pdf", "pdf:guide"),
        ([], SITE + "d/IWI%20Architect%20Reference.pdf", "pdf:guide"),
        ([], SITE + "d/BAW-22-242-S-A-UK%202024.pdf", "pdf:certificate"),
        ([], SITE + "d/warmshell-warranty.pdf", "pdf:policy"),
        (["Download"], SITE + "d/leaflet.pdf", "pdf:other"),
    ],
)
def test_a_pdf_is_labelled_by_its_link_text_then_its_name(
    texts: list[str], url: str, fmt: str
) -> None:
    assert catalogue.pdf_format(texts, url) == fmt


def test_a_file_belongs_to_the_product_family_that_links_it() -> None:
    assert catalogue.file_topic(["faq", "lime-render"]) == "lime-render"
    assert catalogue.file_topic(["news", "case-studies"]) == "news"
    assert catalogue.file_topic([]) == "unknown"


@pytest.fixture
def collected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A page cache and file store: a product page and a case study sharing an image,
    a datasheet, an external document, and one file stored under two URLs."""
    monkeypatch.setattr(config, "SITE", SITE)
    monkeypatch.setattr(config, "PAGE_CACHE", tmp_path / "site")
    monkeypatch.setattr(config, "FILE_STORE", tmp_path / "files")
    config.PAGE_CACHE.mkdir()
    (config.PAGE_CACHE / "products__lime-render__duro.html").write_text(
        '<a href="/d/duro.pdf">SDS</a><img src="/i/wall.webp" alt="A rendered wall">'
    )
    (config.PAGE_CACHE / "support__case-studies__tower.html").write_text(
        '<img src="/i/wall.webp" alt="">'
    )
    acquire.write_manifest(
        [
            {"url": SITE + "d/duro.pdf", "kind": "document", "sha256": "a" * 64},
            {"url": SITE + "d/duro-copy.pdf", "kind": "document", "sha256": "a" * 64},
            {"url": SITE + "i/wall.webp", "kind": "image", "sha256": "b" * 64},
            {"url": "https://gov.test/g.pdf", "kind": "external", "sha256": "c" * 64},
        ]
    )
    return tmp_path


def test_every_page_and_file_is_labelled_once(collected: Path) -> None:
    entries = {entry["id"]: entry for entry in catalogue.catalogue()}

    assert len(entries) == 5  # 2 pages and 3 distinct files
    datasheet = entries["file:" + "a" * 64]
    assert (datasheet["format"], datasheet["topic"]) == ("pdf:safety", "lime-render")
    assert datasheet["text"] == "SDS"
    image = entries["file:" + "b" * 64]
    assert (image["format"], image["topic"]) == ("image", "lime-render")
    assert image["text"] == "A rendered wall"
    external = entries["file:" + "c" * 64]
    assert (external["format"], external["topic"]) == (
        "external:guidance",
        "regulation",
    )
    assert catalogue.strata(list(entries.values())) == {
        "external:guidance": 1,
        "image": 1,
        "page:case-study": 1,
        "page:product": 1,
        "pdf:safety": 1,
    }


def test_the_command_line_writes_the_catalogue_and_its_strata(
    collected: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = collected / "catalogue.json"

    assert cli.main(["catalogue", "--out", str(out)]) == 0

    assert len(json.loads(out.read_text())) == 5
    printed = capsys.readouterr().out
    assert "    1  pdf:safety" in printed
    assert printed.endswith(f"5 sources labelled in {out}\n")
