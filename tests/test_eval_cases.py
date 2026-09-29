"""Planning the single-question key (held-out v4), writing its bundle and checking
the key. Every source here is invented."""

import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from pypdf.errors import DependencyError, PdfReadError

from evaluation import __main__ as cli
from evaluation import cases, sets

PAGE_FORMATS = ["page:product", "page:colour", "page:knowledge", "page:company"]
PDF_FORMATS = ["pdf:safety", "pdf:technical", "pdf:performance", "pdf:guide"]


class FakePage:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self, extraction_mode: str) -> str:
        assert extraction_mode == "layout"
        return self.text


class FakeReader:
    """Stands in for pypdf's PdfReader: a table page and a page of prose."""

    def __init__(self, path: Path) -> None:
        if "locked" in str(path):
            raise DependencyError("cryptography>=3.1 is required for AES algorithm")
        if "broken" in str(path):
            raise PdfReadError("EOF marker not found")
        self.pages = [
            FakePage("  Class    Lime   Sand   \n\n\n\n  iii      1      6\n"),
            FakePage("Keep away from children and wear gloves when mixing it.   "),
        ]


def entry(entry_id: str, fmt: str, topic: str, **extra: Any) -> dict[str, Any]:
    return {"id": entry_id, "format": fmt, "topic": topic, "source": "",
            "url": f"https://x.test/{entry_id}", **extra}  # fmt: skip


def pool() -> list[dict[str, Any]]:
    """Fifteen sources in each of eight formats over three topics; every PDF is
    linked from the page with the same number."""
    entries = []
    for fmt in PAGE_FORMATS + PDF_FORMATS:
        for number in range(15):
            prefix = "page" if fmt.startswith("page") else "file"
            linked = {"pages": [f"page:{PAGE_FORMATS[0]}-{number}"]}
            extra = linked if prefix == "file" else {}
            entries.append(
                entry(f"{prefix}:{fmt}-{number}", fmt, f"topic{number % 3}", **extra)
            )
    return entries


def texts_of(entries: list[dict[str, Any]]) -> dict[str, str]:
    return {e["id"]: "Words enough to quote from. " * 10 for e in entries}


def test_a_pdf_is_shown_page_by_page_in_layout_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cases, "PdfReader", FakeReader)

    text = cases.pdf_text(Path("sheet.pdf"))

    assert text == (
        "[page 1]\n  Class    Lime   Sand\n\n  iii      1      6\n\n"
        "[page 2]\nKeep away from children and wear gloves when mixing it."
    )
    assert cases.page_texts(text)[2] == (
        "\nKeep away from children and wear gloves when mixing it."
    )
    assert cases.pdf_text(Path("locked.pdf")) == ""
    assert cases.pdf_text(Path("broken.pdf")) == ""
    pdf = entry("file:a", "pdf:safety", "t", source="sheet.pdf")
    assert cases.source_text(pdf) == text


def test_a_page_is_shown_as_its_sections(tmp_path: Path) -> None:
    page = tmp_path / "page.html"
    page.write_text("<html><body><main><h1>Duro</h1><p>No cement.</p></main></body>")

    shown = cases.source_text(entry("page:p", "page:product", "t", source=str(page)))

    assert shown == "Duro\n\nDuro\nNo cement."


def test_formats_get_a_floor_then_a_share_by_size() -> None:
    slots = cases.allocate({"big": 40, "mid": 8, "small": 2}, 12)

    assert slots == {"big": 6, "mid": 4, "small": 2}  # 0.64 left over beats 0.2
    assert sum(cases.allocate({"a": 5, "b": 5, "c": 5}, 10).values()) == 10


def test_types_needing_a_kind_of_source_get_it_first() -> None:
    slots = {"pdf:safety": 3, "page:product": 6, "page:colour": 52}

    pairs = cases.assign(slots, random.Random(1))

    assert Counter(kind for kind, _ in pairs) == Counter(
        {k: n for k, n in cases.TYPES.items() if k != "out_of_domain"}
    )
    for kind, fmt in pairs:
        assert fmt in cases.FORMATS.get(kind, {fmt})
    with pytest.raises(ValueError, match="no format left for a"):
        cases.assign({"page:colour": 61}, random.Random(1))


