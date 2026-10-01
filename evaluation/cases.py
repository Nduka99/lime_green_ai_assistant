"""Plan a single-question key over the whole corpus, write the bundle an independent
key writer reads, and check the key it returns (held-out v4).

Cases are spread over source formats: at least `MIN_PER_FORMAT` per format and the
rest in proportion to the format's sources, so every format can be reported on its
own (Coverage, Not Averages, 2026). Case types follow CRAG's question types (Yang et
al., NeurIPS 2024) plus the refusal and safety situations the assistant must handle.
Each case is written from its planned sources only. A PDF is shown as pypdf's
layout-mode text, which keeps table columns apart, with `[page N]` markers, so every
quote names its page and is checked against exactly the text the writer saw, not
against the assistant's own reading of the PDF. `corpus/` holds every source's
text, so an absent figure can be shown to be absent everywhere, by the writer and by
the checker.
"""

import json
import random
import re
import shutil
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import DependencyError, PyPdfError

from evaluation import conversations, keys
from evaluation.catalogue import Entry
from limespec import config

# Case type -> number of cases. Out-of-domain cases need no source.
TYPES = {
    "simple": 10,
    "condition": 6,
    "set": 6,
    "comparison": 6,
    "multi_part": 12,
    "absent": 8,
    "false_premise": 4,
    "price": 3,
    "emergency": 3,
    "injection": 3,
    "out_of_domain": 3,
}
STATUS = {
    "absent": "insufficient_evidence",
    "price": "insufficient_evidence",
    "out_of_domain": "insufficient_evidence",
    "emergency": "safety_referral",
}  # every other type is answered
SOURCES = {"comparison": 2, "multi_part": 2, "out_of_domain": 0}  # others: 1
MIN_PARTS = {"comparison": 2, "multi_part": 2}  # others: 1 when answered
# Types that need a particular kind of source; every other type takes any format.
FORMATS = {
    "emergency": {"pdf:safety", "page:product"},
    "price": {"page:product", "pdf:technical"},
    "comparison": {"page:product", "page:colour", "pdf:technical", "pdf:safety",
                   "pdf:performance"},
}  # fmt: skip
UNINDEXED = {"image", "external:guidance"}  # not in the assistant's index yet
MIN_PER_FORMAT = 3
# Held-out v6 (X43) covers every data type: a picture is a source of its own
# (`catalogue.pictures`), Word files and the OGL guidance are read like PDFs.
PICTURES = {"image:text", "image:visual"}
ASSET_SCALE = 1.5  # a document page drawn at 108 DPI for the writer to see
V6_FORMATS = {
    "visual": PICTURES,
    "structure": {"page:product", "page:knowledge", "page:case-study", "page:company",
                  "pdf:guide", "pdf:technical", "docx:declaration"},
}  # fmt: skip
STYLES = ["original", "rushed"]
# A plan's design: the prefix of its case ids, its cases per type, whether a source may
# serve more than one case, and the wordings its cases get in turn. Held-out v4's:
V4: dict[str, Any] = {
    "prefix": "v4c",
    "counts": TYPES,
    "reuse": False,
    "styles": [STYLES],
}
# What a source is seen by, written into the bundle: (entry, source id, text) -> names.
Show = Callable[[Entry, str, str], list[str]]
PAGE_MARK = re.compile(r"^\[page (\d+)\]$", re.MULTILINE)
# A customer never sees the bundle, so never names its source ids or page markers.
BUNDLE_WORDS = re.compile(r"\bv\d+c\d+-s\d+\b|\[page \d+\]|\bexcerpt\b", re.IGNORECASE)
CASE_ID = re.compile(r"v(\d+)c\d+")  # a case id names its key's version
CASE_FIELDS: dict[str, type] = {
    "id": str,
    "type": str,
    "expected_status": str,
    "wordings": list,
    "expected_answer": str,
    "parts": list,
    "must_not": list,
}


def pdf_text(path: Path) -> str:
    """A PDF's text in pypdf's layout mode, each page after its `[page N]` marker,
    trailing spaces and runs of blank lines removed; "" when it cannot be read."""
    try:
        pages = PdfReader(path).pages
        texts = [page.extract_text(extraction_mode="layout") for page in pages]
    # DependencyError: encrypted with AES, which needs pypdf's cryptography extra.
    except (PyPdfError, DependencyError, ValueError):
        return ""
    blocks = []
    for number, text in enumerate(texts, 1):
        lines = [line.rstrip() for line in text.splitlines()]
        body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")
        blocks.append(f"[page {number}]\n{body}")
    return "\n\n".join(blocks)


