import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

// The API is answered here: each test says what the stream returns, and the
// requests the page sent are kept for checking.

const SOURCE = {
  number: 1,
  title: "Duro Lime Plaster Base Coat",
  heading: "Preparation",
  quote: "Duro may be re-tempered for up to 4 hours after being mixed.",
  link: "https://www.lime-green.co.uk/duro#:~:text=Duro%20may%20be%20re-tempered",
  url: "https://www.lime-green.co.uk/duro",
  captured: "2026-09-12",
};

function recorded(turn: number, change: Record<string, unknown> = {}) {
  return {
    id: 100 + turn,
    conversation_id: "6c1f0a52-0b7e-4c1d-9f3a-2d8b7e5a4c10",
    turn,
    understood_as: ["How long can Duro be re-tempered after mixing?"],
    answer: {
      question: "q",
      status: "answered",
      notice: "",
      claims: [
        {
          text: "Duro can be re-tempered for up to 4 hours after mixing.",
          sources: [1],
        },
      ],
      sources: [SOURCE],
      closest_pages: [],
      ...change,
    },
  };
}

function stream(answer: unknown): string {
  const stages = ["understanding", "searching", "answering", "checking"]
    .map((stage) => `event: stage\ndata: {"stage": "${stage}"}\n\n`)
    .join("");
  return `${stages}event: answer\ndata: ${JSON.stringify(answer)}\n\n`;
}

async function answerWith(page: Page, replies: ((route: Route) => Promise<void>)[]) {
  const sent: Record<string, unknown>[] = [];
  await page.route("**/api/v1/answers/stream", async (route) => {
    sent.push(route.request().postDataJSON() as Record<string, unknown>);
    const reply = replies[sent.length - 1] as (route: Route) => Promise<void>;
    await reply(route);
  });
  return sent;
}

function sse(answer: unknown) {
  return (route: Route) =>
    route.fulfill({ contentType: "text/event-stream", body: stream(answer) });
}

async function ask(page: Page, question: string) {
  await page.getByLabel("Your question").fill(question);
  await page.getByLabel("Your question").press("Enter");
}

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations).toEqual([]);
}

for (const colorScheme of ["light", "dark"] as const) {
  test(`a three-turn conversation, accessible in ${colorScheme}`, async ({
    page,
  }, info) => {
    await page.emulateMedia({ colorScheme });
    const sent = await answerWith(page, [
      sse(recorded(1)),
      sse(
        recorded(2, {
          claims: [{ text: "Duro is re-tempered for up to 4 hours.", sources: [1] }],
        }),
      ),
      sse(
        recorded(3, {
          status: "safety_referral",
          notice:
            "This may be an emergency.\nIf a person was exposed, NHS advice:\n- In the eye: go to A&E or call 999.\n- Swallowed or breathed in: call 999 or go to A&E.",
          claims: [],
          sources: [],
        }),
      ),
    ]);
    await page.goto("/");
    await expectAccessible(page);
    await page.screenshot({
      path: info.outputPath(`empty-${colorScheme}.png`),
      fullPage: true,
    });

    await ask(page, "How long can I re-temper Duro?");
    await expect(page.getByRole("link", { name: "Source 1" })).toBeVisible();
    await ask(page, "and after that?");
    await expect(page.getByText("Understood as")).toBeVisible();
    await ask(page, "it splashed in my eye, help");
    await expect(page.getByRole("region", { name: "Safety referral" })).toBeVisible();

    expect(sent.map((body) => body.conversation_id ?? null)).toEqual([
      null,
      "6c1f0a52-0b7e-4c1d-9f3a-2d8b7e5a4c10",
      "6c1f0a52-0b7e-4c1d-9f3a-2d8b7e5a4c10",
    ]);
    await expectAccessible(page);
    await page.screenshot({
      path: info.outputPath(`thread-${colorScheme}.png`),
      fullPage: true,
    });
  });
}

test("an ended conversation starts again, and a failure shows the fixed message", async ({
  page,
}) => {
  await answerWith(page, [
    (route) => route.fulfill({ status: 503, body: '{"detail": "x"}' }),
    sse(recorded(1)),
    (route) => route.fulfill({ status: 404, body: '{"detail": "ended"}' }),
  ]);
  await page.goto("/");

  await ask(page, "What is Duro?");
  await expect(page.getByRole("alert")).toContainText("The assistant is unavailable.");
  await ask(page, "What is Duro?");
  await expect(page.getByRole("link", { name: "Source 1" })).toBeVisible();
  await ask(page, "And Solo?");
  await page.getByRole("button", { name: "Start a new conversation" }).click();

  await expect(
    page.getByRole("heading", { name: "Ask a question to start" }),
  ).toBeVisible();
});

test("at phone width the thread fits without sideways scrolling", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await answerWith(page, [sse(recorded(1))]);
  await page.goto("/");
  await ask(page, "How long can I re-temper Duro?");
  await expect(page.getByRole("link", { name: "Source 1" })).toBeVisible();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({ path: info.outputPath("phone.png"), fullPage: true });
});