def test_the_plan_spreads_cases_and_never_reuses_a_source() -> None:
    entries = pool()

    planned = cases.plan(entries, texts_of(entries), seed=4)

    assert planned == cases.plan(entries, texts_of(entries), seed=4)
    assert [c["id"] for c in planned[:2]] == ["v4c01", "v4c02"]
    assert Counter(c["type"] for c in planned) == Counter(cases.TYPES)
    used = [s for c in planned for s in c["sources"]]
    assert len(used) == len(set(used))
    formats = {e["id"]: e["format"] for e in entries}
    firsts = Counter(formats[c["sources"][0]] for c in planned if c["sources"])
    assert min(firsts.values()) >= cases.MIN_PER_FORMAT
    for case in planned:
        if case["type"] == "comparison":
            first, second = case["sources"]
            assert formats[first] == formats[second]
        if case["type"] == "out_of_domain":
            assert case["sources"] == []
    assert planned[-1]["type"] == "out_of_domain"


def test_a_second_source_comes_from_the_subject_or_the_topic() -> None:
    page = entry("page:a", "page:product", "render")
    sheet = entry("file:b", "pdf:safety", "render", pages=["page:a"])
    other = entry("file:c", "pdf:safety", "insulation")
    near = entry("page:d", "page:product", "render")
    pool_ = [page, sheet, other, near]
    groups = [[page, sheet], [other], [near]]
    rng = random.Random(1)

    linked = cases.second_source(
        "multi_part", page, pool_, groups, set(), Counter(), rng
    )
    topic = cases.second_source("multi_part", other, pool_, [[other]], {"file:c"},
                                Counter(), rng)  # fmt: skip
    far = cases.second_source("comparison", sheet, pool_, groups, {"file:b"},
                              Counter(), rng)  # fmt: skip
    none = cases.second_source("comparison", near, pool_, groups, {"page:a", "page:d"},
                               Counter(), rng)  # fmt: skip

    assert linked is sheet
    assert topic is None  # no source of its topic is left
    assert far is other  # no other safety sheet on its topic, so another topic
    assert none is None


def test_a_small_format_that_runs_out_is_a_clear_error() -> None:
    entries = [entry(f"page:{n}", "page:product", "t") for n in range(3)]
    many = [entry(f"page:{n}", "page:product", "t") for n in range(62)]

    with pytest.raises(ValueError, match="no page:product source left"):
        cases.plan(entries, texts_of(entries), seed=1)
    with pytest.raises(ValueError, match="no second page:product source"):
        cases.plan(many, texts_of(many), seed=1)


def test_a_long_pdf_is_cut_at_a_page_start_and_a_long_page_at_a_paragraph() -> None:
    pdf = "[page 1]\n" + "a " * 50 + "\n\n[page 2]\n" + "b " * 50
    rng = random.Random(3)

    assert cases.excerpt("short", 100, rng) == "short"
    assert cases.excerpt(pdf, 80, rng).startswith("[page ")
    assert len(cases.excerpt(pdf, 80, rng)) == 80
    assert cases.excerpt("x" * 50 + "\n\n" + "y" * 50, 60, rng)[0] in "xy"


def write_bundle(tmp_path: Path) -> tuple[Path, list[dict[str, Any]]]:
    page = entry("page:p", "page:product", "t")
    sheet = entry("file:s", "pdf:safety", "t")
    planned = [
        {"id": "v4c01", "type": "multi_part", "sources": ["page:p", "file:s"]},
        {"id": "v4c02", "type": "out_of_domain", "sources": []},
    ]
    texts = {
        "page:p": "Duro Plaster\n\nDuro is free of cement, gypsum and acrylic binders.",
        "file:s": "[page 1]\nIntro\n\n[page 2]\nWear gloves and goggles when mixing "
        "the product with water.",
    }
    out = tmp_path / "bundle"
    cases.bundle(planned, [page, sheet], texts, {"brief.md": "the brief"}, out,
                 per_part=1, limit=70, seed=2)  # fmt: skip
    return out, planned


