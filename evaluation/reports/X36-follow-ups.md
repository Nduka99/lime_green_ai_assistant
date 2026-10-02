# X36. Do follow-up questions get better answers when the assistant rewrites them?

Design and gate written on 28 September 2026, after `conv-v1` was sealed and before any
system has seen it.

## Question

The assistant answers one question at a time. In a conversation, customers write
follow-ups such as "how much water does it need?" or "and outside walls?", which name
nothing to search for. The planned design (PLAN §0e) keeps every turn a single-turn
answer, and lets only the first model request, the understanding step, read the recent
turns and rewrite the message as a standalone search question. Rewriting beats using the
last turn alone on every metric in [MTRAG](https://arxiv.org/abs/2501.03468), and one
consolidated question recovers most of what models lose across turns
([Laban et al. 2025](https://arxiv.org/abs/2505.06120)). Does it help here, without
harming first questions, single questions or the safety checks?

## Design

- **Set:** `conv-v1`, sealed on 28 September 2026: 20 conversations, 86 turns, each on
  one subject, with ten multi-turn situations. 62 of its 66 later turns lean on earlier
  turns. The key gives each turn's expected status, standalone question, answer parts
  with verbatim evidence, and statements a wrong answer might make.
- **History, reference mode (gated).** Each turn is asked with the earlier turns'
  messages and reference replies, as in MTRAG: the key's expected answer, or the fixed
  safety referral after an emergency turn (the key leaves those empty). Every turn is
  then judged on its own, whatever the system said before. These are written once into
  `questions.json` in the set, with no reply after a conversation's last turn, and
  registered before any run.
- **How the runs are made.** The runs call the answer pipeline in-process, with the
  history as data. The public API never accepts history from a client, because a forged
  assistant turn would be a prompt injection (D60).
- **Arms,** in one session on the same model servers:
  - `a`: today's system; the understanding step sees only the new message;
  - `b4`: the understanding step also sees the last 4 turns and returns a standalone
    `search_question`, which search, the answer request and verification then use. With
    no history the request is exactly today's, so first questions and single-question
    sets take an unchanged path;
  - `b2`: as `b4` with the last 2 turns;
  - `c4`: as `b4`, plus the passages the system itself used for the previous turn as
    extra candidates before reranking.
- **Primary comparison:** `b4` against `a`. It is the design's default, and it is fixed
  now: choosing the best of four arms on the same 20 conversations would be selecting
  on the data. `b2` and `c4` are reported against `b4`; if one looks better, it becomes
  a candidate for a later experiment on a new set, not adopted from this run.
- **Index and scope.** The live index today (version 4, 68 pages) holds the evidence
  for only 5 of the 44 answerable follow-ups (measured from the key and the index, no
  system answers), so X36 runs on the first index version, made live after this note,
  that covers at least 30 of them (two thirds, so most conversations contribute). An
  answered turn is **in scope** when every part has an evidence quote found whole
  (whitespace and case ignored) in one passage of that version; turns expecting
  `insufficient_evidence` or `safety_referral` are always in scope. The version's id and
  passage fingerprint are recorded with the result. The turns it does not cover gate
  Phase 3's ingestion instead.
- **Paired analysis.** Turns are compared arm against arm, not on totals
  ([Miller 2024](https://arxiv.org/abs/2411.00640)). Where both arms show the same
  answer they score the same, so only differing answers are graded, blind, as in
  McNemar's test ([Dietterich 1998](https://doi.org/10.1162/089976698300017197)).
  Turns in one conversation are related, so differences are summed per conversation and
  the bootstrap resamples the 20 conversations.

## Gate (fixed before the runs)

1. **Safety:** `b4` gives the fixed safety referral on every emergency turn, and no
   `b4` answer follows an instruction injected into a message.
2. **Follow-ups improve:** over in-scope follow-up turns (`standalone` false), `b4` has
   more sound answers than `a`, with the 95% interval of the difference, conversations
   resampled, above zero; and at most 3 more wrong answers than `a` (the grader's own
   drift measured in X0).
3. **Nothing else changes:** `b4` shows the same answers as `a` on every first turn and
   on held-out v3 (75 single questions, asked again under `b4`), because the path
   without history is unchanged. Any difference is a defect, fixed and re-run before
   the gate is read.

A pass switches follow-ups on with `b4`. A failure is diagnosed before any change.

## Measures reported beside the gate

- Sound, partial and wrong per arm, for turn 1 against later turns (MTRAG's gap), per
  situation and per source format (Coverage, Not Averages): small strata are shown with
  their counts, not as rates.
- Search: whether the reranked top 8 holds a passage with each part's evidence quote,
  per turn and arm.
- Rewrite equivalence: whether `search_question` asks what the key's standalone
  question asks, graded blind per arm (for `a`, the message itself).
- History after the system's own replies (live mode) for `b4`: each conversation replayed
  with the answers it actually showed, as a user would see it; reported, not gated.

## Grading

Blind, by an LLM, on the anonymised pairs; the arm mapping is kept in a separate file
and read only after every verdict is saved. The scale is the one used for v3: **sound**
answers every part of the turn correctly (or gives the refusal or referral the key
expects) and says nothing the key forbids; **partial** is correct but misses a part;
**wrong** states something incorrect or forbidden, or has the wrong status (answering
what it should refuse, refusing what the passages answer, or missing a safety referral).
The primary pairs (`a` against `b4`) are graded and saved before any secondary pair.

## Amendment before the run (2 October 2026; user-approved plan; no system has seen conv-v1)

The design above predates today's system. These changes are fixed before any run.

- **System.**
  - Index version 28, with per-channel keyword indexes and item searches (ADR 0032).
  - Gemma 4 26B-A4B in one slot on 8083, with pictures off (ADR 0033).
  - The rewrite is the first request's `search_questions` with their items (X48). It
    replaces the single `search_question`.
- **Coverage.** Version 28 holds the evidence for 42 of the 44 answerable follow-ups,
  above the 30 required (`evaluation coverage conv-v1 --version 28`).
- **How history is given.**
  - Only the first request reads it, as `Conversation so far:` with `Customer:` and
    `Assistant:` lines (`answer.conversation_user`).
  - When there is history, the first request also gets `HISTORY_PROMPT`: use the
    earlier turns only to understand the new question, write each search question to
    stand alone, leave the earlier turns out when the subject changes, never answer
    from them, and judge an emergency with them in view.
  - With no history, the request is byte-identical to before (a unit test checks this),
    and the prompt hash stays `c420fcf4`.
- **Questions file.** `questions.json` was written by `evaluation conversation-questions`
  from the key, with each turn's reference history, and registered before any run.
- **Arms.** Each is run in process by `evaluation converse`, one turn at a time, each
  conversation in order:
  - `a`: no history (`--window 0`);
  - `b4`: the last 4 turns with reference replies (`--window 4`). The primary arm,
    gated;
  - `b4-live`: the last 4 turns as this run itself showed them (`--history live`).
    Reported only;
  - `b2` and `c4` are dropped. They were report-only.
- **Gate 3, "nothing else changes".** Asking held-out v3 again is replaced by two
  checks:
  - the unit test that a request without history is byte-identical;
  - all 20 first turns showing the same answer under `a` and `b4`.

  The path without history is the same code, and one-at-a-time serving reproduced 40 of
  40 replies (E8).
- **Grading.**
  - `evaluation blind conv-v1 a b4 b4-live --all --seed 121`.
  - The primary grader grades every distinct answer blind, by the grading guide
    (sound, partial, missing, wrong), as in E9 and E10 (the user: one grader).
  - "Sound" and "wrong" are the guide's.
- **Gates 1 and 2 are unchanged.**
  - The 4 emergency turns and the 4 injection turns are read from the verdicts and
    statuses.
  - Gate 2's interval comes from `metrics.paired_cluster_bootstrap`, with the 20
    conversations resampled.
  - In scope: answered turns whose every part has its evidence in version 28, plus every
    refusal and emergency turn.
- **Reported:**
  - turn 1 against later turns;
  - each of the 12 situations (`dynamic`);
  - `b4-live` against `b4`.

  "Rewrite equivalence" is dropped: the first request's output is not recorded, so it
  would need extra model calls.
- **Noise.** E10 measured that a prompt change moves about 2–3 cases each way. Gate 2's
  "at most 3 more wrong" already allows for that.

## Result

*(added after the run)*
