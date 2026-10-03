"""Pictures found by what they show (X43 B3, arms T+S), with SigLIP2's encoders
(`limespec.siglip`). The picture ranking joins search in one of two places (amendment
2): `pool` fuses it with the keyword and vector rankings before the reranker; `quota`
keeps the reranked top places and adds the best pictures not among them, as
UniDoc-Bench's text-image fusion splits its results.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from limespec import answer, config
from limespec.models import Passage
from limespec.siglip import Vectors

QUOTA = 2  # of the 8 places: UniDoc-Bench's 5 of 10, scaled
# B4's serving check: replayed text requests answered with and without the projector,
# and image requests carrying up to PER_REQUEST pictures each.
TEXT_REQUESTS = 10
IMAGE_REQUESTS = 20
PER_REQUEST = 4


def picture_ranking(
    question_vector: list[float], vectors: Vectors, by_picture: dict[str, int]
) -> list[int]:
    """The passages of the pictures `by_picture` holds (picture id -> passage id),
    best match first; ties by passage id."""
    scores = {
        passage: sum(
            a * b for a, b in zip(question_vector, vectors[picture], strict=True)
        )
        for picture, passage in by_picture.items()
    }
    return sorted(scores, key=lambda passage: (-scores[passage], passage))


def with_quota(
    ranked: list[Passage], pictures: list[Passage], quota: int = QUOTA
) -> list[Passage]:
    """The reranked passages' first `config.TOP_K - quota`, then the best `quota`
    pictures not already among them, then the rest of the reranked passages."""
    kept = ranked[: config.TOP_K - quota]
    held = {passage.id for passage in kept}
    added = [passage for passage in pictures if passage.id not in held][:quota]
    held.update(passage.id for passage in added)
    return kept + added + [passage for passage in ranked if passage.id not in held]


def serving_requests(
    replay: Mapping[str, list[dict[str, Any]]],
    items: Sequence[Mapping[str, Any]],
    places: Sequence[Mapping[str, Any]],
    folder: Path,
) -> dict[str, list[dict[str, Any]]]:
    """B4's requests: the replay's warm-up, its first TEXT_REQUESTS (compared with
    and without the projector), then IMAGE_REQUESTS `image-facts` questions, each an
    answer request over its picture and the next ones' alt texts, with those
    pictures attached (PER_REQUEST at most)."""
    alts: dict[str, Mapping[str, Any]] = {}
    for place in places:
        if len(place["alt"]) >= len(alts.get(place["id"], {"alt": ""})["alt"]):
            alts[place["id"]] = place
    pictures = [item["picture"] for item in items]
    requests = list(replay["requests"][:TEXT_REQUESTS])
    for number, item in enumerate(items[:IMAGE_REQUESTS]):
        chosen = [pictures[(number + n) % len(pictures)] for n in range(PER_REQUEST)]
        sources = {
            f"S{n}": Passage(n, alts[p]["source"], "", "Image", alts[p]["alt"], "")
            for n, p in enumerate(chosen, 1)
        }
        requests.append(
            {
                "id": f"image-{item['id']}",
                "system": answer.ANSWER_PROMPT,
                "user": answer.user_prompt([item["question"]], sources),
                "schema": answer.answer_schema(list(sources), 1),
                "images": [str(folder / f"{p}.png") for p in chosen],
            }
        )
    return {"warm_up": replay["warm_up"], "requests": requests}