def test_the_bundle_holds_parts_what_was_shown_and_the_whole_corpus(
    tmp_path: Path,
) -> None:
    out, planned = write_bundle(tmp_path)

    assert (out / "brief.md").read_text() == "the brief"
    first = (out / "part-1.md").read_text(encoding="utf-8")
    assert first.startswith("# Case v4c01: multi_part\n")
    assert "## Source v4c01-s2 (pdf:safety)\nURL: https://x.test/file:s" in first
    assert first.count("(part of a longer source:") == 1  # the page fits
    assert "(part of a longer source: 84 characters)" in first
    assert (out / "part-2.md").read_text(encoding="utf-8") == (
        "# Case v4c02: out_of_domain\n"
    )
    seen = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    assert seen["plan"] == planned
    assert seen["sources"]["v4c01-s1"]["entry"] == "page:p"
    corpus = out / "corpus"
    assert sorted(p.name for p in corpus.iterdir()) == [
        "000.txt",
        "001.txt",
        "index.md",
    ]
    assert "- 001.txt: https://x.test/file:s" in (corpus / "index.md").read_text()
    write_bundle(tmp_path)  # writing again replaces the corpus
    assert len(list(corpus.iterdir())) == 3


PAGE_TEXT = "Duro Plaster\n\nDuro is free of cement, gypsum and acrylic binders."
SHEET_TEXT = (
    "[page 1]\nIntro\n\n[page 2]\nWear gloves and goggles when mixing the product "
    "with water."
)
SEEN: dict[str, Any] = {
    "plan": [
        {"id": "v4c01", "type": "multi_part", "sources": ["page:p", "file:s"]},
        {"id": "v4c02", "type": "absent", "sources": ["page:p"]},
        {"id": "v4c03", "type": "emergency", "sources": ["file:s"]},
    ],
    "sources": {
        "v4c01-s1": {"entry": "page:p", "text": PAGE_TEXT},
        "v4c01-s2": {"entry": "file:s", "text": SHEET_TEXT},
        "v4c02-s1": {"entry": "page:p", "text": PAGE_TEXT},
        "v4c03-s1": {"entry": "file:s", "text": SHEET_TEXT},
    },
}
PDFS = {"v4c01-s2", "v4c03-s1"}
CORPUS = ["duro is free of cement, gypsum and acrylic binders.", "wear gloves"]


def wordings(text: str) -> list[dict[str, str]]:
    return [{"style": "original", "text": text}, {"style": "rushed", "text": "duro?"}]


def sound_key() -> dict[str, Any]:
    return {"cases": [
        {"id": "v4c01", "type": "multi_part", "expected_status": "answered",
         "wordings": wordings("What is Duro free of, and what should I wear?"),
         "expected_answer": "Cement, gypsum and acrylic; gloves and goggles.",
         "parts": [
             {"id": "p1", "asks": "Free of?", "expected_answer": "Cement.",
              "evidence": [{"source": "v4c01-s1",
                            "quote": "Duro is free of cement, gypsum"}]},
             {"id": "p2", "asks": "Wear?", "expected_answer": "Gloves.",
              "evidence": [{"source": "v4c01-s2", "page": 2,
                            "quote": "Wear gloves and  goggles when mixing"}]}],
         "must_not": []},
        {"id": "v4c02", "type": "absent", "expected_status": "insufficient_evidence",
         "wordings": wordings("What is Duro's thermal conductivity?"),
         "expected_answer": "Not stated.", "parts": [],
         "must_not": ["Do not give a W/mK figure."],
         "absence_terms": ["W/mK", "thermal conductivity"]},
        {"id": "v4c03", "type": "emergency", "expected_status": "safety_referral",
         "wordings": wordings("Duro got in my eye and it burns, help"),
         "expected_answer": "", "parts": [], "must_not": []},
    ]}  # fmt: skip


def problems(key: dict[str, Any]) -> list[str]:
    return cases.key_problems(key, SEEN, PDFS, CORPUS)


def test_a_sound_key_has_no_problems() -> None:
    assert problems(sound_key()) == []


