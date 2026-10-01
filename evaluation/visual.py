"""Pictures found by what they show (X43 B3, arms T+S): SigLIP2 so400m on the CPU.

Used as its model card shows: pictures through its processor (384 px), text padded to
64 tokens and lowercased (SigLIP2 was trained on lowercased text, and this checkpoint's
Gemma tokenizer does not lowercase). Vectors are normalised, so a dot product is the
cosine. The picture ranking joins search in one of two places (amendment 2): `pool`
fuses it with the keyword and vector rankings before the reranker; `quota` keeps the
reranked top places and adds the best pictures not among them, as UniDoc-Bench's
text-image fusion splits its results.
"""

from collections.abc import Callable
from pathlib import Path

from limespec import config
from limespec.models import Passage

SIGLIP = Path("models/siglip2-so400m-patch14-384")
QUOTA = 2  # of the 8 places: UniDoc-Bench's 5 of 10, scaled
TEXT_TOKENS = 64
BATCH = 8
Vectors = dict[str, list[float]]
EmbedPictures = Callable[[list[Path]], list[list[float]]]
EmbedTexts = Callable[[list[str]], list[list[float]]]


def siglip_model(folder: Path) -> tuple[EmbedPictures, EmbedTexts]:
    """The model's picture and text encoders, each returning unit vectors."""
    import torch
    from PIL import Image
    from transformers import AutoModel, AutoProcessor

    model = AutoModel.from_pretrained(folder).eval()
    processor = AutoProcessor.from_pretrained(folder)  # type: ignore[no-untyped-call]

    def unit(found: torch.Tensor) -> list[list[float]]:
        vectors: list[list[float]] = (found / found.norm(dim=-1, keepdim=True)).tolist()
        return vectors

    def pictures(paths: list[Path]) -> list[list[float]]:
        images = [Image.open(path).convert("RGB") for path in paths]
        batch = processor(images=images, return_tensors="pt")
        with torch.no_grad():
            return unit(model.get_image_features(**batch).pooler_output)

    def texts(found: list[str]) -> list[list[float]]:
        batch = processor(
            text=[text.lower() for text in found],
            padding="max_length",
            max_length=TEXT_TOKENS,
            truncation=True,
            return_tensors="pt",
        )
        with torch.no_grad():
            return unit(model.get_text_features(**batch).pooler_output)

    return pictures, texts


def picture_vectors(
    ids: list[str], folder: Path, embed: EmbedPictures, known: Vectors
) -> Vectors:
    """Every picture's vector, from `known` when it holds the picture (a run resumes),
    else embedded from `folder/<id>.png` in batches."""
    found = {identity: known[identity] for identity in ids if identity in known}
    left = [identity for identity in ids if identity not in found]
    for start in range(0, len(left), BATCH):
        batch = left[start : start + BATCH]
        paths = [folder / f"{identity}.png" for identity in batch]
        found.update(zip(batch, embed(paths), strict=True))
    return found


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
