# 0035. Follow-ups: the first request rewrites them with the last 4 turns

- Status: Accepted. The registered gate decided it.
- Date: 2026-10-02
- Origin: X36 (`evaluation/reports/X36-follow-ups.md`, amended before the run)

## Context

- **The assistant answers one question at a time.** In a conversation, follow-ups such
  as "how much water does it need?" name nothing to search for.
- **The design (PLAN §0e) keeps every turn a single-turn answer.** Only the first
  request reads the recent turns. It rewrites the message into standalone search
  questions and judges an emergency with the conversation in view. Search, the answer
  request and verification are unchanged. With no history the request is
  byte-identical, so the prompt hash stays `c420fcf4`.
- **X36 tested it on `conv-v1`:** 20 conversations, 86 turns, with ten multi-turn
  situations. The gates were fixed before the run (`126d013`). There were three arms on
  today's system: `a` (no history), `b4` (the last 4 turns with reference replies, gated)
  and `b4-live` (the last 4 turns as the run showed them, reported). One grader graded
  every distinct answer blind.

## Decision

- **Follow-ups are switched on with `b4`.** All three gates pass:
  - Safety: 4/4 emergency turns referred, and no injected instruction followed.
  - Follow-ups: 48 sound against 30 of the 60 in-scope follow-ups, a difference of
    +0.300 [+0.150, +0.464] with conversations resampled, and 11 fewer wrong answers
    (4 against 15).
  - Nothing else changes: all 20 first turns show the same answer.
- **History is what the user saw.** Each earlier turn is the customer's message and the
  answer as shown (`view.reply_text`: verified claims, then any notice). It is never
  removed claims, and never text from a client (D60).
- **The window is the last 4 turns.** Live history (`b4-live`) is within noise of
  reference history: −0.050 [−0.121, +0.017].

## Measured

| Arm | Later turns (62): sound / partial / missing / wrong | First turns (20): sound / wrong |
|---|---|---|
| `a` | 31 / 2 / 14 / 15 | 18 / 0 |
| `b4` | 49 / 1 / 8 / 4 | 18 / 0 |
| `b4-live` | 46 / 2 / 9 / 5 | 18 / 0 |

- **Without history, follow-ups fail by substitution.** 13 of `a`'s 15 wrong answers
  give other products' figures for a product the message only implies. 11 of those are
  not wrong under `b4`.
- **`b4`'s 4 wrong turns are all wrong in `a` too:**
  - a flattened data-sheet table ("91"): a reading defect;
  - two substitutions;
  - a related true claim where a refusal was expected.
- **7 of `b4`'s 9 gaps are picture parts.** These are the accepted limit of ADR 0033 and
  ADR 0034.

## Consequences

- **The conversation state is built next** (PLAN §0e, Phase 2):
  - a `conversations` table;
  - `answers` gains the conversation and turn;
  - the API takes an optional `conversation_id`;
  - history rebuilt from `answers.shown`.

  Until then, each API message starts a new conversation.
- **The remaining wrong turns are not conversation faults.** They are the single-question
  mechanisms already recorded (reading, substitution, refusal discipline). Reading is
  frozen until after deployment. The Natural Lime Mortar Strong data sheet's strength
  table joins the deferred reading list.
- **Live history can raise a false emergency.** c15t5, bypassing a robot's guard switch
  after a conversation about the robot, got the safety referral. No instructions were
  given. Over-referral is the safe direction. `conv-v1`'s escalation turns measure it on
  later runs.
