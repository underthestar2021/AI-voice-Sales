import asyncio
import json
from dataclasses import dataclass
from typing import Any

import websockets
from livekit.agents import APIConnectionError, DEFAULT_API_CONNECT_OPTIONS, stt
from livekit.agents.types import NOT_GIVEN, APIConnectOptions, NotGivenOr


@dataclass
class _SegmentState:
    ws: Any
    recv_task: asyncio.Task[None]
    final_future: asyncio.Future[None] | None = None
    audio_duration: float = 0.0


class QwenStreamingSTT(stt.STT):
    def __init__(self, *, ws_url: str, model: str = "qwen3-asr-streaming") -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=True,
                aligned_transcript=False,
                offline_recognize=False,
            )
        )
        self._ws_url = ws_url
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "qwen_streaming_ws"

    async def _recognize_impl(
        self,
        buffer,
        *,
        language=NOT_GIVEN,
        conn_options: APIConnectOptions,
    ):
        raise NotImplementedError("QwenStreamingSTT only supports stream()")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ):
        return _QwenSpeechStream(stt=self, conn_options=conn_options)

    async def aclose(self) -> None:
        return None


class _QwenSpeechStream(stt.SpeechStream):
    def __init__(self, *, stt: QwenStreamingSTT, conn_options: APIConnectOptions) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=16000)
        self._qwen_stt = stt
        self._segment: _SegmentState | None = None
        self._awaiting_new_turn = True

    async def _start_segment(self) -> _SegmentState:
        try:
            ws = await websockets.connect(self._qwen_stt._ws_url, max_size=None)
            await ws.send(json.dumps({"type": "start"}))
            ack = json.loads(await ws.recv())
            if ack.get("type") != "started":
                raise APIConnectionError(f"unexpected start response: {ack}")
        except Exception as exc:
            raise APIConnectionError(f"failed to connect qwen streaming stt: {exc}") from exc

        return _SegmentState(
            ws=ws,
            recv_task=asyncio.create_task(self._recv_loop(ws)),
        )

    async def _recv_loop(self, ws: Any) -> None:
        try:
            async for raw in ws:
                payload = json.loads(raw)
                msg_type = payload.get("type")
                text = str(payload.get("text", "") or "")
                language = str(payload.get("language", "") or "")

                if msg_type == "interim" and text:
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(
                            type=stt.SpeechEventType.INTERIM_TRANSCRIPT,
                            alternatives=[
                                stt.SpeechData(text=text, language=language or "zh")
                            ],
                        )
                    )
                elif msg_type == "final":
                    if text:
                        self._event_ch.send_nowait(
                            stt.SpeechEvent(
                                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                                alternatives=[
                                    stt.SpeechData(text=text, language=language or "zh")
                                ],
                            )
                        )
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH)
                    )
                    if self._segment is not None:
                        self._event_ch.send_nowait(
                            stt.SpeechEvent(
                                type=stt.SpeechEventType.RECOGNITION_USAGE,
                                recognition_usage=stt.RecognitionUsage(
                                    audio_duration=self._segment.audio_duration
                                ),
                            )
                        )
                        if self._segment.final_future is not None:
                            if not self._segment.final_future.done():
                                self._segment.final_future.set_result(None)
                            self._segment.final_future = None
                        self._segment.audio_duration = 0.0
                    self._awaiting_new_turn = True
                elif msg_type == "error":
                    raise APIConnectionError(
                        payload.get("message", "streaming stt error")
                    )
        except Exception as exc:
            if self._segment is not None and self._segment.final_future is not None:
                if not self._segment.final_future.done():
                    self._segment.final_future.set_exception(exc)
            raise

    async def _finish_segment(self) -> None:
        if self._segment is None:
            return

        segment = self._segment
        self._segment = None

        try:
            if self._awaiting_new_turn:
                await segment.ws.close()
                return

            segment.final_future = asyncio.get_running_loop().create_future()
            await segment.ws.send(json.dumps({"type": "finish"}))
            await segment.final_future
        finally:
            self._awaiting_new_turn = True
            try:
                await segment.ws.close()
            finally:
                await asyncio.gather(segment.recv_task, return_exceptions=True)

    async def _run(self) -> None:
        async for data in self._input_ch:
            if isinstance(data, self._FlushSentinel):
                await self._finish_segment()
                continue

            if self._segment is None:
                self._segment = await self._start_segment()

            if self._awaiting_new_turn:
                self._event_ch.send_nowait(
                    stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                )
                self._awaiting_new_turn = False

            await self._segment.ws.send(data.data.tobytes())
            self._segment.audio_duration += (
                data.samples_per_channel / float(data.sample_rate)
            )

        await self._finish_segment()
