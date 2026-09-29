"""Product lists compiled from a page's product grid (X12). Invented pages only."""

from limespec import lists
from limespec.ingest import prepare_index
from limespec.retrieve import Embed

GRID_PAGE = """<html><body><main>
<h1>Cinders</h1>
<p>A warm grey colour.</p>
<div class="product-list">
  <article><h2>Ashlar  Lime Mortar</h2><p>For fine joints.</p></article>
  <article><h3>Contour Repair</h3></article>
  <article><p>A card with no title.</p></article>
  <article><h2> </h2></article>
</div>
</main></body></html>"""


def test_a_grid_lists_every_titled_card_in_page_order() -> None:
    assert lists.grid_products(GRID_PAGE) == ["Ashlar Lime Mortar", "Contour Repair"]
    assert lists.grid_products("<html><body><p>No grid.</p></body></html>") == []
    assert lists.grid_products("<html></html>") == []


def test_the_compiled_passage_says_it_is_compiled_and_names_the_page() -> None:
    text = lists.list_passage("Cinders", ["Ashlar Lime Mortar", "Contour Repair"])

    assert text == (
        f"{lists.HEADING}\nThe Cinders page lists these products: "
        "Ashlar Lime Mortar; Contour Repair."
    )


def test_a_page_with_a_grid_gets_one_compiled_list_passage(fake_embed: Embed) -> None:
    url = "https://example.test/products-by-colour/cinders"
    plain = "<html><body><main><h1>Plain</h1><p>No grid here.</p></main></body></html>"
    pages = [(url, GRID_PAGE.encode(), "2026-09-29T10:00:00+00:00"),
             ("https://example.test/plain", plain.encode(),
              "2026-09-29T10:00:00+00:00")]  # fmt: skip

    prepared = prepare_index(pages, fake_embed)

    compiled = [row for row in prepared.passages if row[2] == lists.HEADING]
    assert compiled == [(url, "Cinders", lists.HEADING,
                         lists.list_passage("Cinders", ["Ashlar Lime Mortar",
                                                        "Contour Repair"]),
                         "", None)]  # fmt: skip
    assert len(prepared.vectors) == len(prepared.passages)
