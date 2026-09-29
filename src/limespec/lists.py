"""Product lists compiled from a page's own product grid (X12, S2 round 2).

A range or colour page shows its products as cards in a grid (`.product-list`). Read as
text, the cards become separate sections, so no single passage holds the whole list and
a question such as "which mortars come in this colour?" is answered from fragments. The
index therefore gets one passage per grid: every card's title, in page order, in the
site's own names. Nothing is interpreted: a product is a card and its name is the
card's title.

The passage is compiled, not copied: its sentence is not on the page. Its heading says
so to every reader of the passage, and a claim quoting it links to the page itself,
since a highlight of the compiled sentence would find nothing there.
"""

from collections.abc import Sequence

from bs4 import BeautifulSoup

GRID = ".product-list"
HEADING = "Products listed on this page (compiled from its product cards)"


def grid_products(raw_html: str) -> list[str]:
    """The product names in a page's product grid, in page order."""
    soup = BeautifulSoup(raw_html, "html.parser")
    root = soup.find("main") or soup.body
    grid = root.select_one(GRID) if root else None
    if grid is None:
        return []
    names = []
    for card in grid.select("article"):
        title = card.select_one("h1, h2, h3")
        if title is not None and title.get_text(strip=True):
            names.append(" ".join(title.get_text().split()))
    return names


def list_passage(title: str, products: Sequence[str]) -> str:
    """One passage stating a page's whole product list; its first line is the heading,
    as in every web passage."""
    return f"{HEADING}\nThe {title} page lists these products: {'; '.join(products)}."
