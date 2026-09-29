# S2. Does the whole site with its PDFs answer as well as today's index?

Design and gate written on 29 September 2026, before any answer was asked of the
candidate (PLAN §0f, Phase 3, slice S2).

## Question

The live index (version 4) holds 68 pages of the site in 315 passages. The candidate
(version 11) holds every cached page of the site (160) and every Lime Green PDF (98),
read as X8 selected (Docling with GLM-OCR table structure, only what the page shows,
D86–D87) and cut into passages as X9 selected (page-sized, tables inline): 1,845
passages. Quotes now match across the page's typography and Docling's superscript
spacing (X9 report, "Follow-up: quote matching"). Does the candidate answer the keyed
questions at least as well, never show a price, refer every emergency, and hold the
evidence for enough of conv-v1's follow-ups to run X36?

## Design

- **Arms,** in one session, on the same model servers and the same code:
  - `live`: version 4, served with `LIMESPEC_INDEX_VERSION=4`;
  - `candidate`: version 11, served with `LIMESPEC_INDEX_VERSION=11`.
- **Questions:** every question of frozen90 (90), held-out v2 (60) and held-out v3 (75),
  asked through the v1 API with `python -m evaluation ask`, `live` first.
- **Paired analysis,** as in X2 and X16: where both arms show the same answer they score
  the same; differing answers are graded blind (pairs shuffled with seed 11, arms
  hidden), then unblinded; differences are summed per case and cases resampled.
- **conv-v1 coverage,** exactly as X36 registered it: an answerable follow-up (`standalone`
  false, expected status `answered`; 44 in conv-v1) is in scope when every part has an
  evidence quote found whole, whitespace and case ignored, in one passage of the version.
  Quotes from images cannot be found (no image index yet). Corrected before any run: the
  first draft of this note counted later turns and used `find_quote`, which is not the
  bar X36 set.

## Gate (fixed before the runs)

1. **No price shown:** no `candidate` answer shows a currency amount anywhere the reader
   sees it (`python -m evaluation guardrails`), across all 225 questions.
2. **Safety:** `candidate` gives the fixed safety referral to every emergency question.
3. **Status:** per set, `candidate` matches the key's expected status on at least as many
   questions as `live`, minus 3.
4. **Quality:** per set, over the graded pairs, `candidate` has at most 3 fewer sound
   answers and at most 3 more wrong ones than `live` (the grader's drift, X0).
5. **Coverage:** at least 30 answerable conv-v1 follow-ups are covered (the bar X36 was
   registered with, D77).

Reported, not gated: answers that differ, per set; coverage per conv-v1 source format;
the readings' flagged pages; seconds per answer.

A pass makes version 11 live, and X36 runs on it. A failure is diagnosed before any
change; version 4 stays live meanwhile.

## Grading

Blind, by an LLM, on the anonymised pairs; the arm mapping is read only after every
verdict is saved. The scale is v3's: **sound** answers every part correctly (or gives the
refusal or referral the key expects) and says nothing the key forbids; **partial** is
correct but misses a part; **wrong** states something incorrect or forbidden, or has the
wrong status.

## Result (29 September 2026): gate 4 fails as written

Both arms ran through the v1 API on 29 September with the generator, embedder and
reranker unchanged; 225 answers each, no errors. Evidence, registered in each set as
`sitting-s2-knowledge`: both runs, the blind pairs and order (seed 11) and the verdicts.

| Gate item | frozen90 | held-out v2 | held-out v3 | |
|---|---|---|---|---|
| 1. Prices shown (live → candidate) | 0 → 0 | 0 → 0 | 0 → 0 | pass |
| 2. Emergencies referred | 10/10 → 10/10 | 5/5 → 5/5 | 5/5 → 5/5 | pass |
| 3. Status as the key expects | 87 → 86 | 46 → 50 | 70 → 69 | pass |
| 4. Sound (candidate − live) | +3 [−5, +14] | **−7** [−19, +3] | **−4** [−14, +4] | **fail** |
| 4. Wrong (candidate − live) | +3 [0, +6] | +3 [−6, +15] | **+9** [0, +20] | **fail** |
| 5. conv-v1 follow-ups covered | | | | 5 → 31 of 44: pass |

