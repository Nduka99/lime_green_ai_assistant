# E7. Slot binding: checking what a claim answers, not what it is about

Status: S1 designed, not yet run (30 September). Every rule below is written before the
run it governs; results are added below them.

## Question

After E5, the evidence for a question's parts reaches the model far more often (held-out
v4: 0.838 → 0.915 of keyed parts), and every wrong answer attributed so far is a binding
error: a true fact about the wrong product or property placed in the asked slot
(substitution: plant *opened* for *built*, a *system's stored* carbon for *boards'
embodied* carbon, *products'* lead time for *samples'* delivery), or an item from a
neighbouring list. Eleven detectors from four families judged whole claims against whole
questions and reached at most 0.76 AUC on `claims-dev`; the published best on
"topical but answerless" evidence is 0.71 (arXiv 2609.37469). **Does comparing slots
instead of texts (the subject and property a part asks for against the subject and
property each quote states) separate the claims that answer from those that do not?**

## Why it might

In a substitution the two texts share the product family, the topic and most words;
only one slot differs, and whole-text signals are dominated by what is shared. Reduced
to their slots, the pair is two short phrases that differ in the thing that matters.
Checking at the granularity of (subject, predicate, object) triplets beats sentence- and
response-level checking by 6.8 to 26.1 points for support (RefChecker, arXiv
2405.14486); here the same granularity is applied to relevance. Each side is read
alone: the asked slots from the part without the evidence, the stated slots from the
quote and its document's title without the question, so neither can be bent to fit the
other. No model is trained (the user ruled out fine-tuning for now).

## S1: the offline test on `claims-dev`

**Extraction** (`limespec.slots`, the prompts committed before the run), by the
generator (Qwen3.6-35B-A3B on 8080, greedy):
- *asked slots*: for each question, all its parts in one request; for each part, every
  (subject, property) it asks for (a part asking two things gives two);
- *stated slots*: for each distinct source of a claim (its document title, heading and
  quote), in requests of up to 8 sources that name no question; each (subject,
  property) the quote states.
The extraction file is registered in `claims-dev` before any comparator is scored.

