import type { components } from "./api-types";
import { createParser } from "./sse";

export type RecordedAnswer = components["schemas"]["RecordedAnswer"];
export type AnswerView = components["schemas"]["AnswerView"];
export type Source = components["schemas"]["Source"];

export const STAGES = ["understanding", "searching", "answering", "checking"] as const;
export type Stage = (typeof STAGES)[number];

/** What happens to one question: each stage as it starts, then one outcome. */
export type StreamEvent =
  | { kind: "stage"; stage: Stage }
  | { kind: "answer"; recorded: RecordedAnswer }
  | { kind: "error"; detail: string }
  | { kind: "ended"; detail: string };

// The server's fixed texts (`app.UNAVAILABLE`, `app.ENDED`), used when a reply
// carries none, such as a dropped connection.
export const UNAVAILABLE =
  "The assistant cannot answer right now. Please try again later.";
export const ENDED = "This conversation has ended. Please start a new conversation.";

/**
 * Ask one question over the v1 stream (`POST /api/v1/answers/stream`), continuing
 * `conversationId` if given. The server keeps the conversation and rebuilds its
 * history, so the request carries only the question and the id.
 */
export async function askStream(
  question: string,
  conversationId: string | null,
  onEvent: (event: StreamEvent) => void,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  let response: Response;
  try {
    response = await fetchImpl("/api/v1/answers/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(
        conversationId === null
          ? { question }
          : { question, conversation_id: conversationId },
      ),
    });
  } catch {
    onEvent({ kind: "error", detail: UNAVAILABLE });
    return;
  }
  if (response.status === 404) {
    onEvent({ kind: "ended", detail: ENDED });
    return;
  }
  if (!response.ok || response.body === null) {
    onEvent({ kind: "error", detail: UNAVAILABLE });
    return;
  }
  let finished = false;
  const parse = createParser(({ event, data }) => {
    const payload: unknown = JSON.parse(data);
    if (event === "stage") {
      onEvent({ kind: "stage", stage: (payload as { stage: Stage }).stage });
    } else if (event === "answer") {
      finished = true;
      onEvent({ kind: "answer", recorded: payload as RecordedAnswer });
    } else if (event === "error") {
      finished = true;
      onEvent({ kind: "error", detail: UNAVAILABLE });
    }
  });
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parse(value);
    }
  } catch {
    // A dropped connection: the outcome below says so.
  }
  if (!finished) onEvent({ kind: "error", detail: UNAVAILABLE });
}
