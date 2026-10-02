"""The JSON API and the web app: the same answer as the command line, over HTTP.

Every answer is `view(answer)`, the same data the CLI prints: the v1 API returns
it with the id of its audit record and its place in a conversation, and the web app
(`web/`, built into `web/dist` and served here) shows it as a thread. An unreachable
model or a missing index is an operational error: HTTP 503 with one fixed message,
never an answer. The cause is logged on the server and never sent to the client,
since it can name internal addresses (OWASP API8:2023).

A conversation (PLAN §0e, ADR 0035) is a sequence of single-turn answers. A request
without `conversation_id` starts one; the reply gives its id and the turn's number,
and the next request sends the id back. The server rebuilds the history from what it
showed; a request carrying any other field, such as a history, is refused (D60).
"""

import contextvars
import logging
import queue
import threading
from collections.abc import Iterator
from typing import Annotated, TypedDict
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from limespec import assistant, config, llm, telemetry
from limespec.assistant import ConversationEnded, Turn
from limespec.ingest import IngestError
from limespec.llm import ModelServerError
from limespec.models import Answer
from limespec.view import AnswerView, view

# No interactive docs: the schema the web app is built against is committed as
# web/openapi.json (`limespec openapi`), and an API's inventory is not served to
# every visitor (OWASP API9:2023).
app = FastAPI(
    title="Lime Green Assistant", docs_url=None, redoc_url=None, openapi_url=None
)
telemetry.instrument(app)
logger = logging.getLogger(__name__)
# Sent with every response (OWASP Secure Headers Project): the page runs only its own
# scripts and styles, cannot be framed, and sends no referrer to the sources it links.
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}
UNAVAILABLE = "The assistant cannot answer right now. Please try again later."
ENDED = "This conversation has ended. Please start a new conversation."


class AnswerRequest(BaseModel):
    """A question for the v1 API, checked after surrounding spaces are removed, and
    the conversation it continues, if any. Any other field is refused."""

    model_config = ConfigDict(extra="forbid")

    question: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=config.MAX_QUESTION_CHARS
        ),
    ]
    conversation_id: UUID | None = None


class RecordedAnswer(TypedDict):
    id: int  # the answer's audit record
    conversation_id: str
    turn: int  # 1 for the first question of a conversation
    understood_as: list[str]  # the search questions; shown on a follow-up
    answer: AnswerView


class Readiness(TypedDict):
    ready: bool
    checks: dict[str, bool]


class SecurityHeaders:
    """Adds SECURITY_HEADERS to every HTTP response. A plain ASGI middleware, so the
    answer stream passes through unbuffered and keeps its trace context."""

    def __init__(self, inner: ASGIApp) -> None:
        self.inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
            await send(message)

        await self.inner(scope, receive, send_with_headers)


app.add_middleware(SecurityHeaders)


def opened_turn(request: AnswerRequest) -> Turn:
    """The request's turn, reserved before any answer work starts, so an ended
    conversation is a plain 404 even on the stream (whose status is sent with its
    first event)."""
    asked = str(request.conversation_id) if request.conversation_id else None
    try:
        return assistant.open_turn(asked)
    except ConversationEnded as ended:
        raise HTTPException(status_code=404, detail=ENDED) from ended
    except IngestError as problem:
        logger.warning("answer failed: %s", problem)
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from problem


def recorded(result: Answer, answer_id: int, turn: Turn) -> RecordedAnswer:
    """What the v1 API returns for one answered turn."""
    return {
        "id": answer_id,
        "conversation_id": turn.conversation_id,
        "turn": turn.number,
        "understood_as": list(result.understood),
        "answer": view(result),
    }


@app.post("/api/v1/answers")
def create_answer(
    request: AnswerRequest, turn: Annotated[Turn, Depends(opened_turn)]
) -> RecordedAnswer:
    """Answer from the live Postgres index and record it for audit."""
    try:
        result, answer_id = assistant.ask_and_record(request.question, turn=turn)
    except (IngestError, ModelServerError) as problem:
        logger.warning("answer failed: %s", problem)
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from problem
    return recorded(result, answer_id, turn)


@app.post("/api/v1/answers/stream", response_class=EventSourceResponse)
def stream_answer(
    request: AnswerRequest, turn: Annotated[Turn, Depends(opened_turn)]
) -> Iterator[ServerSentEvent]:
    """The same answer as server-sent events: `stage` as each stage starts, then
    `answer` once it is verified, or `error`. Unverified text is never sent."""
    events: queue.Queue[ServerSentEvent | Exception] = queue.Queue()

    def report(stage: str) -> None:
        events.put(ServerSentEvent(event="stage", data={"stage": stage}))

    def run() -> None:
        try:
            result, answer_id = assistant.ask_and_record(
                request.question, report, turn=turn
            )
        except (IngestError, ModelServerError) as problem:
            logger.warning("answer failed: %s", problem)
            events.put(ServerSentEvent(event="error", data={"detail": UNAVAILABLE}))
        except Exception as error:  # a bug: raised below, where the server logs it
            events.put(error)
        else:
            data = recorded(result, answer_id, turn)
            events.put(ServerSentEvent(event="answer", data=data))

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


# The web app last, so every route above is matched first: `npm run build` in web/
# writes web/dist; until then its paths are 404.
web = StaticFiles(directory=config.WEB_DIST, html=True, check_dir=False)
app.mount("/", web, name="web")