def source_text(entry: Entry, rendered: Path | None = None) -> str:
    """The text a source offers the writer and the checker. With `rendered` (a
    `web-render` folder), a page is its text as a browser shows it (X43); a Word
    file is the PDF LibreOffice laid it out as; a picture is its alt text and the
    text a machine read in it."""
    if entry["id"].startswith("page:"):
        page = (rendered or Path()) / f"{Path(entry['source']).stem}.txt"
        if rendered is not None and page.exists():
            return page.read_text(encoding="utf-8")
        return conversations.source_text(entry)
    if entry["format"] in PICTURES:
        return picture_text(entry)
    if entry["format"] == "docx:declaration":
        sha256 = entry["id"].split(":", 1)[1]
        return pdf_text(config.READINGS / "rendered" / f"{sha256}.pdf")
    return pdf_text(Path(entry["source"]))


def picture_text(entry: Entry) -> str:
    """What a picture source shows the writer beside the picture itself."""
    where = entry["url"] + (f" (page {entry['page']})" if entry.get("page") else "")
    return "\n".join(
        [
            f"Picture file: {Path(entry['source']).name}",
            f"Shown on: {where}",
            f"Alt text: {entry.get('alt') or '(none)'}",
            "Text a machine read in the picture (it can be wrong: quote only what "
            "the picture itself shows):",
            entry.get("read") or "(none)",
        ]
    )


def page_texts(text: str) -> dict[int, str]:
    """A PDF text's pages by number, from its `[page N]` markers."""
    marks = list(PAGE_MARK.finditer(text))
    pages = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        pages[int(mark.group(1))] = text[mark.end() : end]
    return pages


def allocate(
    counts: dict[str, int], total: int, least: int = MIN_PER_FORMAT
) -> dict[str, int]:
    """Cases per format: `least` each (fewer if the format has fewer sources), the
    rest in proportion to the sources, largest remainders first."""
    slots = {name: min(least, count) for name, count in counts.items()}
    left = total - sum(slots.values())
    size = sum(counts.values())
    shares = {name: left * count / size for name, count in counts.items()}
    for name, share in shares.items():
        slots[name] += int(share)
    rest = total - sum(slots.values())
    by_remainder = sorted(shares, key=lambda n: (-(shares[n] % 1), n))
    for name in by_remainder[:rest]:
        slots[name] += 1
    return slots


def assign(
    slots: dict[str, int],
    rng: random.Random,
    counts: dict[str, int],
    needs: dict[str, set[str]] | None = None,
) -> list[tuple[str, str]]:
    """(type, format) for every case with a source; types that need a kind of
    source (`needs`, else FORMATS) choose first, those allowed the fewest formats
    before the others."""
    needs = FORMATS if needs is None else needs
    formats = [name for name, count in sorted(slots.items()) for _ in range(count)]
    rng.shuffle(formats)
    kinds = [
        kind for kind, n in counts.items() if SOURCES.get(kind, 1) for _ in range(n)
    ]
    kinds.sort(key=lambda kind: len(needs.get(kind, formats)))
    pairs = []
    for kind in kinds:
        allowed = needs.get(kind)
        index = next(
            (i for i, name in enumerate(formats) if allowed is None or name in allowed),
            None,
        )
        if index is None:
            raise ValueError(f"no format left for a {kind} case")
        pairs.append((kind, formats.pop(index)))
    rng.shuffle(pairs)
    return pairs


def pick(
    candidates: list[Entry],
    used: Counter[str],
    topics: Counter[str],
    rng: random.Random,
    reuse: bool = False,
) -> Entry | None:
    """An unused source, from the topic used least so far (ties at random). With
    `reuse`, the source used least so far, so none serves twice before all have
    served once."""
    fresh = [entry for entry in candidates if reuse or not used[entry["id"]]]
    if not fresh:
        return None
    rng.shuffle(fresh)
    chosen = min(fresh, key=lambda e: (used[e["id"]], topics[e["topic"]]))
    used[chosen["id"]] += 1
    topics[chosen["topic"]] += 1
    return chosen


