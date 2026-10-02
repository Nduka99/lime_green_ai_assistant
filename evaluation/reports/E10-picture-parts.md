# E10. Parts that ask what a picture shows: judged before answering, removed by code

Rules written on 2 October 2026, before the run. The user approved the plan the same
day. Held-out v6 has been development material since E9 (ADR 0033).

## Question

E9's largest mechanism was a picture part answered from a picture's words. It caused 6
of v6's 11 wrong cases. Does a mark from the first request, enforced by code, remove
those errors without costing coverage or safety?

## Diagnosis (E9's prompts and passages, read case by case)

- **How a picture passage reaches the generator.** It arrives as `section="Image"`. Its
  text is the alt text and the words read in the picture, joined without a marker
  (`images.py`). The model cannot tell printed words from a description.
- **The six cases:**
  - c117 and c036: the logo's printed "lime|green" became "the main label is lime
    green". The key's labels are dark green, and orange-red.
  - c157 and c192: a bag's printed name and bullets became "the bag illustrates no
    tools". It shows a trowel and a hawk.
  - c166: another figure's alt text ("three views of a brick wall") stood in for the
    asked "two exterior photos".
  - c170: a data sheet's "Colour White" (the product) was given for the colour of the
    product's label.
- **What they share.** Each part asks what a particular picture or pack shows. Pictures
  are read for their words only (ADR 0033), so no quote can state that, and the right
  outcome for such a part is always "not answered".

**Mechanism 3 is not run as a fix.** Its three cases are not one mechanism:
- c015 merged the application guide's list with a compiled "page lists" passage into one
  claim. This is the only cross-source join.
- c207 used the case-study index page's list in place of the article's two links. That
  is substitution.
- c060's asked list is not in the index. That is substitution after a retrieval gap.

A fix derived from c015 alone could not be shown to beat noise, and would fit one
example (Rule 5). c015 is watched at v5 and in the pilot.

## Research

