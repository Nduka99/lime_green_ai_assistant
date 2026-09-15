"""The web page and a JSON endpoint: the same answer as the command line, over HTTP.

Both routes call `assistant.ask` and show `view(answer)`, the same data the CLI
prints. An unreachable model or a missing index is an operational error: a
clear message with HTTP 503, never an answer.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from limespec import assistant
from limespec.ingest import IngestError
from limespec.llm import ModelServerError
from limespec.view import AnswerView, view

app = FastAPI(title="Lime Green Assistant")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


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


@app.get("/api/answer")
def api_answer(q: str) -> AnswerView:
    """The same answer as JSON."""
    question = q.strip()
    if not question:
        raise HTTPException(status_code=400, detail="ask a question with ?q=")
    try:
        return view(assistant.ask(question))
    except (IngestError, ModelServerError) as problem:
        raise HTTPException(status_code=503, detail=str(problem)) from problem
