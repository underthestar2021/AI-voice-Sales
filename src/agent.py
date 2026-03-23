import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from livekit.agents import (
    AgentServer,
    AgentSession,
    JobContext,
    cli,
    room_io,
)
from livekit.agents.metrics import EOUMetrics, LLMMetrics, STTMetrics, TTSMetrics
from livekit.plugins import minimax, openai, volcengine

from assistant import Assistant
from metrics_logger import MetricsLogger

logger = logging.getLogger("agent")

load_dotenv(".env.local")

server = AgentServer()
METRICS_LOG_DIR = Path(__file__).resolve().parents[2] / "log"


async def _probe_tcp_rtt(host: str, port: int, timeout_s: float = 2.0) -> float | None:
    '''通过 TCP 建连估算目标地址的网络 RTT（毫秒）。'''
    start = time.perf_counter()
    try:
        connect_coro = asyncio.open_connection(host, port)
        _, writer = await asyncio.wait_for(connect_coro, timeout=timeout_s)
        writer.close()
        await writer.wait_closed()
        return (time.perf_counter() - start) * 1000.0
    except Exception:
        return None


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext) -> None:
    '''my-agent 主会话入口：组装链路、接入房间并采集延迟指标。'''
    session_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    metrics_log_path = METRICS_LOG_DIR / f"{session_stamp}_metrics_{ctx.job.id}_{ctx.job.room.sid}.jsonl"
    metrics_logger = MetricsLogger(
        metrics_log_path,
        room=ctx.room.name if ctx.room else None,
        room_id=ctx.job.room.sid if ctx.job and ctx.job.room else None,
        job_id=ctx.job.id if ctx.job else None,
        agent_name="my-agent",
    )

    logger.warning("stt backend fixed", extra={"backend": "volcengine"})

    session = AgentSession(
        stt=volcengine.BigModelSTT(
            app_id=os.getenv("VOLCENGINE_STT_APP_ID", ""),
            access_token=os.getenv("VOLCENGINE_STT_ACCESS_TOKEN"),
            model_name=os.getenv("VOLCENGINE_BIGMODEL_STT_MODEL", "bigmodel"),
            enable_itn=False,
            enable_punc=False,
            enable_ddc=False,
            vad_segment_duration=1200,
            end_window_size=240,
            force_to_speech_time=1000,
            interim_results=True,
        ),
        # llm=openai.LLM(
        #     model="./qwen",
        #     base_url="http://127.0.0.1:8000/v1",
        #     api_key="fake-key",
        # ),
        llm=openai.LLM(
            model="qwen-flash",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=os.getenv("DASHSCOPE_API_KEY"),
        ),
        tts=minimax.TTS(
            model="speech-02-turbo",
            voice="socialmedia_female_1_v1",
            api_key=os.getenv("MINIMAX_API_KEY"),
            base_url="https://api.minimax.chat",
            speed=1.05,
        ),
        preemptive_generation=True,
        min_interruption_duration=0.2,
        min_endpointing_delay=0.0,
        max_endpointing_delay=0.05,
        turn_detection="stt",
    )

    await ctx.connect()

    last_user_created_at: float | None = None
    last_tcp_rtt_ms: float | None = None
    last_user_stop_at: float | None = None
    last_interim_text: str = ""

    livekit_url = os.getenv("LIVEKIT_URL", "")
    parsed = urlparse(livekit_url)
    probe_host = parsed.hostname
    if parsed.port:
        probe_port = parsed.port
    elif parsed.scheme == "wss":
        probe_port = 443
    else:
        probe_port = 80

    @session.on("conversation_item_added")
    def _on_conversation_item_added(ev):
        '''处理会话消息事件，记录用户到 AI 首音频的端到端延迟。'''
        nonlocal last_user_created_at
        item = getattr(ev, "item", None)
        if item is None or getattr(item, "type", None) != "message":
            return

        role = getattr(item, "role", None)
        if role == "user":
            last_user_created_at = getattr(item, "created_at", None)
        elif role == "assistant" and last_user_created_at is not None:
            item_metrics = getattr(item, "metrics", {}) or {}
            started = item_metrics.get("started_speaking_at")
            if isinstance(started, (int, float)):
                e2e_from_user_ms = (started - last_user_created_at) * 1000.0
                logger.info(
                    "latency.e2e_user_to_first_audio",
                    extra={
                        "e2e_ms": round(e2e_from_user_ms, 1),
                        "tcp_rtt_ms": round(last_tcp_rtt_ms, 1) if last_tcp_rtt_ms else None,
                    },
                )
                metrics_logger.append(
                    "latency.e2e_user_to_first_audio",
                    {
                        "e2e_ms": round(e2e_from_user_ms, 1),
                        "tcp_rtt_ms": round(last_tcp_rtt_ms, 1) if last_tcp_rtt_ms else None,
                    },
                )

    @session.on("user_state_changed")
    def _on_user_state_changed(ev):
        '''处理用户状态变化，在停说时记录时间锚点。'''
        nonlocal last_user_stop_at
        if getattr(ev, "old_state", None) == "speaking" and getattr(ev, "new_state", None) == "listening":
            last_user_stop_at = float(getattr(ev, "created_at", time.time()))

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev):
        '''处理 STT 转写事件并写入 interim/final 与 STT 延迟指标。'''
        nonlocal last_user_stop_at, last_interim_text
        transcript = str(getattr(ev, "transcript", "") or "").strip()
        if not transcript:
            return

        is_final = bool(getattr(ev, "is_final", False))
        if not is_final:
            if transcript != last_interim_text:
                last_interim_text = transcript
                payload = {
                    "text": transcript,
                    "text_len": len(transcript),
                    "is_final": False,
                }
                logger.info("transcript.interim", extra=payload)
                metrics_logger.append("transcript.interim", payload)
            return

        now_ts = float(getattr(ev, "created_at", time.time()))
        payload_final = {
            "text": transcript,
            "text_len": len(transcript),
            "is_final": True,
            "backfill_from_interim": bool(last_interim_text),
        }
        logger.info("transcript.final", extra=payload_final)
        metrics_logger.append("transcript.final", payload_final)
        last_interim_text = ""

        if last_user_stop_at is None:
            return

        payload = {
            "finalization_ms": round((now_ts - last_user_stop_at) * 1000.0, 1),
            "transcript_len": len(transcript),
            "is_final": True,
        }
        logger.info("latency.stt_final", extra=payload)
        metrics_logger.append("latency.stt_final", payload)
        last_user_stop_at = None

    @session.on("metrics_collected")
    def _on_metrics(ev):
        '''统一处理 EOU/LLM/TTS/STT 指标并写入日志。'''
        m = getattr(ev, "metrics", None)
        if m is None:
            return

        if isinstance(m, EOUMetrics):
            payload = {
                "end_of_utterance_ms": round(m.end_of_utterance_delay * 1000.0, 1),
                "transcription_ms": round(m.transcription_delay * 1000.0, 1),
                "on_user_turn_completed_ms": round(m.on_user_turn_completed_delay * 1000.0, 1),
                "speech_id": m.speech_id,
            }
            logger.info("latency.eou", extra=payload)
            metrics_logger.append("latency.eou", payload)
        elif isinstance(m, LLMMetrics):
            payload = {
                "ttft_ms": round(m.ttft * 1000.0, 1),
                "duration_ms": round(m.duration * 1000.0, 1),
                "request_id": m.request_id,
                "model": m.label,
            }
            logger.info("latency.llm", extra=payload)
            metrics_logger.append("latency.llm", payload)
        elif isinstance(m, TTSMetrics):
            payload = {
                "ttfb_ms": round(m.ttfb * 1000.0, 1),
                "duration_ms": round(m.duration * 1000.0, 1),
                "audio_duration_ms": round(m.audio_duration * 1000.0, 1),
                "request_id": m.request_id,
                "model": m.label,
            }
            logger.info("latency.tts", extra=payload)
            metrics_logger.append("latency.tts", payload)
        elif isinstance(m, STTMetrics):
            payload = {
                "duration_ms": round(m.duration * 1000.0, 1),
                "audio_duration_ms": round(m.audio_duration * 1000.0, 1),
                "request_id": m.request_id,
                "model": m.label,
                "streamed": m.streamed,
            }
            logger.info("latency.stt", extra=payload)
            metrics_logger.append("latency.stt", payload)

    async def _network_probe_loop() -> None:
        '''周期探测网络 RTT，并写入网络探针指标。'''
        nonlocal last_tcp_rtt_ms
        if not probe_host:
            return
        while True:
            rtt = await _probe_tcp_rtt(probe_host, probe_port, timeout_s=2.0)
            last_tcp_rtt_ms = rtt
            if rtt is not None:
                payload = {"host": probe_host, "port": probe_port, "tcp_rtt_ms": round(rtt, 1)}
                logger.info("latency.network_probe", extra=payload)
                metrics_logger.append("latency.network_probe", payload)
            await asyncio.sleep(5.0)

    probe_task = asyncio.create_task(_network_probe_loop())
    try:
        await session.start(
            agent=Assistant(),
            room=ctx.room,
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(sample_rate=16000),
            ),
        )
    finally:
        probe_task.cancel()
        try:
            await probe_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    cli.run_app(server)
