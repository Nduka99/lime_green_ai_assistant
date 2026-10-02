import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { StreamEvent } from "./api";
import { App } from "./App";
import { MAX_QUESTION_CHARS } from "./Composer";
import { recorded } from "./fixtures";

interface Asked {
  question: string;
  conversationId: string | null;
  send: (event: StreamEvent) => void;
  finish: () => void;
}

/** A stand-in for the stream: each question waits until the test sends its
 * events and finishes it. */
function fakeAsk() {
  const asked: Asked[] = [];
  const ask = (
    question: string,
    conversationId: string | null,
    onEvent: (event: StreamEvent) => void,
  ) =>
    new Promise<void>((finish) => {
      asked.push({ question, conversationId, send: onEvent, finish });
    });
  return { ask, asked };
}

async function askAndAnswer(
  user: ReturnType<typeof userEvent.setup>,
  asked: Asked[],
  question: string,
  outcome: StreamEvent,
) {
  await user.type(screen.getByLabelText("Your question"), `${question}{Enter}`);
  const latest = asked.at(-1) as Asked;
  latest.send(outcome);
  latest.finish();
  await screen.findByRole("button", { name: "Ask" });
}

test("the empty thread teaches the input and its examples ask themselves", async () => {
  const user = userEvent.setup();
  const { ask, asked } = fakeAsk();
  render(<App ask={ask} />);

  expect(
    screen.getByRole("heading", { name: "Ask a question to start" }),
  ).toBeVisible();
  await user.click(screen.getByRole("button", { name: "What is Grippa used for?" }));

  expect(asked[0]).toMatchObject({
    question: "What is Grippa used for?",
    conversationId: null,
  });
  expect(
    screen.getByText("What is Grippa used for?", { selector: ".question" }),
  ).toBeVisible();
});

test("each stage is shown as it starts, then the verified answer with its sources", async () => {
  const user = userEvent.setup();
  const { ask, asked } = fakeAsk();
  render(<App ask={ask} />);

  await user.type(screen.getByLabelText("Your question"), "What is Duro?{Enter}");
  expect(screen.getByRole("status")).toHaveTextContent("Sending the question");
  asked[0]?.send({ kind: "stage", stage: "understanding" });
  asked[0]?.send({ kind: "stage", stage: "searching" });
  expect(await screen.findByRole("status")).toHaveTextContent("Searching Lime Green");
  expect(screen.getByRole("button", { name: /Answering/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: "New conversation" })).toBeDisabled();

  asked[0]?.send({ kind: "answer", recorded: recorded() });
  asked[0]?.finish();

  const ref = await screen.findByRole("link", { name: "Source 1" });
  expect(ref).toHaveAttribute("href", "#t1-s1");
  const sources = screen.getByRole("region", { name: "Sources" });
  expect(
    within(sources).getByRole("link", { name: "Duro Lime Plaster Base Coat" }),
  ).toHaveAttribute("href", "https://www.lime-green.co.uk/duro");
  expect(
    within(sources).getByRole("link", { name: "Open at this quote" }),
  ).toHaveAttribute("target", "_blank");
  expect(screen.getByText("Answer", { selector: ".status" })).toBeVisible();
  // "Understood as" is for follow-ups only.
  expect(screen.queryByText("Understood as")).toBeNull();
});

test("a follow-up continues the conversation and shows what it was understood as", async () => {
  const user = userEvent.setup();
  const { ask, asked } = fakeAsk();
  render(<App ask={ask} />);

  await askAndAnswer(user, asked, "What is Duro?", {
    kind: "answer",
    recorded: recorded(),
  });
  const second = recorded(
    { turn: 2, understood_as: ["How thick is Duro applied?"] },
    { claims: [{ text: "Duro goes on 9 to 12 mm thick.", sources: [1] }] },
  );
  await askAndAnswer(user, asked, "How thick?", { kind: "answer", recorded: second });

  expect(asked[1]?.conversationId).toBe("c-1");
  expect(screen.getByText("How thick is Duro applied?")).toBeVisible();
  // Each turn's references point to its own sources.
  const refs = screen.getAllByRole("link", { name: "Source 1" });
  expect(refs.map((ref) => ref.getAttribute("href"))).toEqual(["#t1-s1", "#t2-s1"]);
});

test("an emergency shows the fixed referral, set apart, with its steps as a list", async () => {
  const user = userEvent.setup();
  const { ask, asked } = fakeAsk();
  render(<App ask={ask} />);
  const referral = recorded(
    { understood_as: [] },
    {
      status: "safety_referral",
      notice:
        "This may be an emergency.\n- In the eye: go to A&E.\n- Swallowed: call 999.",
      claims: [],
      sources: [],
    },
  );

  await askAndAnswer(user, asked, "It splashed in my eye", {
    kind: "answer",
    recorded: referral,
  });

  const safety = screen.getByRole("region", { name: "Safety referral" });
  expect(
    within(safety)
      .getAllByRole("listitem")
      .map((item) => item.textContent),
  ).toEqual(["In the eye: go to A&E.", "Swallowed: call 999."]);
});

