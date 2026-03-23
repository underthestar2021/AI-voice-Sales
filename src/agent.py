import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import AgentServer, AgentSession, JobContext, cli, room_io
from livekit.plugins import minimax, openai, volcengine

from assistant import Assistant
from metrics_hooks import (
    MetricsState,
    register_session_metrics_hooks,
    start_network_probe_task,
)
from metrics_logger import MetricsLogger

logger = logging.getLogger("agent")

load_dotenv(".env.local")

server = AgentServer()
METRICS_LOG_DIR = Path(__file__).resolve().parents[2] / "log"


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
        # 使用本地vllm部署的 Qwen 模型进行测试，替换为实际可用的模型和地址
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

    metrics_state = MetricsState()
    register_session_metrics_hooks(session, logger, metrics_logger, metrics_state)

    probe_task = start_network_probe_task(
        livekit_url=os.getenv("LIVEKIT_URL", ""),
        state=metrics_state,
        logger=logger,
        metrics_logger=metrics_logger,
    )
    try:
        await session.start(
            agent=Assistant(),
            room=ctx.room,
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(sample_rate=16000),
            ),
        )
    finally:
        if probe_task is not None:
            probe_task.cancel()
            try:
                await probe_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    cli.run_app(server)