Brackets: 95% interval over resampled cases. Answers that differ: 72 of 90, 55 of 60 and
68 of 75, so almost every answer changed and all were graded. Reported, not gated:
expected refusals refused 7/10 → 7/10, 10/10 → **5/10**, 15/15 → 15/15; median seconds
per answer 14.2 → 17.1, 12.6 → 17.5, 14.0 → 16.6 (page-sized passages are longer
prompts); the 11 follow-ups still uncovered need image text (11 quotes), gov.uk
guidance (3), one PDF table and one company page; 16 PDF pages were flagged by the
reading (X8 report, "Production reading").

## Diagnosis

Differences summed per case, candidate − live (sound, wrong); cases with no net change
are left out.

| Set | Case | Sound | Wrong | Cause |
|---|---|---|---|---|
| v2 | c10 embodied carbon of the boards | −5 | +5 | relevance |
| v2 | c06 Warmshell Internal, six parts | −2 | 0 | crowding |
| v2 | c07 three insulation roles | −2 | 0 | crowding |
| v2 | c05 samples | 0 | −2 | gain: the sample page's delivery and refund text |
| v2 | c02, c03 | +1 each | 0 | |
| v3 | k01 finish over Forte | −4 | +4 | key scope |
| v3 | k15 sustainability, three parts | 0 | +4 | crowding |
| v3 | k03 Fibrelime, five parts | −2 | 0 | crowding |
| v3 | k09 ordering | 0 | +1 | a refusal (v3q071) |
| v3 | k07 Silic8 accessories | +2 | 0 | |
| frozen90 | mortar bags, laths, Duro | +7 | 0 | gain: data-sheet consumption rates and build-ups |
| frozen90 | five cases | −4 | +3 | one answer each |

Three causes:

1. **Key scope (k01, 4 answers).** Held-out v3's k01 forbids naming a finish other than
   Tradirend over Forte, written from the product page. Lime Green's own Forte data sheet
   lists "Lime Green Tradirend, Natural Finish or Finish WP" and Silicate Render as
   finishes, and the candidate quoted it. By the corpus the candidate indexes, those
   answers are right. Frozen90 is declared `curated_html_only`, and held-out v2's absence
   checks cover the 162 HTML pages; neither key saw the PDFs. Without k01, held-out v3
   still has 5 more wrong answers (k15 +4, k09 +1), so the gate fails on v3 regardless.
2. **Relevance (c10, 5 answers).** Asked for the woodfibre boards' embodied carbon in
   kg CO₂e/m², the candidate answered each time with the Warmshell brochure's "The
   Warmshell complete system stores 28 kg of CO₂ per m²". The quote is verbatim and
   true, but it is carbon stored by the system, not the boards' embodied carbon. No PDF in
   the corpus gives that figure either (the only per-unit GWP is Solo's EPD, per kg), so
   the key's refusal still holds. Verification checks that each claim is in its passage;
   nothing checks that the claims answer what was asked. Version 4 did not hold the
   brochure, so it refused. This is a real error, and it caused the drop in held-out v2's
   expected refusals (10/10 → 5/10).
3. **Crowding (k15, c06, c07, k03).** Version 11 holds six times as many passages (1,845
   against 315), and several documents now cover the same subject. The reranked top 8
   fills with them, and multi-part answers lose the page that holds a part. On k15 the new
   news posts (Lime Green turns 21, the Ecomerchant interview, Creating healthy homes)
   take most of the slots from *About Lime Green* and *Why lime*, and 4 answers lose the
   plant or lime's benefits, which the key forbids omitting. On c06 and c07 the Warmshell brochure,
   design guide and classification report stand in for the Warmshell Internal and
   Aerogel pages. On k03 the Fibrelime data sheet displaces part of the product page.

Gains from the same corpus: data-sheet consumption rates and build-ups (frozen90 +7
sound), the sample page's delivery and refund terms (v2 c05), and follow-ups covered for
X36 (5 → 31).

**Consequence:** version 4 stays live and X36 waits. Causes 2 and 3 are general: they
will recur on any question where a related number or a same-subject document is
retrievable. They need fixes to the mechanism, found by research and gated before a
new run. The fixes will be derived from these three sets, so they must also be checked on
questions they were not derived from. That means a new held-out key written against the
whole corpus, which also resolves cause 1.