test("a refusal lists the closest pages, and unknown hosts are not links", async () => {
  const user = userEvent.setup();
  const { ask, asked } = fakeAsk();
  render(<App ask={ask} />);
  const refusal = recorded(
    {},
    {
      status: "insufficient_evidence",
      notice: "I could not find enough support.",
      claims: [],
      sources: [],
      closest_pages: [
        { title: "Duro", url: "https://www.lime-green.co.uk/duro" },
        { title: "Elsewhere", url: "https://example.com/page" },
      ],
    },
  );

  await askAndAnswer(user, asked, "Delivery to Leeds?", {
    kind: "answer",
    recorded: refusal,
  });

  const closest = screen.getByRole("region", { name: "Closest pages" });
  expect(within(closest).getByRole("link", { name: "Duro" })).toBeVisible();
  expect(within(closest).queryByRole("link", { name: "Elsewhere" })).toBeNull();
  expect(within(closest).getByText("Elsewhere")).toBeVisible();
  expect(screen.getByText("Not enough information")).toBeVisible();
});

test("a source off the allowed hosts shows its title and quote without links", async () => {
  const user = userEvent.setup();
  const { ask, asked } = fakeAsk();
  render(<App ask={ask} />);
  const outside = recorded(
    {},
    {
      sources: [
        {
          number: 1,
          title: "Somewhere",
          heading: "",
          quote: "Duro is a lime base coat.",
          link: "https://example.com/a",
          url: "https://example.com/a",
          captured: "2026-09-12",
        },
      ],
    },
  );

  await askAndAnswer(user, asked, "What is Duro?", {
    kind: "answer",
    recorded: outside,
  });

  const sources = screen.getByRole("region", { name: "Sources" });
  expect(within(sources).queryByRole("link")).toBeNull();
  expect(within(sources).getByText("Somewhere")).toBeVisible();
});

test("a failure shows the fixed message and the next question can be asked", async () => {
  const user = userEvent.setup();
  const { ask, asked } = fakeAsk();
  render(<App ask={ask} />);

  await askAndAnswer(user, asked, "What is Duro?", {
    kind: "error",
    detail: "Try later.",
  });

  expect(screen.getByRole("alert")).toHaveTextContent("The assistant is unavailable.");
  expect(screen.getByRole("alert")).toHaveTextContent("Try later.");
});

test("an ended conversation offers a new one, which clears the thread", async () => {
  const user = userEvent.setup();
  const { ask, asked } = fakeAsk();
  render(<App ask={ask} />);

  await askAndAnswer(user, asked, "What is Duro?", {
    kind: "answer",
    recorded: recorded(),
  });
  await askAndAnswer(user, asked, "And Solo?", {
    kind: "ended",
    detail: "It has ended.",
  });
  await user.click(screen.getByRole("button", { name: "Start a new conversation" }));

  expect(
    screen.getByRole("heading", { name: "Ask a question to start" }),
  ).toBeVisible();
  expect(screen.getByLabelText("Your question")).toHaveFocus();
  await user.type(screen.getByLabelText("Your question"), "What is Solo?{Enter}");
  expect(asked[2]?.conversationId).toBeNull();
});

test("New conversation forgets the conversation id", async () => {
  const user = userEvent.setup();
  const { ask, asked } = fakeAsk();
  render(<App ask={ask} />);

  await askAndAnswer(user, asked, "What is Duro?", {
    kind: "answer",
    recorded: recorded(),
  });
  await user.click(screen.getByRole("button", { name: "New conversation" }));
  await user.type(screen.getByLabelText("Your question"), "What is Solo?{Enter}");

  expect(asked[1]?.conversationId).toBeNull();
});

test("Shift+Enter writes a new line, blank questions are not asked, and long ones show a count", async () => {
  const user = userEvent.setup();
  const { ask, asked } = fakeAsk();
  render(<App ask={ask} />);
  const box = screen.getByLabelText("Your question");

  await user.type(box, "   {Enter}");
  await user.type(box, "First line{Shift>}{Enter}{/Shift}second line");
  expect(asked).toEqual([]);
  expect(box).toHaveValue("   First line\nsecond line");
  expect(screen.getByText(/Enter to ask/)).toBeVisible();

  await user.clear(box);
  await user.click(box);
  await user.paste("x".repeat(MAX_QUESTION_CHARS));
  expect(
    screen.getByText(`${MAX_QUESTION_CHARS} / ${MAX_QUESTION_CHARS}`),
  ).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Ask" }));
  expect(asked[0]?.question).toHaveLength(MAX_QUESTION_CHARS);
});

test("a question is shown as text, never as markup", async () => {
  const user = userEvent.setup();
  const { ask } = fakeAsk();
  const { container } = render(<App ask={ask} />);

  await user.type(
    screen.getByLabelText("Your question"),
    "<img src=x onerror=alert(1)>{Enter}",
  );

  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeVisible();
  expect(container.querySelector("img")).toBeNull();
});
