import logging
import os
import statistics
from typing import Any

from dotenv import load_dotenv
from livekit.agents import AgentServer, AgentSession, JobContext, JobProcess, cli, room_io
from livekit.plugins import aliyun, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from assistant import Assistant
from observability import LocalObservability, percentile, safe_name, setup_observability

logger = logging.getLogger("agent")

load_dotenv(".env.local")

server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    session_name = f"{safe_name(ctx.room.name)}_{safe_name(ctx.job.id)}"
    obs: LocalObservability = setup_observability(ctx, session_name)

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
                    "p50_ms": round(percentile(per_turn_ms, 0.5), 1),
                    "p95_ms": round(percentile(per_turn_ms, 0.95), 1),
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

    obs.sink.dump_files(
        chat_history={"items": []},
        perceived_latency=_build_perceived_latency_payload(),
    )

    @session.on("conversation_item_added")
    def _on_item_added(_event: Any) -> None:
        obs.sink.dump_files(
            chat_history=session.history.to_dict(exclude_timestamp=False),
            perceived_latency=_build_perceived_latency_payload(),
        )

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

        obs.logger_provider.force_flush()
        obs.tracer_provider.force_flush()
        logging.getLogger().removeHandler(obs.otel_handler)

        files = obs.sink.dump_files(
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
