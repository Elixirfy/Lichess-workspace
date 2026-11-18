"""Explicit, bounded local recording storage, separate from transient ASR input."""

import asyncio
import hashlib
import io
import json
import re
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

ASSETS = Path(__file__).parent
PHRASES = json.loads((ASSETS / "recording_phrases.json").read_text(encoding="utf-8"))
PHRASES += json.loads(
    (ASSETS / "file_recording_phrases.json").read_text(encoding="utf-8")
)
RATES = {8000, 16000, 22050, 24000, 32000, 44100, 48000, 96000}
NO_CACHE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def local_request(request, *, writing=False):
    origin = request.headers.get("origin")
    if (
        request.headers.get("x-voice-recording") != "1"
        or (writing and not origin)
        or (origin and origin not in {"http://localhost:8080", "http://127.0.0.1:8080"})
    ):
        raise HTTPException(403, "Local recording request required")


def recording_routes(directory):
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    router = APIRouter()
    save_lock = asyncio.Lock()

    @router.get("/record")
    async def page():
        return FileResponse(
            ASSETS / "static/record.html",
            headers={
                **NO_CACHE,
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; media-src 'self' blob:; "
                "object-src 'none'; frame-ancestors 'self'",
                "Referrer-Policy": "no-referrer",
            },
        )

    @router.get("/record.js")
    async def script():
        return FileResponse(ASSETS / "static/record.js", headers=NO_CACHE)

    @router.get("/recordings")
    async def listing(request: Request):
        local_request(request)
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in root.glob("*.json")
            if re.fullmatch(r"[a-f0-9]{32}", path.stem)
        ]
        return JSONResponse(
            {
                "phrases": [{k: p[k] for k in ("id", "text", "kind")} for p in PHRASES],
                "recordings": sorted(records, key=lambda x: x["created_at"]),
            },
            headers=NO_CACHE,
        )

    @router.get("/recordings/{recording_id}/audio")
    async def audio(recording_id: str, request: Request):
        local_request(request)
        if not re.fullmatch(r"[a-f0-9]{32}", recording_id):
            raise HTTPException(404)
        path = root / f"{recording_id}.wav"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="audio/wav", headers=NO_CACHE)

    @router.post("/recordings")
    async def save(request: Request):
        local_request(request, writing=True)
        if request.headers.get("content-type") != "application/octet-stream":
            raise HTTPException(415, "Expected float32 mono PCM")
        phrase = next(
            (p for p in PHRASES if p["id"] == request.headers.get("x-voice-phrase")),
            None,
        )
        if phrase is None:
            raise HTTPException(400, "Unknown phrase")
        try:
            rate = int(request.headers.get("x-sample-rate", ""))
        except ValueError:
            raise HTTPException(400, "Invalid sample rate") from None
        if rate not in RATES:
            raise HTTPException(400, "Unsupported sample rate")
        capture = request.headers.get("x-voice-capture", "microphone")
        if capture not in {"microphone", "fixture"}:
            raise HTTPException(400, "Unknown recording source")
        data = bytearray()
        try:
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > rate * 4 * 12:
                        raise HTTPException(413, "Recording exceeds 12 seconds")
                    data.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "Upload timed out") from None
        if len(data) % 4 or len(data) < rate * 4 // 10:
            raise HTTPException(400, "Invalid PCM length")
        samples = np.frombuffer(data, dtype="<f4")
        if not np.isfinite(samples).all() or np.max(np.abs(samples)) > 1:
            raise HTTPException(400, "Invalid PCM samples")
        encoded = io.BytesIO()
        with wave.open(encoded, "wb") as wav:
            wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            wav.writeframes((samples * 32767).astype("<i2").tobytes())
        content = encoded.getvalue()
        item = {
            "id": uuid.uuid4().hex,
            "phrase_id": phrase["id"],
            "text": phrase["text"],
            "source": "browser-microphone"
            if capture == "microphone"
            else "test-fixture",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sample_rate": rate,
            "duration_seconds": len(samples) / rate,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        async with save_lock:
            if len(list(root.glob("*.wav"))) >= 128:
                raise HTTPException(507, "Recording storage is full (128 takes)")
            audio_path = root / f"{item['id']}.wav"
            meta_path = root / f"{item['id']}.json"
            # Publish metadata only after the complete WAV exists. Retakes get new IDs.
            try:
                with audio_path.open("xb") as file:
                    file.write(content)
                with meta_path.open("x", encoding="utf-8") as file:
                    json.dump(item, file, ensure_ascii=False, indent=2)
            except OSError:
                audio_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                raise HTTPException(507, "Cannot save recording") from None
        return JSONResponse(item, status_code=201, headers=NO_CACHE)

    return router
