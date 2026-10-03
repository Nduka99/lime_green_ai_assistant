import { useEffect, useRef, useState } from "react";
import { askStream, type StreamEvent } from "./api";
import { Composer } from "./Composer";
import { NewIcon } from "./Icons";
import { Turn, type TurnState } from "./Turn";

const EXAMPLES = [
  "What is Grippa used for?",
  "Can Solo Onecoat Lime Plaster go on plasterboard?",
  "How should I store Natural Lime Mortar, and how long does it keep?",
];

/** One conversation. Its id lives in page memory only: reloading the page or
 * choosing "New conversation" starts again, and the server keeps the history. */
export function App({ ask = askStream }: { ask?: typeof askStream }) {
  const [turns, setTurns] = useState<TurnState[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [turns]);

  function update(key: number, change: (turn: TurnState) => TurnState) {
    setTurns((all) => all.map((turn) => (turn.key === key ? change(turn) : turn)));
  }

  async function onAsk(question: string) {
    const key = turns.length + 1;
    setTurns((all) => [...all, { key, question, stages: [] }]);
    setBusy(true);
    await ask(question, conversationId, (event: StreamEvent) => {
      if (event.kind === "stage") {
        update(key, (turn) => ({ ...turn, stages: [...turn.stages, event.stage] }));
        return;
      }
      if (event.kind === "answer") setConversationId(event.recorded.conversation_id);
      update(key, (turn) => ({ ...turn, outcome: event }));
    });
    setBusy(false);
  }

  function onNewConversation() {
    setTurns([]);
    setConversationId(null);
    inputRef.current?.focus();
  }

  return (
    <div className="shell">
      <header className="header">
        <div>
          <h1>Lime Green Assistant</h1>
          <p className="tagline">
            Answers from Lime Green's pages and documents, with the quote behind every
            statement.
          </p>
        </div>
        <button
          type="button"
          className="button"
          onClick={onNewConversation}
          disabled={busy || turns.length === 0}
        >
          <NewIcon />
          New conversation
        </button>
      </header>
      <main className="thread" aria-label="Conversation">
        {turns.length === 0 ? (
          <section className="empty">
            <h2>Ask a question to start</h2>
            <p>
              Ask about a product, how to use it, or what its data sheets say. Follow-up
              questions can refer to the earlier ones, such as "how much water does it
              need?". Every statement links to the quote it rests on; when the pages do
              not say, the assistant says so.
            </p>
            <ul className="examples" aria-label="Example questions">
              {EXAMPLES.map((example) => (
                <li key={example}>
                  <button
                    type="button"
                    className="example"
                    onClick={() => void onAsk(example)}
                  >
                    {example}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : (
          turns.map((turn) => (
            <Turn key={turn.key} turn={turn} onNewConversation={onNewConversation} />
          ))
        )}
        <div ref={endRef} />
      </main>
      <footer className="footer">
        <Composer
          busy={busy}
          onAsk={(question) => void onAsk(question)}
          inputRef={inputRef}
        />
        <p className="disclaimer">
          Not a substitute for professional building or medical advice. Prices, stock
          and delivery are not answered here.
        </p>
      </footer>
    </div>
  );
}
