"""Index versions made for experiments (E5 model arms).

`embedded_again` copies an index version's documents and passages into a new version,
not live, whose vectors come from another embedding model. The words, sections and
keyword index are the same, so a replay on the copy differs from one on the original
only in the vector ranking.
"""

from collections.abc import Callable

from limespec import config, store
from limespec.models import described

Embed = Callable[[list[str]], list[list[float]]]


def embedded_again(
    conn: store.Connection, version_id: int, embed: Embed, model: str
) -> int:
    """A new version holding `version_id`'s passages with vectors from `embed`,
    recorded as made by `model`; returns its id."""
    found = conn.execute(
        "SELECT corpus_sha256, passages_sha256 FROM index_versions WHERE id = %s",
        (version_id,),
    ).fetchone()
    if found is None:
        raise ValueError(f"no index version {version_id}")
    rows = conn.execute(
        "SELECT d.url, d.title, d.fetched_at, d.sha256, "
        "p.title, p.heading, p.text, p.context, p.page "
        "FROM passages p JOIN documents d ON d.id = p.document_id "
        "WHERE p.index_version_id = %s ORDER BY p.id",
        (version_id,),
    ).fetchall()
    pages = sorted(
        {(url, title, fetched, sha) for url, title, fetched, sha, *_ in rows}
    )
    passages = [(row[0], *row[4:]) for row in rows]
    texts = [
        described(title, context, text) for _, title, _, text, context, _ in passages
    ]
    vectors: list[list[float]] = []
    for start in range(0, len(texts), config.EMBEDDING_BATCH_SIZE):
        vectors += embed(texts[start : start + config.EMBEDDING_BATCH_SIZE])
    manifest = {
        "corpus_sha256": found[0],
        "passages_sha256": found[1],
        "embedding_model": model,
    }
    return store.write_version(conn, pages, passages, vectors, manifest)