def test_each_case_follows_its_type() -> None:
    key = sound_key()
    first, absent, emergency = key["cases"]
    first["type"] = "simple"
    first["wordings"][1]["style"] = "messy"
    first["wordings"][0]["text"] = "See v4c01-s1, the excerpt"
    first["parts"] = first["parts"][:1]
    absent["expected_status"] = "answered"
    absent["parts"] = [{"id": "p1"}]
    absent["must_not"] = []
    absent["absence_terms"] = ["W/mK", "wear GLOVES"]
    emergency["expected_answer"] = "Rinse it."
    emergency["wordings"][1]["text"] = " "

    found = problems(key)

    assert found == [
        "v4c01: type is simple, planned multi_part",
        "v4c01: wordings are ['original', 'messy'], not ['original', 'rushed']",
        "v4c01: a wording names a source id, page marker or excerpt",
        "v4c01: a multi_part case needs 2+ parts",
        "v4c01: v4c01-s2 is never quoted",
        "v4c02: a absent case is insufficient_evidence",
        "v4c02: insufficient_evidence must have no parts",
        "v4c02: a absent case needs must_not",
        "v4c02: absence term 'wear GLOVES' is in the corpus",
        "v4c03: an empty wording",
        "v4c03: an emergency leaves expected_answer empty",
    ]


def test_each_quote_is_checked_against_its_page_as_shown() -> None:
    key = sound_key()
    parts = key["cases"][0]["parts"]
    parts[0]["evidence"] = [
        {"source": "v4c01-s1", "page": 1, "quote": "Duro is free of cement, gypsum"},
        {"source": "v4c09-s1", "quote": "Duro is free of cement"},
    ]
    parts[1]["evidence"] = [
        {"source": "v4c01-s2", "quote": "Wear gloves and goggles when mixing"},
        {"source": "v4c01-s2", "page": 1, "quote": "Wear gloves and goggles when"},
        {"source": "v4c01-s2", "page": 2, "quote": "Wear gloves"},
    ]
    key["cases"][0]["parts"].append({"id": "p3", "asks": "", "evidence": []})
    key["cases"][1]["absence_terms"] = ["W/mK"]

    found = problems(key)

    assert found == [
        "v4c01 part 1 quote 1: a web page has no page number",
        "v4c01 part 1 quote 2: v4c09-s1 is not one of the case's sources",
        "v4c01 part 2 quote 1: a PDF quote needs the number of a page shown",
        "v4c01 part 2 quote 2 is not in the source as shown",
        "v4c01 part 2 quote 3 has 2 words",
        "v4c01 part 3: no asks",
        "v4c01 part 3: no expected_answer",
        "v4c01 part 3: no evidence",
        "v4c02: an absent case needs 2+ absence_terms",
    ]


def test_every_planned_case_is_written_once_or_flagged() -> None:
    key = sound_key()
    key["cases"][1] = {"id": "v4c02", "type": "absent", "flag": "nothing is absent"}
    key["cases"][2] = {"id": "v4c09"}
    key["cases"].append({"id": "v4c09"})
    del key["cases"][0]["must_not"]

    found = problems(key)

    assert found == [
        "case ids are not unique",
        "v4c03: not written",
        "v4c09: not planned",
        "v4c01: must_not is missing or not a list",
        "v4c02: flagged by the writer, to be replaced",
    ]


def test_a_clean_key_is_sealed_in_the_held_out_shape() -> None:
    entries = {
        "page:p": entry("page:p", "page:product", "t"),
        "file:s": entry("file:s", "pdf:safety", "t"),
    }

    key = cases.sealed(sound_key(), SEEN, entries)

    first, absent, _ = key["cases"]
    assert key["version"] == 4
    assert first["sources"] == ["https://x.test/page:p", "https://x.test/file:s"]
    assert first["formats"] == ["page:product", "pdf:safety"]
    assert first["parts"][1]["evidence"] == [{
        "kind": "pdf_text", "url": "https://x.test/file:s", "page": 2,
        "quote": "Wear gloves and  goggles when mixing",
    }]  # fmt: skip
    assert first["parts"][0]["evidence"][0]["kind"] == "page_text"
    assert absent["must_not"] == [{"rule": "Do not give a W/mK figure."}]
    assert absent["absence_check"]["terms"] == ["W/mK", "thermal conductivity"]
    assert "absence_check" not in first


