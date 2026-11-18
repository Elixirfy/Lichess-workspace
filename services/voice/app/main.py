import asyncio
import os
import threading
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


def create_app(recognizer=None, recordings_dir=None):
    gate = threading.BoundedSemaphore(1)
    jobs = set()

    @asynccontextmanager
    async def lifespan(app):
        nonlocal recognizer
        if recognizer is None:
            from .recognizer import Recognizer

            recognizer = await asyncio.to_thread(Recognizer)
        yield
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    if recordings_dir is not None:
        from .recordings import recording_routes

        app.include_router(recording_routes(recordings_dir))

    @app.get("/health")
    async def health():
        return {
            "ready": recognizer is not None,
            "model": "PhoWhisper-small",
            "vad": True,
        }

    @app.post("/transcribe")
    async def transcribe(request: Request):
        if (
            request.headers.get("origin")
            not in {"http://localhost:8080", "http://127.0.0.1:8080"}
            or request.headers.get("x-voice-asr") != "1"
        ):
            raise HTTPException(403, "Local same-origin voice input required")
        if request.headers.get("content-type") != "application/octet-stream":
            raise HTTPException(415, "Expected float32 mono PCM")
        context = request.headers.get("x-voice-context", "general")
        if context not in {"general", "promotion", "coordinates"}:
            raise HTTPException(400, "Invalid recognition context")
        try:
            rate = int(request.headers.get("x-sample-rate", ""))
        except ValueError:
            raise HTTPException(400, "Invalid sample rate") from None
        if rate not in {8000, 16000, 22050, 24000, 32000, 44100, 48000, 96000}:
            raise HTTPException(400, "Unsupported sample rate")
        if not gate.acquire(blocking=False):
            raise HTTPException(
                429, "Voice recognizer busy", headers={"Retry-After": "2"}
            )
        submitted = False
        try:
            data = bytearray()
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > rate * 4 * 12:
                        raise HTTPException(413, "Utterance exceeds 12 seconds")
                    data.extend(chunk)
            if len(data) % 4 or len(data) < rate * 4 // 10:
                raise HTTPException(400, "Invalid PCM length")
            samples = np.frombuffer(data, dtype="<f4").copy()
            if not np.isfinite(samples).all() or np.max(np.abs(samples)) > 1.001:
                raise HTTPException(400, "Invalid PCM samples")
            job = asyncio.create_task(
                asyncio.to_thread(recognizer.transcribe, samples, rate, context=context)
            )
            jobs.add(job)
            submitted = True

            def finished(task):
                jobs.discard(task)
                gate.release()
                if not task.cancelled():
                    task.exception()  # consume even if the client disconnected

            job.add_done_callback(finished)
            result = await asyncio.shield(job)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except TimeoutError:
            raise HTTPException(408, "Audio upload timed out") from None
        finally:
            # Cancellation cannot admit concurrent inference while its worker still runs.
            if not submitted:
                gate.release()

    return app


app = create_app(recordings_dir=os.environ.get("VOICE_RECORDINGS_DIR"))
