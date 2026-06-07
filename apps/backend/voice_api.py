"""
ARIA Voice API — FastAPI application

Run with:
    uv run uvicorn voice_api:app --reload --port 8001

Endpoints:
    POST /voice/run    — accept transcript, return spoken summary
    GET  /health       — liveness check
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aria.voice.router import router as voice_router

app = FastAPI(
    title="ARIA Voice API",
    description="Browser voice interface for ARIA — read-only skills only; governance gate preserved",
    version="1.0.0",
)

# Allow the Vite dev server (localhost:5173) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

app.include_router(voice_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "aria-voice-api"}
