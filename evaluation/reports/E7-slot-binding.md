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

## Results

*(added after each run)*
