import { askStream, ENDED, UNAVAILABLE, type StreamEvent } from "./api";
import { recorded } from "./fixtures";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
}

function respond(body: BodyInit | null, status = 200): typeof fetch {
  return vi.fn(async () => new Response(body, { status }));
}

async function events(fetchImpl: typeof fetch, id: string | null = null) {
  const heard: StreamEvent[] = [];
  await askStream("What is Duro?", id, (event) => heard.push(event), fetchImpl);
  return heard;
}

const ANSWER = recorded();
const STREAM =
  'event: stage\ndata: {"stage":"understanding"}\n\n' +
  `event: answer\ndata: ${JSON.stringify(ANSWER)}\n\n`;

test("a first question sends only the question and hears each stage, then the answer", async () => {
  const fetchImpl = respond(streamOf(STREAM));

  expect(await events(fetchImpl)).toEqual([
    { kind: "stage", stage: "understanding" },
    { kind: "answer", recorded: ANSWER },
  ]);
  const [url, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/v1/answers/stream");
  expect(JSON.parse(init.body as string)).toEqual({ question: "What is Duro?" });
});

test("a follow-up sends the conversation id and nothing else", async () => {
  const fetchImpl = respond(streamOf(STREAM));

  await events(fetchImpl, "c-1");

  const [, init] = vi.mocked(fetchImpl).mock.calls[0] as [string, RequestInit];
  expect(JSON.parse(init.body as string)).toEqual({
    question: "What is Duro?",
    conversation_id: "c-1",
  });
});

test("an ended conversation is its own outcome", async () => {
  expect(await events(respond('{"detail": "ended"}', 404))).toEqual([
    { kind: "ended", detail: ENDED },
  ]);
});

test("every failure shows the fixed message, never the server's detail", async () => {
  const unreachable: typeof fetch = vi.fn(async () => {
    throw new TypeError("Failed to fetch");
  });
  const broken = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.error(new Error("connection reset"));
    },
  });
  const failures: (typeof fetch)[] = [
    respond('{"detail": "internal address"}', 503),
    respond(null),
    unreachable,
    respond(streamOf('event: error\ndata: {"detail": "x"}\n\n')),
    // An event the client does not know is ignored; the stream then ends unanswered.
    respond(
      streamOf(
        'event: stage\ndata: {"stage":"searching"}\n\n',
        "event: ping\ndata: {}\n\n",
      ),
    ),
    respond(broken),
  ];

  for (const fetchImpl of failures) {
    expect((await events(fetchImpl)).at(-1)).toEqual({
      kind: "error",
      detail: UNAVAILABLE,
    });
  }
});
