"""Persistent, isolated CPU VieNeu Nano process; JSON lines match the Piper transport."""
import base64
from contextlib import redirect_stdout
import io
import json
import os
import sys
import wave

from voices import NANO_VOICES, nano_speed
from nano_audio import pcm16

with redirect_stdout(sys.stderr):
    from vieneu import Vieneu
    tts = Vieneu(mode="v3nano", onnx_dir=sys.argv[1],
                 threads=max(1, min(2, int(os.getenv("BLV_NANO_THREADS", "1")))),
                 steps=int(os.getenv("BLV_NANO_STEPS", "16")))
    speed = float(os.getenv("BLV_NANO_SPEED", "1.2"))
    if not 0.8 <= speed <= 1.5:
        raise ValueError("BLV_NANO_SPEED must be between 0.8 and 1.5")

print('{"ready":true}', flush=True)
for line in sys.stdin:
    try:
        request = json.loads(line)
        with redirect_stdout(sys.stderr):
            samples = tts.infer(request["text"][:500], voice=NANO_VOICES[request["voice"]],
                                sway=-1, speed=nano_speed(request["voice"], speed), seed=42)
        pcm = pcm16(samples)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(tts.sample_rate)
            wav.writeframes(pcm)
        print(json.dumps({"audio": base64.b64encode(output.getvalue()).decode()}), flush=True)
    except Exception:
        print('{"error":"nano synthesis failed"}', flush=True)