def second_source(
    kind: str,
    first: Entry,
    pool: list[Entry],
    groups: list[list[Entry]],
    used: Counter[str],
    topics: Counter[str],
    rng: random.Random,
    reuse: bool = False,
) -> Entry | None:
    """A comparison's second product: same format, same topic when possible, never
    from the first source's subject (a page and the files it links to), which is the
    same product. A multi-part case's second source: another format from the first
    source's subject, else another source of the same topic."""
    subject = [e for g in groups if first in g for e in g] or [first]
    if kind == "comparison":
        same = [e for e in pool if e["format"] == first["format"] and e not in subject]
        on_topic = [e for e in same if e["topic"] == first["topic"]]
        return pick(on_topic, used, topics, rng, reuse) or pick(
            same, used, topics, rng, reuse
        )
    linked = [e for e in subject if e["format"] != first["format"]]
    on_topic = [e for e in pool if e["topic"] == first["topic"] and e is not first]
    return pick(linked, used, topics, rng, reuse) or pick(
        on_topic, used, topics, rng, reuse
    )


def usable_pool(
    entries: list[Entry], texts: dict[str, str], unindexed: set[str] = UNINDEXED
) -> list[Entry]:
    """The sources a case may use: indexed, with enough text to quote (a picture
    always: it can be asked about by what it shows)."""
    return [
        e
        for e in entries
        if e["format"] not in unindexed
        and (e["format"] in PICTURES or conversations.usable(e, texts[e["id"]]))
    ]


