"""Traces: one per request, with a span for each answer stage and model call.

Spans are sent over OTLP/HTTP to OTEL_EXPORTER_OTLP_TRACES_ENDPOINT when it is set
(deploy/compose.yaml runs VictoriaTraces for this) and dropped otherwise. Every
attribute name is in this module: the OpenTelemetry GenAI conventions are still
"Development", so a renamed attribute is a one-place change. No question, passage or
answer text is recorded; that stays in the audit table, linked by the record id.

One answer's trace:

    POST /api/v1/answers          the request (FastAPI instrumentation)
      answer                      index version, status, record id, claims kept/removed
        understanding
          chat                    the emergency check: model, tokens, finish reason
        searching
          embeddings <model>
          rerank
        answering
          chat                    the answer request
"""

import os
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

import httpx
from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, SpanKind, get_current_span

from limespec import config
from limespec.models import Answer

Attributes = dict[str, str | int | float]  # the value types recorded here
PROVIDER = "llama.cpp"  # gen_ai.provider.name: every model server is llama-server
USAGE = {
    "prompt_tokens": "gen_ai.usage.input_tokens",
    "completion_tokens": "gen_ai.usage.output_tokens",
}


def tracer_provider() -> TracerProvider:
    """Spans for this service, sent on when an OTLP endpoint is configured."""
    provider = TracerProvider(resource=Resource.create({"service.name": "limespec"}))
    if os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    return provider


provider = tracer_provider()
tracer = provider.get_tracer("limespec")


def instrument(app: FastAPI) -> None:
    """A server span for every request, parent of the answer's spans. Health probes
    and the ASGI per-message spans (one per streamed event) are left out as noise."""
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="healthz,readyz",
        exclude_spans=["receive", "send"],
    )


@contextmanager
def span(
    name: str,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Attributes | None = None,
) -> Iterator[Span]:
    """A span around one step, current while it runs. An error ends it with the
    error status, the exception and `error.type`."""
    with tracer.start_as_current_span(name, kind=kind, attributes=attributes) as step:
        try:
            yield step
        except Exception as error:
            step.set_attribute("error.type", type(error).__qualname__)
            raise


def model_span(
    name: str, operation: str, url: str, attributes: Attributes
) -> AbstractContextManager[Span]:
    """A client span for one request to a model server."""
    server = httpx.URL(url)
    default_port = 443 if server.scheme == "https" else 80
    return span(
        name,
        SpanKind.CLIENT,
        {
            "gen_ai.operation.name": operation,
            "gen_ai.provider.name": PROVIDER,
            "server.address": server.host,
            "server.port": server.port or default_port,
            **attributes,
        },
    )


def chat_span() -> AbstractContextManager[Span]:
    # The request names no model: the server answers with whichever it loaded,
    # reported afterwards as gen_ai.response.model.
    return model_span(
        "chat",
        "chat",
        config.CHAT_URL,
        {
            "gen_ai.output.type": "json",
            "gen_ai.request.temperature": config.TEMPERATURE,
            "gen_ai.request.seed": config.SEED,
            "gen_ai.request.max_tokens": config.MAX_ANSWER_TOKENS,
        },
    )


def embeddings_span() -> AbstractContextManager[Span]:
    return model_span(
        f"embeddings {config.EMBEDDING_MODEL}",
        "embeddings",
        config.EMBEDDING_URL,
        {"gen_ai.request.model": config.EMBEDDING_MODEL},
    )


def rerank_span() -> AbstractContextManager[Span]:
    # Reranking has no GenAI operation name yet; the conventions allow a custom one.
    return model_span("rerank", "rerank", config.RERANK_URL, {})


def record_reply(model: object, finish_reason: object, usage: object) -> None:
    """What the server reports about a chat reply, on the current span. Values of
    an unexpected type are skipped: the reply itself is validated by the caller."""
    step = get_current_span()
    if isinstance(model, str):
        step.set_attribute("gen_ai.response.model", model)
    if isinstance(finish_reason, str):
        step.set_attribute("gen_ai.response.finish_reasons", [finish_reason])
    if isinstance(usage, dict):
        for key, name in USAGE.items():
            if type(usage.get(key)) is int:
                step.set_attribute(name, usage[key])


def record_answer(result: Answer, answer_id: int, index_version: int) -> None:
    """The outcome of an answer, on the current span, and its audit record id."""
    get_current_span().set_attributes(
        {
            "limespec.index.version": index_version,
            "limespec.answer.id": answer_id,
            "limespec.answer.status": result.status,
            "limespec.claims.kept": len(result.claims),
            "limespec.claims.removed": len(result.rejected),
        }
    )
