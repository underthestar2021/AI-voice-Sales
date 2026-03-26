import argparse
import wave

import numpy as np
import soundfile as sf


def convert_wav(src: str, dst: str, target_sr: int = 16000) -> None:
    audio, sr = sf.read(src, dtype="float32", always_2d=False)

    if getattr(audio, 'ndim', 1) > 1:
        audio = audio.mean(axis=1)

    if sr != target_sr:
        duration = len(audio) / float(sr)
        new_len = int(round(duration * target_sr))
        x_old = np.linspace(0.0, duration, num=len(audio), endpoint=False)
        x_new = np.linspace(0.0, duration, num=new_len, endpoint=False)
        audio = np.interp(x_new, x_old, audio).astype(np.float32)

    audio = np.clip(audio, -1.0, 1.0)
    pcm16 = (audio * 32767.0).astype(np.int16)

    with wave.open(dst, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(target_sr)
        wf.writeframes(pcm16.tobytes())

    print(f"written: {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert wav to 16k mono PCM16")
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("--sample-rate", type=int, default=16000)
    args = parser.parse_args()
    convert_wav(args.src, args.dst, target_sr=args.sample_rate)


if __name__ == "__main__":
    main()
