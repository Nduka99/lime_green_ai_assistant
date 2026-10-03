# 0028. The answer path after E5: whole lists, a scoped second search, fairer checks, no gate

- Status: Accepted (the embedding model approved 30 September, served on its own port)
- Date: 2026-09-30
- Origin: E5 (`evaluation/reports/E5-fixes.md`), after the S2b gate and the R0
  reliability readout

## Context

On held-out v4 the candidate answered 43 cases and 4 were wrong (upper bound 21.6%,
against the 5% release bar). Attribution put the wrong answers and the lost coverage in
four places: evidence that never reached the model (lists cut between passages, a price
fence that hid whole passages, look-alike documents crowding out the product asked
about), a model that states a nearby fact when a part's evidence is missing,
verification that removed correct claims, and no signal able to catch the rest.

Every change below was chosen offline, on benchmarks built from existing records, by a
rule written before it was scored. No end-to-end run chose anything; the first full run
is the held-out v5 gate.

## Decision

- **Index (stage A′).** A web list stays one paragraph with the line that introduces it,
  so the splitter keeps it whole when it fits. The price fence removes the sentences that
  state a price, not the passage. Bold lines stay ordinary paragraphs: as section
  breaks they cut sections into short passages that crowded out other evidence
  (frozen90 lost two cases), which the rule rejected.
- **Search (B4).** After each search, a second search inside the products the query
  names adds its best 4 passages, within a budget of 32. A passage's product is its
  title up to " — " (a PDF is titled after the product page linking it), so no schema
  change is needed. A named product's copy of shared text replaces another product's
  copy, so the product asked about is the one cited.
- **Verification (D).** A quote the model cited to the wrong supplied passage is cited
  to the passage that holds it; a number is supported when a cited passage holds it
  with the name it is part of ("Silic8", "ISO 9001"). Fragments joined by "…" still
  fail: accepting them also restored claims their evidence does not state.
- **Notice (E).** When a part of the question has no verified claim, the notice names
  it.
- **No sufficiency gate (C).** Eleven detectors from four families (cross-encoder
  relevance, entailment, extractive reading with a no-answer option, word coverage)
  and their combinations reached at most 0.76 AUC on 856 labelled claims; none could
  withhold half the wrong claims at a cost of one correct claim in ten. The published
  best on this kind of near-miss evidence is 0.71.
- **Models.** The reranker stays (bge-reranker-v2-m3): the Qwen3 rerankers, 0.6B and
  4B, reached less evidence on this corpus. Qwen3-Embedding-4B (vectors cut to the
  index's 1,024 values) reached more on every set; served on the CPU alone it needs
  4.7 GB of RAM and no GPU, and adds about 0.4 s per search. It runs on port 8084
  beside the 0.6B model on 8081, which the page on 8090 and the versions built with it
  still need; the candidate is index version 17.

## Consequences

- On the four development sets, evidence reached rises with every set; held-out v4
  from 109 to 116 of 130 parts with the current embedder, and to 119 with the 4B one.
- A question kept as one part by the first request cannot have its unanswered piece
  named by the notice; the price fence then withholds a price silently.
- The wrong answers that remain come mostly from a model that answers a neighbouring
  question when evidence is missing. No detector found here stops them; the remaining
  levers are more evidence reaching the model, and, later, a generator trained to
  refuse on missing evidence (needs rented GPU time, the user's decision).
- Held-out v5 certifies the result: run once, blind grading, three graders.
