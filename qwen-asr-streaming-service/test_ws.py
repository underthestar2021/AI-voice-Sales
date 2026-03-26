import asyncio
import json
import wave

import websockets


WAV_PATH = "/root/my-vllm-py312-cu128/test_16k.wav"
WS_URL = "ws://127.0.0.1:8001/ws"


async def main():
    async with websockets.connect(WS_URL, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start"}))
        print(await ws.recv())

        with wave.open(WAV_PATH, "rb") as wf:
            print("rate:", wf.getframerate())
            print("channels:", wf.getnchannels())
            print("width:", wf.getsampwidth())

            assert wf.getframerate() == 16000
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2

            chunk_frames = 1600
            while True:
                data = wf.readframes(chunk_frames)
                if not data:
                    break

                await ws.send(data)

                try:
                    while True:
                        msg = await asyncio.wait_for(ws.recv(), timeout=0.05)
                        print(msg)
                except asyncio.TimeoutError:
                    pass

        await ws.send(json.dumps({"type": "finish"}))
        print(await ws.recv())


asyncio.run(main())
