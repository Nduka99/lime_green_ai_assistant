import { useState } from "react";
import { SendIcon } from "./Icons";

// The API's limit (`config.MAX_QUESTION_CHARS`); the count shows near it.
export const MAX_QUESTION_CHARS = 1000;
const SHOW_COUNT_FROM = 900;

/** The question box: Enter asks, Shift+Enter starts a new line. It stays ready
 * for typing while an answer is on its way; only asking waits. */
export function Composer({
  busy,
  onAsk,
  inputRef,
}: {
  busy: boolean;
  onAsk: (question: string) => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const [text, setText] = useState("");
  const question = text.trim();
  const canAsk = !busy && question.length > 0 && text.length <= MAX_QUESTION_CHARS;

  function ask() {
    if (!canAsk) return;
    onAsk(question);
    setText("");
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        ask();
      }}
    >
      <label className="visually-hidden" htmlFor="question">
        Your question
      </label>
      <textarea
        id="question"
        ref={inputRef}
        rows={2}
        value={text}
        placeholder="Ask about a Lime Green product, its use or its documents"
        maxLength={MAX_QUESTION_CHARS}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            ask();
          }
        }}
      />
      <div className="composer-row">
        {text.length >= SHOW_COUNT_FROM ? (
          <span className="count">
            {text.length} / {MAX_QUESTION_CHARS}
          </span>
        ) : (
          <span className="hint">Enter to ask · Shift+Enter for a new line</span>
        )}
        <button type="submit" className="button button-primary" disabled={!canAsk}>
          <SendIcon />
          {busy ? "Answering…" : "Ask"}
        </button>
      </div>
    </form>
  );
}