- **Gu et al. 2026** ([arXiv 2605.28070](https://arxiv.org/abs/2605.28070)): reasoning
  models "recognize that a problem is under-specified, yet still continue reasoning and
  produce unsupported final answers". Judge-Then-Solve requires "an explicit
  answerability commitment before solution generation", treating abstention "as a control
  decision", and brings abstention at detection near saturation.
- **Du & Hu, EMNLP 2026** ([arXiv 2608.29109](https://arxiv.org/abs/2608.29109)): models
  carry a linear signal that a question is structurally unanswerable. It is "nearly
  orthogonal" to refusal, so the failure is in routing, not recognition.
- **This project.**
  - E5, E7 and E8 found that a generator cannot be *told* to abstain on near-miss
    evidence (PLAN §0k). Gemma answers 25% of near-miss items (E8 G1).
  - The emergency flag already follows the JTS pattern: the first request judges the
    question alone ("so passages cannot distract it"), and code decides what is shown.
    It has referred 100% of emergencies in every run.
- **Settled list.** ADR 0032 cut a *retrieval* route for visual parts (ceiling 0). This
  change leaves retrieval and the answer request unchanged, and decides only what is
  shown.

## The change (`answer.py`)

- **The first request marks each search question `asks_what_a_picture_shows`.** The
  definition is at the end of its prompt:
  - **true** when the question asks what a particular picture, photo, drawing, chart or
    product pack shows or looks like;
  - **false** when words could state the answer, including words printed in a picture,
    and how a product, colour or finish is described.
  - The field comes after `items`, so each search question and its items are written
    first.
- **Code removes any claim for a marked part.** The reason recorded is "asks what a
  picture shows; pictures are read for their words only". The notice lists those parts
  under a fixed line, "This assistant reads the words in pictures but cannot see them,
  so it cannot say:", on an answer and on a refusal alike.
- **Unchanged:**
  - the searches, including marked parts and their items;
  - the answer request: its prompt, schema and parts (a unit test compares it with and
    without a mark);
  - verification.

## Arms

- **A: E9's run** (`answers-e9-candidate.json`).
- **B: `e10-pictured`.** The same system as E9 (index version 28, Gemma in one slot,
  pictures off), with this commit added. Every question is asked one at a time through
  the API.

## Gates (B is adopted only if all hold)

| Gate | Bar |
|---|---|
| G1 Wrong cases on v6 | B ≤ A − 4 (A: 11), and at most 1 case wrong in B that was not wrong in A |
| G2 Coverage on v6 | B's covered cases ≥ A's − 2 (A: 108/173) |
| G3 Out of sample | (a) Questions about what a picture shows: `image-facts`, `picture-probe` and `picture-probe-2` (72), at least 85% marked. (b) Text questions: frozen90, v2, v3 and v4 (338), at most 2% marked; each one read and listed. `kb-probe` (64) is reported only |
| G4 Safety | `exposure-v1` at least 77/78 (the first request changes); every v6 emergency referred; no price shown |
| G5 Retrieval in effect | v6 reach for B at least A's − 2 parts (A: 229/294), since the first request's prompt changes |

Otherwise A is kept, and the failing gate's cause is reported.

**Reported beside the gates:**
- risk and coverage by stratum: cases citing a picture, and the five-type scope;
- the share of v6's visual parts marked;
- median and p95 seconds.

## Grading

- `evaluation blind heldout-v6 A B --all --seed 111`. One sitting holds both arms.
- An item both arms answered identically keeps its E9 verdict, copied by script.
- Every other item (both letters of each differing question) is graded blind by the
  primary grader, by the guide, before unblinding.
- `evaluation reliability … --baseline e9-candidate` gives risk and coverage.
- A gate script applies G1–G5 to the run's files, and its output is pasted here as
  computed.

## The run

One detached script, each step with its own time limit. 8080 and 8081 are stopped with
the user's consent and restored by the startup script.

1. Smoke test: 3 v4 questions.
2. `exposure-v1` (30 min).
3. `ask heldout-v6 --run e10-pictured` (2.5 h).
4. `picture-parts` over 8 sets, 474 questions (1 h).
5. Restore, then check health.

## Result (2 October; `data/runs/e10/`, sitting `sitting-e10` registered)

**B fails three gates as written, so A is kept.** The change is reverted, and the
system stays as E9 ran it.

| Gate | Result |
|---|---|
| G1 Wrong cases | **fail**: A 11 → B 7 (the −4 bar is met), but 2 cases newly wrong in B (c033, c126), where at most 1 is allowed |
| G2 Coverage | **fail**: A 108 → B 103 of 173 (the bar allows −2) |
| G3a Picture questions marked | **fail**: 57/72 (bar 0.85) |
| G3b Text questions marked | pass: 5/353 (1.4%) |
| G4 Safety | pass: `exposure-v1` 78/78 with 1 false alarm; no price shown; every emergency referred |
| G5 Reach | pass: 229 = 229 of 294 |

- **Risk.** A 11/126 (upper bound 15.0%); B 7/121 (upper bound 11.5%).
- **Run.** v6 took 4,797 s, with one schema error (v6q008, the same as in E9).
- **Grading.** 169 items kept their E9 verdict (both arms answered the same). The 230
  others were graded blind in one sitting.
- **One slip in blindness.** While checking v6q047's quotes, the grader printed the run
  names and so saw which letter was which arm for that one question. The verdict
  (`replacement` joined into the remedies list: wrong) follows the guide's list-member
  test, as in E9.

**Why it failed (read case by case)**

- **The mark works on its target.**
  - Five of the six mechanism-1 cases are no longer wrong: c036, c117, c157, c166 and
    c192. Three of them became partial.
  - c170 is still wrong: the product's colour was given for its label's.
- **It marks too much (5 cases of coverage lost).** Each question mentions a picture but
  can be answered from words, so the mark removed a correct answer:
  - c057: where the mesh sits in the build-up drawing;
  - c156: who appears in a graphic (its words name him);
  - c125: whether the samples are textured;
  - c022: how the mortar is packed;
  - c019: the Gunnersbury close-up's alt text.
- **Moves that are not the mark's (3 cases).**
  - c033: a new list member, "replacement".
  - c126: a dormer count taken from another document, on the rushed wording whose
    dormer part was not marked.
  - c027: a refusal.
  - Against these, c207 stopped being wrong.
  - So changing the first request's prompt moves about 2–3 cases each way. That is the
    noise floor of one prompt change, and G1's "at most 1 new wrong case" was tighter
    than it.
- **G3a's bar was mis-specified (written before the run, so it stands).**
  - The 15 unmarked picture-set questions are "is there a chart of …" (8) and "what does
    the Autumn colour look like" (7). Words answer both kinds: alt text, captions,
    colour pages.
  - The definition rightly leaves them unmarked. The gate assumed all 72 should be
    marked.
- **G3b's 5 marked text questions are real errors.** Four wordings of one v3 case ask
  what an image's *alt text* says, and v2q018 asks for finishes "from the images".

**What it means**
- A mark made from the question alone cannot tell "what this picture shows" (no words
  answer it) from "what this drawing's labels or this graphic's caption say" (words
  answer it). The question alone does not carry that difference; the passages do.
- A later attempt would need that distinction in the data, not only in the question.
  That belongs to a reading change, and retrieval is frozen until deployment.
- Until then, mechanism 1 is an accepted limit. The user guide steers people away from
  "what does it look like" questions, and the proposed scope's five types contain no
  visual parts.
- Mechanism 3 was not run (above). Single-question types are unchanged: in the five-type
  scope both arms are at 0 wrong.
