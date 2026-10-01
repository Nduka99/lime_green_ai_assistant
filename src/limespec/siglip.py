"""Pictures ranked by what they show: SigLIP2 so400m on the CPU (X43 B3, X44 F2).

Used as its model card shows: pictures through its processor (384 px), text padded to
SIGLIP_TEXT_TOKENS tokens and lowercased (SigLIP2 was trained on lowercased text, and
this checkpoint's Gemma tokenizer does not lowercase). Vectors are normalised, so a
dot product is the cosine. Picture vectors are made once, when pictures are read, and
stored with each picture; a question's vector is made at search time by the text
tower, loaded once per process. Needs torch and transformers.
"""

from collections.abc import Callable
from functools import cache
from pathlib import Path

from limespec import config

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
            max_length=config.SIGLIP_TEXT_TOKENS,
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


@cache
def text_encoder() -> EmbedTexts:
    """The text encoder, loaded once per process on first use."""
    return siglip_model(config.SIGLIP)[1]


def text_vector(question: str) -> list[float]:
    """A question's SigLIP2 vector, for ranking pictures by what they show."""
    return text_encoder()([question])[0]
