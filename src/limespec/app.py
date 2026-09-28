"""The web page and the JSON API: the same answer as the command line, over HTTP.

Every route shows `view(answer)`, the same data the CLI prints. The page calls
`assistant.ask`; the v1 API returns the same answer with the id of its audit
record. An unreachable model or a missing index is an operational error: a clear
message with HTTP 503, never an answer.
"""

import contextvars
import logging
import queue
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, TypedDict

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, StringConstraints

from limespec import assistant, config, llm, telemetry
from limespec.ingest import IngestError
from limespec.llm import ModelServerError
from limespec.view import AnswerView, view

app = FastAPI(title="Lime Green Assistant")
telemetry.instrument(app)
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


class AnswerRequest(BaseModel):
    """A question for the v1 API, checked after surrounding spaces are removed."""

    question: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=config.MAX_QUESTION_CHARS
        ),
    ]


class RecordedAnswer(TypedDict):
    id: int  # the answer's audit record
    answer: AnswerView


class Readiness(TypedDict):
    ready: bool
    checks: dict[str, bool]


@app.get("/", response_class=HTMLResponse)
def page(request: Request, q: str = "") -> HTMLResponse:
    """The question form, with the answer below it once a question is asked."""
    question = q.strip()
    answer: AnswerView | None = None
    error = ""
    if question:
        try:
            answer = view(assistant.ask(question))
        except (IngestError, ModelServerError) as problem:
            error = str(problem)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"question": question, "answer": answer, "error": error},
        status_code=503 if error else 200,
    )


@app.post("/api/v1/answers")
def create_answer(request: AnswerRequest) -> RecordedAnswer:
    """Answer from the live Postgres index and record it for audit."""
    try:
        result, answer_id = assistant.ask_and_record(request.question)
    except (IngestError, ModelServerError) as problem:
        logger.warning("answer failed: %s", problem)
        raise HTTPException(status_code=503, detail=str(problem)) from problem
    return {"id": answer_id, "answer": view(result)}


@app.post("/api/v1/answers/stream", response_class=EventSourceResponse)
def stream_answer(request: AnswerRequest) -> Iterator[ServerSentEvent]:
    """The same answer as server-sent events: `stage` as each stage starts, then
    `answer` once it is verified, or `error`. Unverified text is never sent."""
    events: queue.Queue[ServerSentEvent | Exception] = queue.Queue()

    def report(stage: str) -> None:
        events.put(ServerSentEvent(event="stage", data={"stage": stage}))

    def run() -> None:
        try:
            result, answer_id = assistant.ask_and_record(request.question, report)
        except (IngestError, ModelServerError) as problem:
            logger.warning("answer failed: %s", problem)
            events.put(ServerSentEvent(event="error", data={"detail": str(problem)}))
        except Exception as error:  # a bug: raised below, where the server logs it
            events.put(error)
        else:
            recorded: RecordedAnswer = {"id": answer_id, "answer": view(result)}
            events.put(ServerSentEvent(event="answer", data=recorded))

    # The answer runs in its own thread so each stage is sent as it starts. A new
    # thread starts with an empty context, so the request's is copied in: its spans
    # then belong to the request's trace.
    context = contextvars.copy_context()
    threading.Thread(target=context.run, args=(run,), daemon=True).start()
    while True:
        event = events.get()
        if isinstance(event, Exception):
            raise event
        yield event
        if event.event != "stage":
            return


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process answers HTTP. It checks nothing else, so a slow model
    or database never gets a working process restarted."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response) -> Readiness:
    """Readiness: whether an answer can be served now. HTTP 503 until the database
    has a matching live index and every model server has loaded its model."""
    checks = {
        "database": assistant.database_ready(),
        "embedding": llm.healthy(config.EMBEDDING_URL),
        "reranking": llm.healthy(config.RERANK_URL),
        "generation": llm.healthy(config.CHAT_URL),
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = 503
    return {"ready": ready, "checks": checks}
