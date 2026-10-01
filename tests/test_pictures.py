"""Claims from pictures (X43 B5): attached only when asked for, verified against the
picture's own words, shown beside the picture. Invented passages and pictures."""

import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from limespec import answer, app, assistant, config, llm, store
from limespec.ingest import IngestError
from limespec.llm import ModelServerError
from limespec.models import Answer, DraftClaim, Passage
from limespec.verify import verify
from limespec.view import view

PICTURE = "a" * 64
WALL = Passage(
    1, "https://x.test/duro", "Duro", "Uses", "Duro suits walls.", "2026-10-01"
)
PHOTO = Passage(2, "https://x.test/duro", "Duro", "Image", "A Duro wall in Ochre",
                "2026-10-01", image=PICTURE)  # fmt: skip
MANIFEST = {"corpus_sha256": "c", "passages_sha256": "p", "embedding_model": "m"}
FIGURE = Passage(3, "https://x.test/sheet.pdf", "Sheet", "Image", "Build-up 25 mm",
                 "2026-10-01", page=3, image="b" * 64)  # fmt: skip


def understanding(system: str, user: str, schema: dict[str, Any]) -> object:
    return {
        "describes_exposure": False,
        "search_questions": ["What does Duro look like?"],
    }


def test_pictures_are_attached_numbered_and_may_be_described(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "MAX_PICTURES", 1)
    seen: list[Any] = []

    def see(
        system: str, user: str, schema: dict[str, Any], given: Sequence[Passage]
    ) -> object:
        seen.append((system, user, schema, list(given)))
        picture = {"part": 1, "picture": "S2", "text": "The wall is a warm ochre."}
        evidence = [{"source_id": "S1", "quote": "Duro suits walls"}]
        quoted = {"part": 1, "text": "Duro suits walls.", "evidence": evidence}
        return {"claims": [picture, quoted]}

    found = answer.answer(
        "Duro?", lambda q: [WALL, PHOTO, FIGURE], understanding, see=see, describe=True
    )

    system, user, schema, given = seen[0]
    assert system.endswith(answer.SEE_PROMPT + answer.DESCRIBE_PROMPT)
    assert given == [PHOTO]
    assert 'section="Image" picture="1">' in user and user.count("picture=") == 1
    item = schema["properties"]["claims"]["items"]["anyOf"][1]
    assert item["properties"]["picture"]["enum"] == ["S2"]
    claim = found.claims[0]
    assert (claim.picture, claim.evidence[0].quote) == (PICTURE, "")
    assert claim.evidence[0].link == "https://x.test/duro"
    shown = view(found)
    assert shown["claims"][0]["picture"] == PICTURE
    assert "picture" not in shown["claims"][1]


def test_seeing_pictures_alone_keeps_every_claim_quoted() -> None:
    seen: list[Any] = []

    def see(system: str, user: str, schema: dict[str, Any], given: Any) -> object:
        seen.append((system, user, schema))
        return {"claims": [{"part": 1, "picture": "S2", "text": "Ochre."}]}

    with pytest.raises(ModelServerError):  # a picture claim is not allowed here
        answer.answer("Duro?", lambda q: [WALL, PHOTO], understanding, see=see)

    system, user, schema = seen[0]
    assert system.endswith(answer.SEE_PROMPT) and 'picture="1"' in user
    assert "anyOf" not in schema["properties"]["claims"]["items"]


def test_the_picture_setting_is_checked_when_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    monkeypatch.setenv("LIMESPEC_PICTURES", "yes")
    with pytest.raises(ValueError):
        importlib.reload(config)
    monkeypatch.setenv("LIMESPEC_PICTURES", "claims")
    importlib.reload(config)
    assert config.PICTURES == "claims"
    monkeypatch.delenv("LIMESPEC_PICTURES")
    monkeypatch.setenv("LIMESPEC_PICTURE_RANKING", "pixels")
    with pytest.raises(ValueError):
        importlib.reload(config)
    monkeypatch.setenv("LIMESPEC_PICTURE_RANKING", "siglip")
    importlib.reload(config)
    assert config.PICTURE_RANKING == "siglip"
    monkeypatch.delenv("LIMESPEC_PICTURE_RANKING")
    importlib.reload(config)


def test_without_a_way_to_see_no_picture_is_attached() -> None:
    asked: list[str] = []

    def chat(system: str, user: str, schema: dict[str, Any]) -> object:
        if "describes_exposure" in schema["properties"]:
            return understanding(system, user, schema)
        asked.append(user)
        return {"claims": []}

    answer.answer("Duro?", lambda q: [WALL, PHOTO], chat)

    assert "picture=" not in asked[0]


