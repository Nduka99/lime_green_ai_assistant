import { Answer } from "./Answer";
import { STAGES, type RecordedAnswer, type Stage } from "./api";
import { CheckIcon } from "./Icons";

/** How one question ended: a verified answer, the fixed error, or an ended
 * conversation. Absent while the answer is on its way. */
export type Outcome =
  | { kind: "answer"; recorded: RecordedAnswer }
  | { kind: "error"; detail: string }
  | { kind: "ended"; detail: string };

export interface TurnState {
  key: number;
  question: string;
  stages: Stage[]; // the stages started so far, in order
  outcome?: Outcome;
}

const STAGE_LABELS: Record<Stage, string> = {
  understanding: "Understanding",
  searching: "Searching",
  answering: "Answering",
  checking: "Checking quotes",
};

const STAGE_STATUS: Record<Stage, string> = {
  understanding: "Reading the question…",
  searching: "Searching Lime Green's pages and documents…",
  answering: "Writing an answer from the passages found…",
  checking: "Checking every quote against its source…",
};

export function Turn({
  turn,
  onNewConversation,
}: {
  turn: TurnState;
  onNewConversation: () => void;
}) {
  return (
    <article className="turn" aria-label={`Question: ${turn.question}`}>
      <p className="question">{turn.question}</p>
      {turn.outcome === undefined ? (
        <Progress stages={turn.stages} />
      ) : turn.outcome.kind === "answer" ? (
        <Answer recorded={turn.outcome.recorded} />
      ) : turn.outcome.kind === "error" ? (
        <div className="problem" role="alert">
          <p className="problem-title">The assistant is unavailable.</p>
          <p>{turn.outcome.detail}</p>
        </div>
      ) : (
        <div className="problem" role="alert">
          <p className="problem-title">{turn.outcome.detail}</p>
          <button type="button" className="button" onClick={onNewConversation}>
            Start a new conversation
          </button>
        </div>
      )}
    </article>
  );
}

/** The four stages, each marked done once the next has started; the current one
 * is announced to screen readers. */
function Progress({ stages }: { stages: Stage[] }) {
  const current = stages.at(-1);
  return (
    <div className="progress">
      <ol className="stages">
        {STAGES.map((stage) => {
          const reached = stages.includes(stage);
          const state = !reached ? "waiting" : stage === current ? "current" : "done";
          return (
            <li key={stage} className={`stage stage-${state}`}>
              <span className="stage-mark" aria-hidden="true">
                {state === "done" && <CheckIcon />}
              </span>
              {STAGE_LABELS[stage]}
            </li>
          );
        })}
      </ol>
      <p className="stage-status" role="status">
        {current ? STAGE_STATUS[current] : "Sending the question…"}
      </p>
    </div>
  );
}
