"""Drawing X8's pages from the catalogue. Every document and text is invented."""

import json
import random
from pathlib import Path

import pytest
from pypdf.errors import DependencyError, PdfReadError

from evaluation import __main__ as cli
from evaluation import pages, sets
from limespec import acquire

WORDS = "lime mortar for brick and stone walls mixed with clean water"  # 11 words
OTHER = "hemp binder cast into shuttering around a timber frame wall today"


class FakePage:
    def __init__(self, text: str | None) -> None:
        self.text = text

    def extract_text(self) -> str | None:
        return self.text


class FakeReader:
    """Stands in for pypdf's PdfReader: a page of text, then one without a layer."""

    def __init__(self, path: Path) -> None:
        if "locked" in str(path):
            raise DependencyError("cryptography>=3.1 is required for AES algorithm")
        if "broken" in str(path):
            raise PdfReadError("EOF marker not found")
        self.pages = [FakePage(WORDS), FakePage(None)]


def document(name: str, form: str) -> dict[str, str]:
    return {"id": f"file:{name}", "format": form, "url": f"https://x.test/{name}.pdf",
            "source": name}  # fmt: skip


def test_each_page_text_layer_is_read_and_unreadable_files_have_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pages, "PdfReader", FakeReader)

    assert pages.read_pages("sheet.pdf") == [WORDS, ""]
    assert pages.read_pages("locked.pdf") == []
    assert pages.read_pages("broken.pdf") == []


def test_pages_with_ten_words_have_a_text_layer_and_resemblance_is_shared_words() -> (
    None
):
    assert pages.text_pages(["", "Contents 3", WORDS]) == [3]
    assert pages.resemblance(WORDS, WORDS.upper()) == 1.0
    assert pages.resemblance(WORDS, OTHER) == 0.0
    assert pages.resemblance("a b", "b c") == pytest.approx(1 / 3)
    assert pages.resemblance("", " ") == 1.0


def test_documents_give_their_first_or_a_random_page_in_a_seeded_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pages, "QUOTAS", (("pdf:performance", 2, "first"), ("pdf:guide", 1, "random"))
    )
    texts = {
        "dop-a": ["cover", WORDS, OTHER],
        "dop-b": [OTHER + " dop b"],
        "dop-c": [WORDS + " dop c extra words for a third declaration"],
        "guide": [WORDS + " g1", OTHER + " g2", "x"],
        "locked": [],
    }
    entries = [
        document(name, "pdf:guide" if name == "guide" else "pdf:performance")
        for name in texts
    ] + [document("photo", "image")]

    drawn = pages.sample(entries, texts.__getitem__, seed=3, near=1.01)

    rng = random.Random(3)
    order = sorted(e["id"] for e in entries if e["format"] == "pdf:performance")
    rng.shuffle(order)
    usable = [name for name in order if name != "file:locked"][:2]
    assert [page["entry"] for page in drawn[:2]] == usable
    first = {"file:dop-a": 2, "file:dop-b": 1, "file:dop-c": 1}
    assert [page["page"] for page in drawn[:2]] == [first[name] for name in usable]
    assert drawn[2]["entry"] == "file:guide"
    assert drawn[2]["page"] in (1, 2)
    name = usable[0].removeprefix("file:")
    assert drawn[0] == {
        "format": "pdf:performance",
        "entry": usable[0],
        "url": f"https://x.test/{name}.pdf",
        "page": first[usable[0]],
        "source": name,
    }
    assert pages.sample(entries, texts.__getitem__, seed=3, near=1.01) == drawn


def test_excluded_documents_and_pages_like_earlier_ones_are_passed_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pages, "QUOTAS", (("pdf:performance", 2, "first"),))
    texts = {
        "used": [WORDS + " used"],
        "twin": [WORDS + " twin"],  # the same declaration under another name
        "new": [OTHER],
        "also": [OTHER + " also new words here too and more of them"],
    }
    entries = [document(name, "pdf:performance") for name in texts]

    drawn = pages.sample(
        entries, texts.__getitem__, seed=1, exclude=["file:used"], seen=[WORDS]
    )

    assert sorted(page["entry"] for page in drawn) == ["file:also", "file:new"]


def test_a_format_short_of_documents_takes_further_pages_of_the_same_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pages, "QUOTAS", (("pdf:guide", 5, "random"),))
    texts = {
        "one": [WORDS + " one", OTHER + " one", "cover"],
        "two": [f"{WORDS} two {n}" if n % 2 else f"{OTHER} two" for n in range(3)],
    }
    entries = [document(name, "pdf:guide") for name in texts]

    drawn = pages.sample(entries, texts.__getitem__, seed=5, near=1.01)
    near = pages.sample(entries, texts.__getitem__, seed=5)

    assert sorted((page["entry"], page["page"]) for page in drawn) == [
        ("file:one", 1), ("file:one", 2),
        ("file:two", 1), ("file:two", 2), ("file:two", 3),
    ]  # fmt: skip
    # Near-duplicates (page 3 of "two" is page 1 again, give or take one word) are
    # passed over, and the quota stays unmet when no page is left.
    assert len(near) < 5


def test_blank_pages_are_drawn_from_every_pdf_by_a_seeded_generator() -> None:
    texts = {"dwg": ["", WORDS, "Section A-A"], "sheet": [WORDS], "photo": [""]}
    entries = [document("dwg", "pdf:guide"), document("sheet", "pdf:technical"),
               document("photo", "image")]  # fmt: skip

    drawn = pages.blank(entries, texts.__getitem__, seed=2, count=5)

    assert sorted((page["entry"], page["page"]) for page in drawn) == [
        ("file:dwg", 1),
        ("file:dwg", 3),
    ]
    assert len(pages.blank(entries, texts.__getitem__, seed=2, count=1)) == 1


def test_the_command_line_leaves_out_a_set_s_documents_and_pages(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalogue = tmp_path / "catalogue.json"
    entries = [document(name, "pdf:policy") for name in ("used", "twin", "new")]
    catalogue.write_text(json.dumps(entries))
    folder = tmp_path / "old"
    folder.mkdir()
    truth = {"pages": [{"entry": "file:used", "page": 1}]}
    (folder / "truth.json").write_text(json.dumps(truth))
    sets.register("old", "invented", tmp_path, tmp_path / "sets.json")
    texts = {"used": [WORDS], "twin": [WORDS + " twin"], "new": [OTHER, ""]}
    monkeypatch.setattr(pages, "read_pages", lambda source: texts[Path(source).name])
    monkeypatch.setattr(acquire, "store_path", lambda sha: tmp_path / sha)
    out = tmp_path / "drawn.json"
    base = ["--root", str(tmp_path), "--registry", str(tmp_path / "sets.json")]
    command = ["sample-pages", "--catalogue", str(catalogue), "--seed", "9"]

    assert cli.main([*base, *command, "--exclude-set", "old", "--blank", "3",
                     "--out", str(out)]) == 0  # fmt: skip

    drawn = json.loads(out.read_text(encoding="utf-8"))
    assert [page["entry"] for page in drawn["pages"]] == ["file:new"]
    assert [(page["entry"], page["page"]) for page in drawn["blank"]] == [
        ("file:new", 2)
    ]
    assert "1 pages, 1 blank" in capsys.readouterr().out
    assert cli.main([*base, *command, "--exclude", "file:new", "--out", str(out)]) == 0
    drawn = json.loads(out.read_text(encoding="utf-8"))
    assert [page["entry"] for page in drawn["pages"]] == ["file:used"]