def plan(
    entries: list[Entry],
    texts: dict[str, str],
    seed: int,
    design: dict[str, Any] = V4,
    served: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Every case: its id, type, source ids and wording styles, out-of-domain cases
    last. `served` names the sources earlier keys used: they wait their turn behind
    the sources no key has used."""
    rng = random.Random(seed)
    counts, reuse = design["counts"], design["reuse"]
    unindexed = set(design.get("unindexed", UNINDEXED))
    pool = usable_pool(entries, texts, unindexed)
    total = sum(n for kind, n in counts.items() if SOURCES.get(kind, 1))
    least = design.get("min_per_format", MIN_PER_FORMAT)
    slots = allocate(dict(Counter(e["format"] for e in pool)), total, least)
    groups = conversations.subjects(pool)
    used = Counter(served)
    topics: Counter[str] = Counter()
    firsts = []
    needs = FORMATS | (V6_FORMATS if "visual" in counts else {})
    # Every case's own source first, so second sources never exhaust a small format.
    for kind, name in assign(slots, rng, counts, needs):
        named = [e for e in pool if e["format"] == name]
        first = pick(named, used, topics, rng, reuse)
        if first is None:
            raise ValueError(f"no {name} source left for a {kind} case")
        firsts.append((kind, first))
    planned = []
    for kind, first in firsts:
        sources = [first]
        if SOURCES.get(kind, 1) == 2:
            other = second_source(kind, first, pool, groups, used, topics, rng, reuse)
            if other is None and kind == "comparison":
                raise ValueError(f"no second {first['format']} source for a comparison")
            sources += [other] if other else []  # a multi-part case may use one
        planned.append({"type": kind, "sources": [e["id"] for e in sources]})
    for _ in range(counts["out_of_domain"]):
        planned.append({"type": "out_of_domain", "sources": []})
    width = max(2, len(str(len(planned))))
    styles = design["styles"]
    return [
        {
            "id": f"{design['prefix']}{n:0{width}d}",
            **case,
            "styles": styles[n % len(styles)],
        }
        for n, case in enumerate(planned, 1)
    ]


def replace(
    planned: list[dict[str, Any]],
    flagged: set[str],
    entries: list[Entry],
    texts: dict[str, str],
    seed: int,
    reuse: bool = False,
) -> list[dict[str, Any]]:
    """The plan with each flagged case given new sources by the planning rules: a
    first source of the format its old first source had (so each format keeps its
    cases) and, where the type takes two, a second; never a source any case of the
    plan has used, the flagged ones included, unless the plan reuses sources and none
    is left."""
    rng = random.Random(seed)
    pool = usable_pool(entries, texts)
    groups = conversations.subjects(pool)
    by_id = {e["id"]: e for e in entries}
    used = Counter(source for case in planned for source in case["sources"])
    topics = Counter(by_id[source]["topic"] for source in used)
    replaced = []
    for case in planned:
        if case["id"] not in flagged:
            replaced.append(case)
            continue
        kind = case["type"]
        name = by_id[case["sources"][0]]["format"]
        old = set(case["sources"])  # never the sources the writer flagged
        named = [e for e in pool if e["format"] == name and e["id"] not in old]
        first = pick(named, used, topics, rng, reuse)
        if first is None:
            raise ValueError(f"no {name} source left to replace {case['id']}")
        sources = [first]
        if SOURCES.get(kind, 1) == 2:
            other = second_source(kind, first, pool, groups, used, topics, rng, reuse)
            if other is None and kind == "comparison":
                raise ValueError(f"no second {name} source to replace {case['id']}")
            sources += [other] if other else []
        replaced.append({**case, "sources": [e["id"] for e in sources]})
    return replaced


def excerpt(text: str, limit: int, rng: random.Random) -> str:
    """The text if it fits; else a PDF from a random page's start, or a page's text
    from a random paragraph, cut at `limit` characters."""
    if len(text) <= limit:
        return text
    marks = [m.start() for m in PAGE_MARK.finditer(text)]
    if not marks:
        return conversations.excerpt(text, limit, rng)[0]
    starts = [s for s in marks if s <= len(text) - limit] or [marks[0]]
    start = rng.choice(starts)
    return text[start : start + limit]


def part_text(
    planned: list[dict[str, Any]],
    by_id: dict[str, Entry],
    texts: dict[str, str],
    limit: int,
    rng: random.Random,
    shown: dict[str, dict[str, Any]],
    taken: dict[str, list[str]],
    show: Show | None = None,
) -> str:
    """One part file: each case's wordings and its sources as the writer sees them,
    with the quotes earlier keys took from a source (`taken`, by entry id) listed
    under it. What is shown is recorded in `shown` by source id. `show` writes the
    images a source is seen by (a picture, a page's screenshot, a PDF's pages) and
    names them."""
    lines = []
    for case in planned:
        lines += [f"# Case {case['id']}: {case['type']}", ""]
        if "styles" in case:
            lines += [f"Wordings: {', '.join(case['styles'])}", ""]
        for number, entry_id in enumerate(case["sources"], 1):
            source_id = f"{case['id']}-s{number}"
            text = excerpt(texts[entry_id], limit, rng)
            shown[source_id] = {"entry": entry_id, "text": text}
            entry = by_id[entry_id]
            lines += [
                f"## Source {source_id} ({entry['format']})",
                f"URL: {entry['url']}",
            ]
            for name in show(entry, source_id, text) if show else []:
                lines.append(f"See: {name}")
            whole = len(texts[entry_id])
            if len(text) < whole:
                lines.append(f"(part of a longer source: {whole:,} characters)")
            if taken.get(entry_id):
                lines += ["", "Already asked about (ask about something else):"]
                lines += [f"- {quote}" for quote in taken[entry_id]]
            lines += ["", text, ""]
    return "\n".join(lines)


def rebundle(
    seen: dict[str, Any],
    flagged: set[str],
    entries: list[Entry],
    texts: dict[str, str],
    limit: int,
    seed: int,
) -> tuple[dict[str, Any], str]:
    """What the writer has seen, with the flagged cases given new sources, and the
    part file that shows them. The flagged cases' old sources leave `sources`."""
    reuse, taken = seen.get("reuse", False), seen.get("taken", {})
    planned = replace(seen["plan"], flagged, entries, texts, seed, reuse)
    shown = {
        source_id: source
        for source_id, source in seen["sources"].items()
        if source_id.rsplit("-s", 1)[0] not in flagged
    }
    by_id = {e["id"]: e for e in entries}
    cases = [case for case in planned if case["id"] in flagged]
    text = part_text(cases, by_id, texts, limit, random.Random(seed), shown, taken)
    return {**seen, "plan": planned, "sources": shown}, text


def bundle(
    planned: list[dict[str, Any]],
    entries: list[Entry],
    texts: dict[str, str],
    notes: dict[str, str],
    out: Path,
    per_part: int,
    limit: int,
    seed: int,
    reuse: bool = False,
    taken: dict[str, list[str]] | None = None,
    rendered: Path | None = None,
) -> list[Path]:
    """Write the brief and writer's instructions (`notes`: file name -> text), the
    part files, `plan.json` (what the writer saw, whether the plan reuses sources,
    and the quotes earlier keys took, by entry id) and `corpus/` (every indexed
    source's whole text, with `corpus/index.md` naming each file's URL). Given
    `rendered` (a `web-render` folder), each source is also shown as a visitor sees
    it: its screenshot, picture or page images (`asset_writer`)."""
    taken = taken or {}
    show = asset_writer(out, rendered) if rendered else None
    rng = random.Random(seed)
    by_id = {e["id"]: e for e in entries}
    out.mkdir(parents=True, exist_ok=True)
    for name, text in notes.items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
    shown: dict[str, dict[str, Any]] = {}
    parts = []
    for first in range(0, len(planned), per_part):
        cases = planned[first : first + per_part]
        part = out / f"part-{first // per_part + 1}.md"
        text = part_text(cases, by_id, texts, limit, rng, shown, taken, show)
        part.write_text(text, encoding="utf-8", newline="\n")
        parts.append(part)
    saw = {"plan": planned, "sources": shown, "reuse": reuse, "taken": taken}
    seen = json.dumps(saw, indent=1, ensure_ascii=False)
    (out / "plan.json").write_text(seen + "\n", encoding="utf-8", newline="\n")
    corpus = out / "corpus"
    if corpus.exists():
        shutil.rmtree(corpus)
    corpus.mkdir()
    index = ["# Corpus: every indexed source's whole text", ""]
    for number, entry in enumerate(e for e in entries if texts.get(e["id"])):
        name = f"{number:03d}.txt"
        (corpus / name).write_text(texts[entry["id"]], encoding="utf-8", newline="\n")
        index.append(f"- {name}: {entry['url']}")
    (corpus / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return parts


def asset_writer(out: Path, rendered: Path) -> Show:
    """Writes into `out` what a source is seen by and names it: a picture's file,
    a page's full screenshot (from `rendered`), or a document's shown pages drawn
    at ASSET_SCALE."""
    import pypdfium2

    def show(entry: Entry, source_id: str, text: str) -> list[str]:
        if entry["format"] in PICTURES:
            name = f"pictures/{Path(entry['source']).name}"
            (out / "pictures").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry["source"], out / name)
            return [name]
        if entry["id"].startswith("page:"):
            slug = Path(entry["source"]).stem
            shot = rendered / f"{slug}.png"
            if not shot.exists():
                return []
            (out / "screenshots").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(shot, out / "screenshots" / f"{slug}.png")
            return [f"screenshots/{slug}.png"]
        path = Path(entry["source"])
        if entry["format"] == "docx:declaration":
            path = config.READINGS / "rendered" / f"{entry['id'].split(':', 1)[1]}.pdf"
        names = []
        document = pypdfium2.PdfDocument(str(path))
        (out / "pages").mkdir(parents=True, exist_ok=True)
        for mark in PAGE_MARK.finditer(text):
            page = int(mark.group(1))
            name = f"pages/{source_id}-p{page}.png"
            document[page - 1].render(scale=ASSET_SCALE).to_pil().save(out / name)
            names.append(name)
        document.close()
        return names

    return show


def evidence_problems(
    item: dict[str, Any],
    label: str,
    texts: dict[str, str],
    pdfs: set[str],
    pictures: frozenset[str] = frozenset(),
) -> list[str]:
    """Problems in one quote: its source, its page for a PDF, and its text. A
    picture may be cited as what it shows (`"visual": true`, no quote, X43)."""
    source = str(item.get("source", ""))
    if source not in texts:
        return [f"{label}: {source} is not one of the case's sources"]
    if item.get("visual") is True:
        if source not in pictures:
            return [f"{label}: only a picture can be cited as what it shows"]
        return []
    text = texts[source]
    page = item.get("page")
    if source in pdfs:
        pages = page_texts(text)
        if not isinstance(page, int) or page not in pages:
            return [f"{label}: a PDF quote needs the number of a page shown"]
        text = pages[page]
    elif page is not None:
        return [f"{label}: a web page has no page number"]
    problem = conversations.quote_problem(str(item.get("quote", "")), text)
    return [f"{label} {problem}"] if problem else []


def case_problems(
    case: dict[str, Any],
    planned: dict[str, Any],
    shown: dict[str, dict[str, Any]],
    pdfs: set[str],
    corpus: list[str],
    pictures: frozenset[str] = frozenset(),
) -> list[str]:
    """Problems in one case against its plan, the text shown and the corpus."""
    cid = planned["id"]
    if case.get("flag"):
        return [f"{cid}: flagged by the writer, to be replaced"]
    found = [
        f"{cid}: {field} is missing or not a {kind.__name__}"
        for field, kind in CASE_FIELDS.items()
        if not isinstance(case.get(field), kind)
    ]
    if found:
        return found
    kind = planned["type"]
    if case["type"] != kind:
        found.append(f"{cid}: type is {case['type']}, planned {kind}")
    status = STATUS.get(kind, "answered")
    if case["expected_status"] != status:
        found.append(f"{cid}: a {kind} case is {status}")
    styles = [str(w.get("style")) for w in case["wordings"]]
    wanted = planned.get("styles", STYLES)
    if sorted(styles) != sorted(wanted):
        found.append(f"{cid}: wordings are {styles}, not {wanted}")
    for wording in case["wordings"]:
        if not str(wording.get("text", "")).strip():
            found.append(f"{cid}: an empty wording")
        elif BUNDLE_WORDS.search(str(wording["text"])):
            found.append(f"{cid}: a wording names a source id, page marker or excerpt")
    count = len(planned["sources"])
    texts = {f"{cid}-s{n}": shown[f"{cid}-s{n}"]["text"] for n in range(1, count + 1)}
    if status == "answered":
        found += answered_problems(case, cid, kind, texts, pdfs, pictures)
    elif case["parts"]:
        found.append(f"{cid}: {status} must have no parts")
    if kind == "emergency" and case["expected_answer"]:
        found.append(f"{cid}: an emergency leaves expected_answer empty")
    if kind in {"absent", "false_premise", "injection"} and not case["must_not"]:
        found.append(f"{cid}: a {kind} case needs must_not")
    if kind == "absent":
        found += absence_problems(case, cid, corpus)
    return found


def answered_problems(
    case: dict[str, Any],
    cid: str,
    kind: str,
    texts: dict[str, str],
    pdfs: set[str],
    pictures: frozenset[str] = frozenset(),
) -> list[str]:
    """An answered case: enough parts, each with checked quotes, every source used."""
    found = []
    if len(case["parts"]) < MIN_PARTS.get(kind, 1):
        found.append(f"{cid}: a {kind} case needs {MIN_PARTS.get(kind, 1)}+ parts")
    cited = set()
    for number, part in enumerate(case["parts"], 1):
        label = f"{cid} part {number}"
        found += [
            f"{label}: no {f}" for f in conversations.PART_FIELDS if not part.get(f)
        ]
        evidence = part.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            found.append(f"{label}: no evidence")
            continue
        for index, item in enumerate(evidence, 1):
            label_item = f"{label} quote {index}"
            found += evidence_problems(item, label_item, texts, pdfs, pictures)
            cited.add(str(item.get("source", "")))
    found += [f"{cid}: {s} is never quoted" for s in sorted(texts.keys() - cited)]
    return found


def absence_problems(case: dict[str, Any], cid: str, corpus: list[str]) -> list[str]:
    """An absent figure: two or more search terms, none found in any source."""
    terms = case.get("absence_terms")
    if not isinstance(terms, list) or len(terms) < 2:
        return [f"{cid}: an absent case needs 2+ absence_terms"]
    found = []
    for term in terms:
        wanted = keys.normalise(str(term))
        if any(wanted in text for text in corpus):
            found.append(f"{cid}: absence term {term!r} is in the corpus")
    return found


def quotes(case: dict[str, Any]) -> list[str]:
    """A written case's evidence quotes, normalised; none for a malformed case."""
    parts = case.get("parts")
    found = []
    for part in parts if isinstance(parts, list) else []:
        evidence = part.get("evidence") if isinstance(part, dict) else None
        for item in evidence if isinstance(evidence, list) else []:
            found.append(keys.normalise(str(item.get("quote", ""))))
    return [quote for quote in found if quote]


def repeat_problems(
    written: dict[str, dict[str, Any]], taken: dict[str, list[str]]
) -> list[str]:
    """Cases asking what is already asked: a quote that overlaps one an earlier key
    took (`taken`) or one an earlier case of this key uses. A held-out key must ask
    new facts, and two cases on one fact count as one."""
    owners = {
        keys.normalise(quote): "an earlier key"
        for found in taken.values()
        for quote in found
    }
    problems = []
    for cid in sorted(written):
        mine = quotes(written[cid])
        for quote in mine:
            clash = next((o for q, o in owners.items() if quote in q or q in quote), "")
            if clash:
                problems.append(f"{cid}: a quote is already used by {clash}")
        owners.update(dict.fromkeys(mine, cid))
    return problems


def key_problems(
    key: dict[str, Any],
    seen: dict[str, Any],
    pdfs: set[str],
    corpus: list[str],
    pictures: frozenset[str] = frozenset(),
) -> list[str]:
    """Problems in a key, checked against the plan and the text its writer saw.
    `pdfs` names the shown sources that are PDFs; `corpus` holds every source's
    normalised text. Problems name ids, never key text."""
    planned = {c["id"]: c for c in seen["plan"]}
    written = {str(c.get("id")): c for c in key.get("cases", [])}
    found = []
    if len(written) != len(key.get("cases", [])):
        found.append("case ids are not unique")
    found += [f"{cid}: not written" for cid in sorted(planned.keys() - written)]
    found += [f"{cid}: not planned" for cid in sorted(written.keys() - planned)]
    for cid in sorted(planned.keys() & written):
        found += case_problems(
            written[cid], planned[cid], seen["sources"], pdfs, corpus, pictures
        )
    if seen.get("reuse"):
        found += repeat_problems(written, seen.get("taken", {}))
    return found


def sealed_evidence(item: dict[str, Any], entry: Entry) -> dict[str, Any]:
    """One quote in the sealed key, its kind named by its source: a page's text, a
    PDF's or Word file's text by page, a picture's own words, or a picture as what
    it shows (no quote)."""
    if entry["format"] in PICTURES:
        visual = item.get("visual") is True
        return {
            "kind": "image_visual" if visual else "image_text",
            "url": entry["url"],
            "page": entry.get("page"),
            "image": entry["id"].split(":", 1)[1],
            "quote": "" if visual else item["quote"],
        }
    if item.get("page") is None:
        kind = "page_text"
    else:
        kind = "docx_text" if entry["format"] == "docx:declaration" else "pdf_text"
    return {"kind": kind, "url": entry["url"], "page": item.get("page"),
            "quote": item["quote"]}  # fmt: skip


def sealed(
    key: dict[str, Any], seen: dict[str, Any], entries: dict[str, Entry]
) -> dict[str, Any]:
    """The key in the shape of the other held-out keys: evidence by URL and page,
    `must_not` as rules, and each case's source URLs and formats kept for reporting
    per stratum. `entries` are the catalogue's entries by id."""
    planned = {c["id"]: c for c in seen["plan"]}
    cases = []
    for case in key["cases"]:
        parts = []
        for part in case["parts"]:
            evidence = []
            for item in part["evidence"]:
                entry = entries[seen["sources"][item["source"]]["entry"]]
                evidence.append(sealed_evidence(item, entry))
            fields = {f: part[f] for f in conversations.PART_FIELDS}
            parts.append({**fields, "evidence": evidence})
        sources = [entries[entry_id] for entry_id in planned[case["id"]]["sources"]]
        found = {
            "id": case["id"],
            "type": case["type"],
            "expected_status": case["expected_status"],
            "expected_answer": case["expected_answer"],
            "parts": parts,
            "must_not": [{"rule": rule} for rule in case["must_not"]],
            "wordings": case["wordings"],
            "sources": [entry["url"] for entry in sources],
            "formats": [entry["format"] for entry in sources],
        }
        if case.get("absence_terms"):
            found["absence_check"] = {
                "terms": case["absence_terms"],
                "scope": "every indexed page and PDF, as the writer's corpus held them",
            }
        cases.append(found)
    version = int(CASE_ID.findall(seen["plan"][0]["id"])[0])
    return {"version": version, "cases": cases}
