"""Tracing: export over OTLP/HTTP, errors on spans, and reply details."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from limespec import config, telemetry


def test_spans_are_sent_over_otlp_http_when_an_endpoint_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[tuple[str, str]] = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, self.headers["Content-Type"]))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            """Keep the test output quiet."""

    server = HTTPServer(("127.0.0.1", 0), Collector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    path = "/insert/opentelemetry/v1/traces"
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        f"http://127.0.0.1:{server.server_port}{path}",
    )

    provider = telemetry.tracer_provider()
    with provider.get_tracer("test").start_as_current_span("answer"):
        pass
    provider.shutdown()  # sends what is waiting
    server.shutdown()

    assert received == [(path, "application/x-protobuf")]


def test_an_error_marks_the_span_with_its_type(spans: InMemorySpanExporter) -> None:
    with pytest.raises(ValueError), telemetry.span("searching"):
        raise ValueError("no passages")

    [searching] = spans.get_finished_spans()
    assert searching.status.status_code is StatusCode.ERROR
    assert searching.attributes is not None
    assert searching.attributes["error.type"] == "ValueError"


def test_reply_details_of_an_unexpected_type_are_skipped(
    spans: InMemorySpanExporter,
) -> None:
    with telemetry.chat_span():
        telemetry.record_reply(["not", "a", "name"], None, {"prompt_tokens": "12"})

    [chat] = spans.get_finished_spans()
    assert chat.attributes is not None
    for name in ["gen_ai.response.model", "gen_ai.response.finish_reasons"]:
        assert name not in chat.attributes
    assert "gen_ai.usage.input_tokens" not in chat.attributes


def test_an_https_model_server_defaults_to_port_443(
    monkeypatch: pytest.MonkeyPatch, spans: InMemorySpanExporter
) -> None:
    monkeypatch.setattr(config, "RERANK_URL", "https://rerank.test/v1/rerank")

    with telemetry.rerank_span():
        pass

    [rerank] = spans.get_finished_spans()
    assert rerank.attributes is not None
    assert (rerank.attributes["server.address"], rerank.attributes["server.port"]) == (
        "rerank.test",
        443,
    )