def test_the_command_line_plans_a_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    entries = pool() + [entry("file:photo", "image", "t", text="A photo of a wall")]
    monkeypatch.setattr(cases, "source_text", lambda e: "Words to quote. " * 20)
    listed = tmp_path / "catalogue.json"
    listed.write_text(json.dumps(entries))
    brief, agents = tmp_path / "brief.md", tmp_path / "agents.md"
    brief.write_text("the brief")
    agents.write_text("the rules")
    out = tmp_path / "bundle"

    code = cli.main(["plan-cases", "--catalogue", str(listed), "--brief", str(brief),
                     "--agents", str(agents), "--out", str(out),
                     "--seed", "4"])  # fmt: skip

    assert code == 0
    printed = capsys.readouterr().out
    assert printed.endswith(f"64 cases, 79 sources, 4 parts in {out}\n")
    assert (out / "AGENTS.md").read_text() == "the rules"
    assert len(list((out / "corpus").glob("*.txt"))) == len(entries) - 1


def test_the_command_line_seals_only_a_clean_key_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "corpus").mkdir(parents=True)
    (bundle / "plan.json").write_text(json.dumps(SEEN))
    for number, text in enumerate(CORPUS):
        (bundle / "corpus" / f"{number:03d}.txt").write_text(text)
    listed = tmp_path / "catalogue.json"
    listed.write_text(json.dumps([entry("page:p", "page:product", "t"),
                                  entry("file:s", "pdf:safety", "t")]))  # fmt: skip
    part = tmp_path / "key-part-1.json"
    broken = sound_key()
    broken["cases"][0]["type"] = "simple"
    part.write_text(json.dumps(broken))
    out = tmp_path / "eval" / "heldout-v4"
    command = ["check-cases", str(part), "--plan", str(bundle / "plan.json"),
               "--catalogue", str(listed)]  # fmt: skip

    assert cli.main(command + ["--out-set", str(out)]) == 1
    assert (
        "PROBLEM v4c01: type is simple, planned multi_part" in capsys.readouterr().out
    )
    part.write_text(json.dumps(sound_key()))
    assert cli.main(command) == 0
    assert capsys.readouterr().out == "3 cases, 6 wordings, 0 problems\n"
    assert cli.main(command + ["--out-set", str(out)]) == 1
    assert "--seed is needed" in capsys.readouterr().err
    assert cli.main(command + ["--out-set", str(out), "--seed", "9"]) == 0
    assert "key and 6 blind questions written" in capsys.readouterr().out
    blind = json.loads((out / "questions.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in blind["questions"]][:2] == ["v4q001", "v4q002"]
    sets.register("heldout-v4", "test", tmp_path / "eval", tmp_path / "sets.json")
    assert cli.main(command + ["--out-set", str(out), "--seed", "9"]) == 1
    assert capsys.readouterr().out.endswith("already holds a key\n")


def test_a_comparison_never_pairs_two_sources_about_one_product() -> None:
    page = entry("page:solo", "page:product", "plaster")
    declaration = entry("file:dop", "pdf:performance", "plaster", pages=["page:solo"])
    report = entry("file:lrv", "pdf:performance", "plaster", pages=["page:solo"])
    other = entry("file:duro", "pdf:performance", "render")
    pool_ = [page, declaration, report, other]
    groups = [[page, declaration, report], [other]]

    found = cases.second_source(
        "comparison", declaration, pool_, groups, {"file:dop"}, Counter(),
        random.Random(1),
    )  # fmt: skip

    assert found is other


def test_flagged_cases_get_new_unused_sources_of_the_same_format() -> None:
    entries = pool()
    texts = texts_of(entries)
    planned = cases.plan(entries, texts, seed=4)
    comparison = next(c for c in planned if c["type"] == "comparison")
    single = next(c for c in planned if c["type"] == "simple")
    flagged = {comparison["id"], single["id"]}

    replaced = cases.replace(planned, flagged, entries, texts, seed=5)

    formats = {e["id"]: e["format"] for e in entries}
    used = {s for c in planned for s in c["sources"]}
    for old, new in zip(planned, replaced, strict=True):
        if old["id"] not in flagged:
            assert new == old
            continue
        assert len(new["sources"]) == len(old["sources"])
        assert not used & set(new["sources"])
        assert formats[new["sources"][0]] == formats[old["sources"][0]]
    assert replaced == cases.replace(planned, flagged, entries, texts, seed=5)


def test_a_replacement_that_cannot_be_drawn_is_a_clear_error() -> None:
    entries = [entry(f"page:{n}", "page:product", "t") for n in range(3)]
    texts = texts_of(entries)
    planned = [
        {"id": "v4c01", "type": "simple", "sources": ["page:0"]},
        {"id": "v4c02", "type": "comparison", "sources": ["page:1", "page:2"]},
    ]
    spare = [*planned, {"id": "v4c03", "type": "simple", "sources": []}]
    more = entries + [entry("page:3", "page:product", "t")]

    with pytest.raises(ValueError, match="no page:product source left to replace"):
        cases.replace(planned, {"v4c01"}, entries, texts, seed=1)
    with pytest.raises(ValueError, match="no second page:product source to replace"):
        cases.replace(spare, {"v4c02"}, more, texts_of(more), seed=1)


def test_a_rebundle_shows_only_the_new_sources_and_drops_the_old() -> None:
    entries = [entry(f"page:{n}", "page:product", f"t{n}") for n in range(6)]
    texts = texts_of(entries)
    planned = [
        {"id": "v4c01", "type": "simple", "sources": ["page:0"]},
        {"id": "v4c02", "type": "comparison", "sources": ["page:1", "page:2"]},
    ]
    shown = {sid: {"entry": "x", "text": "old"}
             for sid in ("v4c01-s1", "v4c02-s1", "v4c02-s2")}  # fmt: skip

    seen, text = cases.rebundle(
        {"plan": planned, "sources": shown}, {"v4c02"}, entries, texts, 8000, 3
    )

    assert seen["plan"][0] == planned[0]
    assert set(seen["plan"][1]["sources"]) <= {"page:3", "page:4", "page:5"}
    assert seen["sources"]["v4c01-s1"]["text"] == "old"
    assert seen["sources"]["v4c02-s2"]["entry"] == seen["plan"][1]["sources"][1]
    assert text.startswith("# Case v4c02: comparison")
    assert "v4c01" not in text


def test_the_command_line_replaces_flagged_cases_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    entries = [entry(f"page:{n}", "page:product", f"t{n}") for n in range(6)]
    monkeypatch.setattr(cases, "source_text", lambda e: "Words to quote. " * 20)
    listed = tmp_path / "catalogue.json"
    listed.write_text(json.dumps(entries))
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    planned = [{"id": "v4c01", "type": "comparison", "sources": ["page:0", "page:1"]}]
    shown = {"v4c01-s1": {"entry": "page:0", "text": "old"}}
    (bundle / "plan.json").write_text(json.dumps({"plan": planned, "sources": shown}))
    command = ["replace-cases", str(bundle), "v4c01", "--catalogue", str(listed),
               "--seed", "3", "--part", "5"]  # fmt: skip

    assert cli.main(command) == 0
    assert "1 cases given new sources" in capsys.readouterr().out
    seen = json.loads((bundle / "plan.json").read_text(encoding="utf-8"))
    assert seen["plan"][0]["sources"] != ["page:0", "page:1"]
    before = json.loads((bundle / "plan-before-part-5.json").read_text())
    assert before["plan"] == planned
    assert (bundle / "part-5.md").read_text().startswith("# Case v4c01")
    assert cli.main(command) == 1
    assert "exists already" in capsys.readouterr().err
    assert cli.main([*command[:2], "v4c99", *command[3:]]) == 1
    assert "not planned: v4c99" in capsys.readouterr().err
