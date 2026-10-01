import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from evaluation import __main__ as cli
from evaluation import cases, imagesets, kbprobe, sets
from limespec import assistant, config, store
from limespec.models import Passage

SITE = "https://www.lime-green.co.uk/"
GOV = "https://assets.publishing.service.gov.uk/"


def entry(identity: str, kind: str, url: str, **more: Any) -> dict[str, Any]:
    return {"id": identity, "format": kind, "url": url, "source": identity, **more}


CATALOGUE = [
    entry("page:kb", "page:knowledge", SITE + "support/knowledgebase/lime"),
    entry("page:ochre", "page:colour", SITE + "products-by-colour/ochre"),
    entry("page:mortar", "page:product", SITE + "products/lime-mortar"),
    entry("page:ashlar", "page:product", SITE + "products/lime-mortar/ashlar"),
    entry("page:warmshell", "page:product", SITE + "warmshell-natural-insulation"),
    *[
        entry(
            f"file:p{n}",
            "pdf:technical",
            SITE + f"Documents/p{n}.pdf",
            pages=["page:ashlar"],
        )
        for n in range(4)
    ],  # fmt: skip
    entry("picture:fig", "image:visual", SITE + "Documents/p0.pdf", page=2),
    entry(
        "picture:site", "image:visual", SITE + "products/lime-mortar/ashlar", page=None
    ),
    entry("picture:words", "image:text", SITE + "news", page=None),
    entry("file:docx", "docx:declaration", SITE + "Documents/dop.docx"),
    entry("file:iwi", "external:guidance", GOV + "iwi-guidance.pdf"),
    entry("file:plan", "external:guidance", GOV + kbprobe.LEFT_OUT),
    entry("picture:plan", "image:visual", GOV + kbprobe.LEFT_OUT, page=9),
    entry("file:x", "image", SITE + "images/x.webp"),
]


def test_each_source_belongs_to_the_strata_a_visitor_would_meet_it_in() -> None:
    found = {e["id"]: kbprobe.strata(e) for e in CATALOGUE}

    assert found["page:kb"] == ["web-content"]
    assert found["page:ochre"] == ["listing"] and found["page:mortar"] == ["listing"]
    assert found["page:ashlar"] == ["web-content"]
    assert found["page:warmshell"] == ["web-content"]
    assert found["file:p0"] == ["pdf-text", "pdf-table"]
    assert found["picture:fig"] == ["pdf-figure"]
    assert found["picture:site"] == ["picture-visual"]
    assert found["picture:words"] == ["picture-text"]
    assert found["file:docx"] == ["word"] and found["file:iwi"] == ["guidance"]
    assert found["file:plan"] == found["picture:plan"] == found["file:x"] == []


def test_the_draw_fills_every_stratum_and_pairs_cross_type_sources() -> None:
    drawn = kbprobe.draw(CATALOGUE, seed=3)

    assert len(drawn) == sum(kbprobe.STRATA.values())
    assert [d["id"] for d in drawn[:2]] == ["kb01", "kb02"]
    counts = {name: sum(d["stratum"] == name for d in drawn) for name in kbprobe.STRATA}
    assert counts == kbprobe.STRATA
    crossed = [d for d in drawn if d["stratum"] == "cross-type"]
    assert all(d["also"] == "page:ashlar" for d in crossed)
    assert {d["source"] for d in drawn if d["stratum"] == "guidance"} == {"file:iwi"}
    assert kbprobe.draw(CATALOGUE, seed=3) == drawn
    pages = [entry(f"page:{n}", "page:news", SITE + f"news/{n}") for n in range(9)]
    larger = kbprobe.draw([*CATALOGUE, *pages], seed=3)
    content = [d["source"] for d in larger if d["stratum"] == "web-content"]
    assert len(set(content)) == kbprobe.STRATA["web-content"]  # no source twice


def test_a_written_question_is_checked_against_its_own_sources() -> None:
    nuggets = [{"text": "Shelf life: 12 months"}, {"picture": "a"}]
    good = {"id": "kb1", "question": "Shelf life?", "nuggets": nuggets}
    bad = {"id": "kb2", "question": " ", "nuggets": [
        {"text": "one two three four five six seven eight nine ten 11 12 13 14 15 16"},
        {"text": "not there"}, {"picture": "z"}]}  # fmt: skip

    assert kbprobe.nugget_problems(good, "Shelf life:\n 12 months", {"a"}) == []
    assert kbprobe.nugget_problems(bad, "text", {"a"}) == [
        "kb2: no question",
        "kb2: a nugget over 15 words",
        "kb2: not in its sources: 'not there'",
        "kb2: unknown picture z",
    ]
    assert kbprobe.nugget_problems({"id": "kb3", "question": "Q"}, "", set()) == [
        "kb3: no nugget"
    ]


def test_sealing_finds_every_holder_unless_the_fact_is_the_sources_own() -> None:
    texts = {"u1": "Shelf life: 12 months", "u2": "Shelf life: 12 months", "u3": "x"}
    item = {"id": "kb1", "stratum": "pdf-text", "source": "file:p1", "question": "Q",
            "nuggets": [{"text": "Shelf life: 12 months"},
                        {"text": "Shelf life: 12 months", "own": True},
                        {"picture": "a"}, {"picture": "b"}]}  # fmt: skip

    found = kbprobe.sealed(item, texts, {"a": ["a", "a2"]}, ["u2"])

    assert found["set"] == "pdf-text" and found["cluster"] == "file:p1"
    assert [n.get("holders") for n in found["nuggets"][:2]] == [["u1", "u2"], ["u2"]]
    assert [n.get("accepted") for n in found["nuggets"][2:]] == [["a", "a2"], ["b"]]


