import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from json import JSONDecodeError
import json
from pathlib import Path
import statistics
from threading import Lock
from typing import Any

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
    room_io,
)
from livekit.plugins import aliyun, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
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

from livekit.agents.telemetry import set_tracer_provider

logger = logging.getLogger("agent")

load_dotenv(".env.local")

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "log"


def _safe_name(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", text).strip("_") or "unknown"


@dataclass
class _LocalTraceLogSink:
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
                        {
                            "scope": {"name": "livekit.agents.local"},
                            "spans": spans,
                        }
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
                        {
                            "scope": {"name": "livekit.agents.local"},
                            "logRecords": logs,
                        }
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


def _percentile(values: list[float], p: float) -> float:
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


class _InMemorySpanExporter(SpanExporter):
    def __init__(self, sink: _LocalTraceLogSink) -> None:
        self._sink = sink

    def export(self, spans: list[Any]) -> SpanExportResult:
        for span in spans:
            self._sink.add_span(span.to_json())
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class _InMemoryLogExporter(LogExporter):
    def __init__(self, sink: _LocalTraceLogSink) -> None:
        self._sink = sink

    def export(self, batch: list[Any]) -> LogExportResult:
        for record in batch:
            self._sink.add_log(record.to_json())
        return LogExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def _setup_local_observability(ctx: JobContext, session_name: str) -> dict[str, Any]:
    sink = _LocalTraceLogSink(base_name=session_name)
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
            _InMemorySpanExporter(sink),
            max_export_batch_size=64,
            schedule_delay_millis=500,
        )
    )
    set_tracer_provider(tracer_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            _InMemoryLogExporter(sink),
            max_export_batch_size=64,
            schedule_delay_millis=500,
        )
    )
    set_logger_provider(logger_provider)

    otel_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    logging.getLogger().addHandler(otel_handler)

    return {
        "sink": sink,
        "tracer_provider": tracer_provider,
        "logger_provider": logger_provider,
        "otel_handler": otel_handler,
    }


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""You are a helpful voice AI assistant. The user is interacting with you via voice, even if you perceive the conversation as text.
            You eagerly assist users with their questions by providing information from your extensive knowledge.
            Always answer in very short, natural spoken Chinese sentences that are easy to synthesize and interrupt.
            The first sentence must be extremely short, ideally 4 to 8 Chinese characters, and should be spoken immediately.
            After the first sentence, continue in short clauses, usually 6 to 16 Chinese characters each.
            Use normal spoken punctuation like commas, periods, question marks, and exclamation marks to create clear pauses.
            For stories or long answers, first say a tiny hook sentence, then continue one short clause at a time.
            Never start with a long sentence, a long setup, or a paragraph-sized clause.
            Avoid emojis, markdown, bullet points, and special symbols.
            You are curious, friendly, and have a sense of humor.""",
        )


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    session_name = f"{_safe_name(ctx.room.name)}_{_safe_name(ctx.job.id)}"
    local_obs = _setup_local_observability(ctx, session_name)
    sink: _LocalTraceLogSink = local_obs["sink"]
    tracer_provider: TracerProvider = local_obs["tracer_provider"]
    logger_provider: LoggerProvider = local_obs["logger_provider"]
    otel_handler: LoggingHandler = local_obs["otel_handler"]

    session = AgentSession(
        stt=aliyun.STT(model="paraformer-realtime-v2"),
        tts=aliyun.TTS(
            model="qwen3-tts-flash-realtime",
            voice="Cherry",
            min_sentence_length=4,
            use_level2_threshold=12,
            use_level3_threshold=20,
        ),
        llm=openai.LLM(
            model="qwen-flash",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=os.getenv("DASHSCOPE_API_KEY"),
        ),
        preemptive_generation=True,
        # Lower endpointing wait to reduce "user finished speaking -> agent starts" latency.
        min_endpointing_delay=0.25,
        max_endpointing_delay=1.2,
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
    )

    pending_user_end_at: float | None = None
    turn_latencies_s: list[float] = []

    def _build_perceived_latency_payload() -> dict[str, Any]:
        per_turn_ms = [round(v * 1000, 1) for v in turn_latencies_s]
        summary: dict[str, Any] = {"count": len(per_turn_ms)}
        if per_turn_ms:
            summary.update(
                {
                    "avg_ms": round(statistics.mean(per_turn_ms), 1),
                    "p50_ms": round(_percentile(per_turn_ms, 0.5), 1),
                    "p95_ms": round(_percentile(per_turn_ms, 0.95), 1),
                    "min_ms": round(min(per_turn_ms), 1),
                    "max_ms": round(max(per_turn_ms), 1),
                }
            )
        return {
            "definition": "user_state speaking->listening 到 agent_state -> speaking",
            "unit": "ms",
            "summary": summary,
            "per_turn_ms": per_turn_ms,
        }

    sink.dump_files(chat_history={"items": []}, perceived_latency=_build_perceived_latency_payload())

    def _dump_chat_history_snapshot() -> None:
        sink.dump_files(
            chat_history=session.history.to_dict(exclude_timestamp=False),
            perceived_latency=_build_perceived_latency_payload(),
        )

    @session.on("conversation_item_added")
    def _on_item_added(_event: Any) -> None:
        _dump_chat_history_snapshot()

    @session.on("user_state_changed")
    def _on_user_state_changed(event: Any) -> None:
        nonlocal pending_user_end_at
        if event.old_state == "speaking" and event.new_state in {"listening", "away"}:
            pending_user_end_at = float(event.created_at)

    @session.on("agent_state_changed")
    def _on_agent_state_changed(event: Any) -> None:
        nonlocal pending_user_end_at
        if event.new_state != "speaking" or pending_user_end_at is None:
            return
        delta = float(event.created_at) - pending_user_end_at
        # Ignore negative / implausible values caused by interrupts or state reordering.
        if 0.0 <= delta <= 10.0:
            turn_latencies_s.append(delta)
            logger.info(
                "perceived turn latency measured",
                extra={"perceived_turn_latency_ms": round(delta * 1000, 1)},
            )
        pending_user_end_at = None

    async def _on_shutdown(reason: str) -> None:
        session_report: dict[str, Any] | None = None
        try:
            report = ctx.make_session_report(session)
            session_report = report.to_dict()
            chat_history = report.chat_history.to_dict(exclude_timestamp=False)
        except Exception:
            logger.exception("failed to build session report, fallback to session history")
            chat_history = session.history.to_dict(exclude_timestamp=False)

        logger_provider.force_flush()
        tracer_provider.force_flush()
        logging.getLogger().removeHandler(otel_handler)

        files = sink.dump_files(
            chat_history=chat_history,
            session_report=session_report,
            perceived_latency=_build_perceived_latency_payload(),
        )
        logger.info(
            "local observability files written",
            extra={
                "shutdown_reason": reason,
                "traces_file": str(files["traces"]),
                "logs_file": str(files["logs"]),
                "chat_history_file": str(files["chat_history"]),
                "perceived_latency_file": str(files["perceived_latency"]),
            },
        )

    ctx.add_shutdown_callback(_on_shutdown)

    await ctx.connect()

    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(),
        ),
    )


if __name__ == "__main__":
    cli.run_app(server)