def test_a_picture_claim_must_name_an_attached_picture() -> None:
    claim = {"part": 1, "picture": "S3", "text": "Ochre."}

    with pytest.raises(ModelServerError):
        answer.read_output({"claims": [claim]}, ["S1", "S2", "S3"], 1, ["S2"])


@pytest.mark.parametrize(
    ("text", "picture", "reason"),
    [
        ("A warm ochre wall.", "S1", "not an attached picture: S1"),
        ("It costs £20.", "S2", "states a price"),
        ("The wall is 40 mm thick.", "S2", "number not in the picture's words: 40"),
        ("It meets Part L.", "S2", "regulation not in the picture's words: part l"),
    ],
)
def test_a_picture_claim_is_held_to_the_picture_s_own_words(
    text: str, picture: str, reason: str
) -> None:
    sources = {"S1": WALL, "S2": PHOTO}

    claims, rejected = verify([DraftClaim(text, (), 1, picture)], sources, ["S2"])

    assert claims == () and rejected[0].reason == reason


def test_a_figure_s_claim_opens_its_page_and_may_use_its_numbers() -> None:
    claims, _ = verify([DraftClaim("The build-up is 25 mm.", (), 1, "S3")],
                       {"S3": FIGURE}, ["S3"])  # fmt: skip

    assert claims[0].evidence[0].link == "https://x.test/sheet.pdf#page=3"


def test_the_chat_request_carries_its_pictures(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}

    def post(url: str, **kwargs: Any) -> httpx.Response:
        sent.update(kwargs)
        message = {"content": json.dumps({"claims": []})}
        body = {"choices": [{"finish_reason": "stop", "message": message}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.CLIENT, "post", post)

    assert llm.chat("s", "u", {}, [b"x"]) == {"claims": []}
    assert sent["json"]["messages"][1]["content"][1]["type"] == "image_url"


def test_the_pictures_are_read_from_the_index_for_the_request(
    monkeypatch: pytest.MonkeyPatch, pg: store.Connection
) -> None:
    page = ("https://x.test/duro", "Duro", "2026-10-01T00:00:00+00:00", "1" * 64)
    row = ("https://x.test/duro", "Duro", "Image", "A Duro wall", "Image", None)
    vector = [1.0] + [0.0] * (config.EMBEDDING_DIMENSIONS - 1)
    store.write_version(pg, [page], [row], [vector], MANIFEST,
                        [PICTURE], {PICTURE: b"png"})  # fmt: skip
    sent: list[Any] = []

    def chat(*request: Any) -> object:
        sent.append(request)
        return {}

    monkeypatch.setattr(llm, "chat", chat)
    stages: list[str] = []

    see = assistant.seer(pg, stages.append)
    see("s", "u", {}, [PHOTO])

    assert sent[0][3] == [b"png"] and stages == ["answering", "checking"]
    with pytest.raises(IngestError):
        see("s", "u", {}, [FIGURE])


def test_the_api_serves_a_stored_picture_by_its_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app.app)
    stored = {PICTURE: b"\x89PNG"}

    def picture(image_id: str) -> bytes | None:
        if image_id == "c" * 64:
            raise IngestError("no database")
        return stored.get(image_id)

    monkeypatch.setattr(assistant, "picture", picture)

    found = client.get(f"/api/v1/images/{PICTURE}")
    assert (found.status_code, found.content) == (200, b"\x89PNG")
    assert found.headers["content-type"] == "image/png"
    assert client.get(f"/api/v1/images/{'b' * 64}").status_code == 404
    assert client.get(f"/api/v1/images/{'c' * 64}").status_code == 503
    assert client.get("/api/v1/images/not-a-picture").status_code == 422


def test_the_page_shows_a_picture_claim_beside_its_picture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims, _ = verify([DraftClaim("A warm ochre wall.", (), 1, "S2")],
                       {"S2": PHOTO}, ["S2"])  # fmt: skip
    result = Answer("Duro?", "answered", "", claims, (PHOTO,), ())
    monkeypatch.setattr(assistant, "ask", lambda question: result)

    page = TestClient(app.app).get("/", params={"q": "Duro?"}).text

    assert f'src="/api/v1/images/{PICTURE}"' in page and "From the image" in page
    assert "Open where this picture is shown" in page


def test_a_stored_picture_is_read_through_the_assistant(
    monkeypatch: pytest.MonkeyPatch, postgres_url: str, pg: store.Connection
) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", postgres_url)

    assert assistant.picture("d" * 64) is None