**Comparators**, each giving a claim a score, higher meaning it answers its question:
- (a) *product*: 1 when the question names no product (`scope.naming` over index
  version 17's product names) or when one of the claim's sources belongs to a named
  product (`scope.scope_of` its title); otherwise 0;
- (b) *phrase relevance*: the current reranker (bge-reranker-v2-m3) with each asked
  slot's phrase ("property of subject") as the query and each stated slot's phrase as
  a document; the claim's score is its best pair;
- (c) *phrase judge*: the generator asked, for each pair of phrases and with nothing
  else, whether the second gives the property the first asks, of the same subject;
  the score is the probability of "yes" from its log-probabilities; the claim's score
  is its best pair;
- (d) (a) then (b), and (a) then (c): the product check's zero stands, else the phrase
  score.

**Rule (E5 stage C's, unchanged):** a comparator qualifies if, at the threshold set by
conformal risk control on the calibration half of the cases (seed 5), it withholds at
most 1 in 10 correct claims and catches at least half of the not-correct ones on the
other half, and qualifies on at least half of seeds 1–20. AUC and results by label
(off the question, incorrect, forbidden) are reported for every comparator. If more
than one qualifies, the one catching most not-correct claims at seed 5 is chosen; ties
go to the one with fewer model requests. **If none qualifies:** the report diagnoses
where extraction or comparison fails (read on the not-correct claims), a literature
search on that point follows, and no gate is built.

**How the prompts were settled, before the run.** A first smoke run of the extraction
and the judge on five `claims-dev` claims (three off the question, two correct: read,
not scored) showed three faults of design: stated properties came out as verb
fragments ("opened in", "have") because the prompt said to leave out the value;
phrases joined as "property of subject" read badly; and the judge rejected a quote
giving one item of an asked list. The fixes are general: both prompts ask for the
property as a short noun phrase naming the kind of information (examples chosen from
no test item: "drying time", "fire classification", "backgrounds it suits"); a slot
reads "subject: kind of information"; the judge says yes when the stated slot gives the
asked kind of information about the same subject wholly or in part (such as one item of
a list), and no for another kind, or the same kind about another subject. They were
checked by reading eight claims of the earlier `relevance-dev` benchmark (not the test
set): claims not answering scored 0.02–0.39, three of four answering 0.81–1.0, the
fourth 0.07 (its quote had no document title, which real sources carry). The prompts
are then frozen at the commit that precedes the run. The five claims seen stay in the
benchmark; they are 5 of 856.

## S3: an in-domain near-miss set, labelled by construction (written before it is built)

Evaluation data, never training data. From index version 17: 300 passages drawn with seed
71, stratified by document kind (product page, data sheet, safety data sheet, guide or
article; compiled product lists and passages under 200 characters left out). For each
passage the generator writes, in one request that sees only the passage and its title:
- two **answerable** questions, each with the quote (word for word) that answers it;
- two **near-miss** questions about the same subject and topic that the passage does
  not answer, each with the quote a careless reader would take as the answer (as SQuAD
  2.0's unanswerable questions were written against their paragraphs).
Quotes must be found in the passage by `verify.find_quote`, else the question is
dropped. Gemma 4 26B then reads each question with its passage alone and says whether
the passage answers it; a question is kept only when Gemma agrees with its label. The
kept set is registered as `nearmiss-dev` before any use, and v5's key is never read or
used. It serves: (i) the gate's calibration at a scale `claims-dev` lacks; (ii) a second
test of S1's comparator on questions it was not chosen on: the rule's shares, read as
answerable (question, answering quote) kept and near-miss (question, tempting quote)
caught; (iii) S4's substitution rate: the answer request run on each near-miss question
with its passage, a claim for it counting as a substitution.

## S4: the generator, Gemma 4 26B against Qwen3.6 (written before it runs)

Each model answers every kept `nearmiss-dev` question from its passage alone, with the
assistant's own answer request and verification (`evaluation nearmiss-answer`).
Measured: the **substitution rate** (near-miss questions given at least one verified
claim) and the **answer rate** (answerable questions given at least one), each with a
Wilson 95% interval, and seconds per request. **Rule:** Gemma is a candidate to replace
Qwen only if its substitution rate is lower with intervals not overlapping, and its
answer rate is at most 2 points lower; a candidate then goes to the dev sets' replayed
requests before any startup-line change, which is the user's decision.

## Results

**S1 extraction** (`78e0d29`; 30 September, 2,046 s on the generator alone): 379
distinct parts and 572 distinct sources read; saved as `claims-dev/slots.json` and
registered before any comparator was scored.

**S1, comparators (a) and (b): neither qualifies.**

| Comparator | AUC | Correct withheld (seed 5) | Not correct caught | Qualifies (seeds 1–20) |
|---|---|---|---|---|
| (a) product check | 0.547 | 0 of 370 | 0 of 30 | no (0) |
| (b) reranker on slot phrases | 0.680 | 27 of 370 | 3 of 30 | no (0) |
| (a) then (b) | 0.680 | 0 of 370 | 0 of 30 | no (0) |

The product check fails 71 of 755 correct claims and only 19 of the 101 not correct:
correct answers often cite articles and system pages that name the product without
belonging to it, so a product's scope is too blunt a rule (its binary score also gives
the conformal threshold nothing to cut between). The reranker reads short slot phrases
no better than whole texts (0.680 against 0.717). Read while the judge ran (its prompts
and code frozen): the extracted slots do expose the mismatches in words ("year new
production plant was built" against "plant: opening date"; "iso 9001 certificate:
scope" against "the business: ISO certification"; "Mesh Coat: incompatible materials"
against "Meshcoat: mixing instructions"), which is what the judge is asked to read.

**S1, comparators (c) and (d): neither qualifies. S1 fails; no gate is built.**

| Comparator | AUC | Correct withheld (seed 5) | Not correct caught | Qualifies (seeds 1–20) |
|---|---|---|---|---|
| (c) phrase judge | 0.689 | 40 of 370 | 8 of 30 | no (0); median caught 30% |
| (a) then (c) | 0.692 | 0 of 370 | 0 of 30 | no (0) |

By label, the judge reads off-question claims at 0.693, incorrect ones at 0.798 and
forbidden ones at 0.577: no better than the whole-text detectors of E5 (best 0.755).

**Diagnosis, read on the claims it gets most wrong in each direction.** Two extraction
faults exist but are small: 7 of 572 sources received another source's slots when eight
were read in one request (their answers drifted out of position; nothing in a list
answer ties an item to its input), and 3 of 379 parts hit the four-slot cap. The cause
is the abstraction itself. Judged one pair at a time, outside any list, the judge still
passes "Lime Green: year new production plant was built" against "plant: opening date"
(0.78) and fails "Duro base coat: cement content" against "Duro lime render:
composition" (0.03) and "cavity: ventilation method" against "the cavity: ventilation
requirement" (0.15). A (subject, property) slot drops the value, and the value is what
decides whether a quote answers: "completely free of cement" answers the cement content;
the slot "composition" cannot show it. Near-synonymous properties ("built", "opened")
stay as close for the judge as they were in whole texts. RefChecker's triplets keep the
object; a relevance check that keeps the object is a claim against a question again,
which is where E5's detectors stopped. Batching was checked separately: the same eight
pairs judged alone and as a list moved in both directions but did not separate.

What follows, by the plan: S3 and S4 run (the generator comparison needs no gate), and
the near-miss set gives every detector a second, larger test with labels by
construction: if a detector reads that set well but `claims-dev` poorly, the benchmark's
own labels and composition become the question.