def passage(identity: int, url: str, text: str, image: str = "") -> Passage:
    return Passage(identity, url, "Duro", "Storage", text, "", image=image)


ITEM = {"id": "kb1", "set": "pdf-text", "cluster": "s", "question": "Q", "nuggets": [
    {"text": "Shelf life: 12 months", "holders": ["u1"]},
    {"picture": "a", "accepted": ["a", "a2"]}]}  # fmt: skip


def test_a_question_is_found_when_what_is_given_holds_every_nugget() -> None:
    held = passage(1, "u1", "Shelf life: 12 months")
    elsewhere = passage(2, "u9", "Shelf life: 12 months")
    picture = passage(3, "u1", "", image="a2")

    found = kbprobe.result(ITEM, [elsewhere, held, picture], [held, picture])
    missed = kbprobe.result(ITEM, [held], [held])

    assert (found["success"], found["reciprocal"], found["ceiling"]) == (
        1.0,
        1 / 3,
        1.0,
    )
    assert (missed["success"], missed["reciprocal"], missed["ceiling"]) == (0, 0, 0)
    assert kbprobe.pooled([found, {**missed, "set": "picture-visual"}]) == {
        "text": 1.0, "pictures": 0.0, "all": 0.5}  # fmt: skip
    assert kbprobe.pooled([]) == {"text": 0.0, "pictures": 0.0, "all": 0.0}


def test_the_command_line_draws_and_seals_the_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps(CATALOGUE))
    monkeypatch.setattr(
        cases, "source_text", lambda e, rendered: f"Shelf life of {e['id']}"
    )
    images = tmp_path / "images"
    images.mkdir()
    for name in ("fig", "site", "words"):
        (images / f"{name}.png").write_bytes(b"")
    monkeypatch.setattr(config, "IMAGES", images)
    monkeypatch.setattr(imagesets, "copies", lambda ids, folder: {i: [i] for i in ids})
    out = tmp_path / "draw"
    common = ["--catalogue", str(catalogue), "--rendered", str(tmp_path)]

    assert cli.main(["kb-probe-draw", *common, "--seed", "3", "--out", str(out)]) == 0
    assert "64 questions' sources" in capsys.readouterr().out
    shown = (out / "sources.md").read_text(encoding="utf-8")
    assert "## kb01" in shown and "Picture: picture:fig (id fig)" in shown

    drawn = json.loads((out / "draw.json").read_text())
    written = [
        {**d, "question": "Q", "nuggets": [{"text": "Shelf life"}]} for d in drawn
    ]
    written[0]["nuggets"] = [{"text": "Shelf life", "own": True}, {"picture": "site"}]
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(written))
    sealed_set = tmp_path / "eval" / "kb-probe"
    command = ["kb-probe-seal", str(draft), *common, "--out-set", str(sealed_set)]

    assert cli.main(command) == 0
    assert "64 questions sealed" in capsys.readouterr().out
    first = json.loads((sealed_set / "questions.json").read_text())["questions"][0]
    own = next(e["url"] for e in CATALOGUE if e["id"] == drawn[0]["source"])
    assert first["nuggets"][0]["holders"] == [own]  # every text holds it; only its own
    assert first["nuggets"][1] == {"picture": "site", "accepted": ["site"]}

    written[1]["nuggets"] = [{"text": "missing words"}]
    draft.write_text(json.dumps(written))
    assert cli.main(command) == 1
    assert "kb02: not in its sources" in capsys.readouterr().out


def test_the_command_line_scores_a_version_on_kb_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "eval" / "kb-probe"
    folder.mkdir(parents=True)
    (folder / "questions.json").write_text(json.dumps({"questions": [ITEM]}))
    registry = tmp_path / "sets.json"
    sets.register("kb-probe", "", tmp_path / "eval", registry)

    @contextmanager
    def connect() -> Iterator[None]:
        yield None

    held = passage(1, "u1", "Shelf life: 12 months")
    picture = passage(3, "u1", "", image="a")
    monkeypatch.setattr(assistant, "connect", connect)
    monkeypatch.setattr(store, "search", lambda conn, v, q, e, r: [held, picture])
    monkeypatch.setattr(store, "document_passages", lambda conn, v, url: [held])
    monkeypatch.setattr(store, "picture_passages", lambda conn, v: {"a": 3})
    monkeypatch.setattr(store, "load_passages", lambda conn, ids: [picture])
    run = tmp_path / "run.json"
    common = ["--root", str(tmp_path / "eval"), "--registry", str(registry)]

    assert cli.main([*common, "kb-probe", "--version", "21", "--out", str(run)]) == 0
    assert "text 1.000, pictures 0.000, all 1.000" in capsys.readouterr().out
    saved = json.loads(run.read_text())
    assert saved["summary"]["strata"]["pdf-text"]["ceiling"] == 1.0
