// Invented answers for the tests, in the API's shapes.
import type { AnswerView, RecordedAnswer } from "./api";

export function view(change: Partial<AnswerView> = {}): AnswerView {
  return {
    question: "What is Duro?",
    status: "answered",
    notice: "",
    claims: [{ text: "Duro is a lime base coat.", sources: [1] }],
    sources: [
      {
        number: 1,
        title: "Duro Lime Plaster Base Coat",
        heading: "Overview",
        quote: "Duro is a lime base coat.",
        link: "https://www.lime-green.co.uk/duro#:~:text=Duro",
        url: "https://www.lime-green.co.uk/duro",
        captured: "2026-09-12",
      },
    ],
    closest_pages: [],
    ...change,
  };
}

export function recorded(
  change: Partial<RecordedAnswer> = {},
  answer: Partial<AnswerView> = {},
): RecordedAnswer {
  return {
    id: 7,
    conversation_id: "c-1",
    turn: 1,
    understood_as: ["What is Duro?"],
    answer: view(answer),
    ...change,
  };
}
