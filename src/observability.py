import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from threading import Lock
from typing import Any

from livekit.agents import JobContext
from livekit.agents.telemetry import set_tracer_provider
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    LogExportResult,
    LogExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult, SpanExporter

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "log"


def safe_name(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", text).strip("_") or "unknown"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    arr = sorted(values)
    if len(arr) == 1:
        return arr[0]
    k = (len(arr) - 1) * p
    f = int(k)
    c = min(f + 1, len(arr) - 1)
    if f == c:
        return arr[f]
    return arr[f] + (arr[c] - arr[f]) * (k - f)


@dataclass
class TraceLogSink:
    base_name: str

    def __post_init__(self) -> None:
        self._lock = Lock()
        self._spans: list[dict[str, Any]] = []
        self._logs: list[dict[str, Any]] = []

    def add_span(self, payload: str) -> None:
        try:
            parsed = json.loads(payload)
        except JSONDecodeError:
            return
        with self._lock:
            self._spans.append(parsed)

    def add_log(self, payload: str) -> None:
        try:
            parsed = json.loads(payload)
        except JSONDecodeError:
            return
        with self._lock:
            self._logs.append(parsed)

    def dump_files(
        self,
        *,
        chat_history: dict[str, Any],
        session_report: dict[str, Any] | None = None,
        perceived_latency: dict[str, Any] | None = None,
    ) -> dict[str, Path]:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with self._lock:
            spans = list(self._spans)
            logs = list(self._logs)

        resource_from_spans = spans[0].get("resource", {}) if spans else {}
        resource_from_logs = logs[0].get("resource", {}) if logs else {}

        traces_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "resourceSpans": [
                {
                    "resource": resource_from_spans,
                    "scopeSpans": [
                        {"scope": {"name": "livekit.agents.local"}, "spans": spans}
                    ],
                }
            ],
        }
        logs_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "resourceLogs": [
                {
                    "resource": resource_from_logs,
                    "scopeLogs": [
                        {"scope": {"name": "livekit.agents.local"}, "logRecords": logs}
                    ],
                }
            ],
        }

        traces_path = OUTPUT_DIR / f"{self.base_name}_traces.json"
        logs_path = OUTPUT_DIR / f"{self.base_name}_logs.json"
        chat_path = OUTPUT_DIR / f"{self.base_name}_chat_history.json"
        perceived_latency_path = OUTPUT_DIR / f"{self.base_name}_perceived_latency.json"

        traces_path.write_text(
            json.dumps(traces_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logs_path.write_text(
            json.dumps(logs_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        chat_path.write_text(
            json.dumps(chat_history, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        perceived_latency_path.write_text(
            json.dumps(perceived_latency or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        report_path: Path | None = None
        if session_report is not None:
            report_path = OUTPUT_DIR / f"{self.base_name}_session_report.json"
            report_path.write_text(
                json.dumps(session_report, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        return {
            "traces": traces_path,
            "logs": logs_path,
            "chat_history": chat_path,
            "perceived_latency": perceived_latency_path,
            "session_report": report_path,
        }


class _SpanExporter(SpanExporter):
    def __init__(self, sink: TraceLogSink) -> None:
        self._sink = sink

    def export(self, spans: list[Any]) -> SpanExportResult:
        for span in spans:
            self._sink.add_span(span.to_json())
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class _LogExporter(LogExporter):
    def __init__(self, sink: TraceLogSink) -> None:
        self._sink = sink

    def export(self, batch: list[Any]) -> LogExportResult:
        for record in batch:
            self._sink.add_log(record.to_json())
        return LogExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


@dataclass
class LocalObservability:
    sink: TraceLogSink
    tracer_provider: TracerProvider
    logger_provider: LoggerProvider
    otel_handler: LoggingHandler


def setup_observability(ctx: JobContext, session_name: str) -> LocalObservability:
    sink = TraceLogSink(base_name=session_name)
    resource = Resource.create(
        {
            "service.name": "livekit-agents",
            "job_id": ctx.job.id,
            "room_id": ctx.job.room.sid,
            "room": ctx.room.name,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            _SpanExporter(sink),
            max_export_batch_size=64,
            schedule_delay_millis=500,
        )
    )
    set_tracer_provider(tracer_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            _LogExporter(sink),
            max_export_batch_size=64,
            schedule_delay_millis=500,
        )
    )
    set_logger_provider(logger_provider)

    otel_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    logging.getLogger().addHandler(otel_handler)

    return LocalObservability(
        sink=sink,
        tracer_provider=tracer_provider,
        logger_provider=logger_provider,
        otel_handler=otel_handler,
    )
