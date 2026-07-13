from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .auth import authenticate
from .config import Settings
from .models import Principal, StartCallRequest, UtteranceRequest, VoiceCall
from .policy import PolicyViolation
from .service import VoiceOpsService
from .voice import AcsCallGateway, AzureSpeechSynthesizer, MediaHub, read_transcription_event

logger = logging.getLogger("voiceops.api")
settings = Settings.from_environment()
service = VoiceOpsService(settings)
media_hub = MediaHub()
static_dir = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="VoiceOps Sentinel", version="0.1.0", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "public, max-age=300"
    return response


def principal(authorization: str | None, role: str) -> Principal:
    return authenticate(authorization, settings, role)


def http_error(error: Exception) -> HTTPException:
    if isinstance(error, KeyError):
        return HTTPException(status_code=404, detail="Call not found.")
    if isinstance(error, PolicyViolation):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, RuntimeError):
        return HTTPException(status_code=503, detail=str(error))
    return HTTPException(status_code=500, detail="VoiceOps request failed.")


async def deliver_voice_response(call: VoiceCall) -> None:
    if not settings.is_production or not call.latest_assessment or not call.acs_call_connection_id:
        return
    try:
        audio = await AzureSpeechSynthesizer(settings).synthesize_pcm(call.latest_assessment.spoken_response)
        await media_hub.send_pcm(call.id, audio)
    except Exception:
        logger.exception("speech_delivery_failed", extra={"call_id": call.id})


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readiness() -> dict[str, object]:
    gaps = settings.production_gaps() if settings.is_production else []
    return {"status": "ready" if not gaps else "not_ready", "environment": settings.environment, "gaps": gaps}


@app.get("/api/calls", response_model=list[VoiceCall])
def list_calls() -> list[VoiceCall]:
    return service.repository.recent()


@app.post("/api/calls", response_model=VoiceCall, status_code=201)
async def create_call(
    request: StartCallRequest,
    authorization: str | None = Header(default=None),
    actor_role: str = Header(default="voiceops_operator", alias="X-VoiceOps-Development-Role"),
) -> VoiceCall:
    try:
        call = await service.start_call(request, principal(authorization, actor_role))
        await deliver_voice_response(call)
        return call
    except Exception as error:
        raise http_error(error) from error


@app.post("/api/calls/{call_id}/utterances", response_model=VoiceCall)
async def add_utterance(
    call_id: str,
    request: UtteranceRequest,
    authorization: str | None = Header(default=None),
    actor_role: str = Header(default="voiceops_operator", alias="X-VoiceOps-Development-Role"),
) -> VoiceCall:
    try:
        call = await service.ingest_utterance(call_id, request, principal(authorization, actor_role))
        await deliver_voice_response(call)
        return call
    except Exception as error:
        raise http_error(error) from error


@app.post("/api/calls/{call_id}/approve", response_model=VoiceCall)
def approve_recommendation(
    call_id: str,
    authorization: str | None = Header(default=None),
    actor_role: str = Header(default="voiceops_supervisor", alias="X-VoiceOps-Development-Role"),
) -> VoiceCall:
    try:
        return service.approve_recommendation(call_id, principal(authorization, actor_role))
    except Exception as error:
        raise http_error(error) from error


@app.post("/api/calls/{call_id}/end", response_model=VoiceCall)
def end_call(
    call_id: str,
    authorization: str | None = Header(default=None),
    actor_role: str = Header(default="voiceops_operator", alias="X-VoiceOps-Development-Role"),
) -> VoiceCall:
    try:
        return service.end_call(call_id, principal(authorization, actor_role))
    except Exception as error:
        raise http_error(error) from error


@app.post("/integrations/acs/events")
async def acs_events(events: list[dict[str, Any]]) -> dict[str, object]:
    """Receives Event Grid subscription validation and ACS incoming/call-control events."""
    if events and events[0].get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
        return {"validationResponse": events[0].get("data", {}).get("validationCode")}
    if not settings.is_production:
        raise HTTPException(status_code=503, detail="ACS callbacks are enabled only in production mode.")
    settings.assert_production_ready()
    system = Principal(subject="acs-call-automation", roles={"system"})
    processed: list[str] = []
    for event in events:
        data = event.get("data", {})
        if event.get("eventType") == "Microsoft.Communication.IncomingCall":
            incoming_context = data.get("incomingCallContext")
            if not incoming_context:
                continue
            connection_id = await AcsCallGateway(settings).answer_incoming(incoming_context)
            call = await service.start_call(
                StartCallRequest(channel="pstn", caller_reference=f"acs-{connection_id[-12:]}", locale="en-US"),
                system,
                acs_call_connection_id=connection_id,
            )
            processed.append(call.id)
            continue
        connection_id = data.get("callConnectionId") or data.get("call_connection_id")
        transcript = read_transcription_event(data)
        if connection_id and transcript:
            call = service.repository.find_by_acs_connection(connection_id)
            if call:
                updated = await service.ingest_utterance(call.id, UtteranceRequest(text=transcript, source="transcription"), system)
                await deliver_voice_response(updated)
                processed.append(updated.id)
    return {"accepted": True, "processed_call_ids": processed}


@app.websocket("/media")
async def acs_media_stream(websocket: WebSocket) -> None:
    """ACS bidirectional PCM media socket; utterance processing occurs only from transcription events."""
    await websocket.accept()
    call_id: str | None = None
    try:
        metadata = await websocket.receive_json()
        metadata_block = metadata.get("AudioMetadata", metadata.get("audioMetadata", metadata))
        connection_id = metadata_block.get("CallConnectionId") or metadata_block.get("callConnectionId")
        call = service.repository.find_by_acs_connection(connection_id) if connection_id else None
        if not call:
            await websocket.close(code=4404)
            return
        call_id = call.id
        media_hub.bind(call_id, websocket)
        while True:
            payload = await websocket.receive_json()
            transcript = read_transcription_event(payload)
            if transcript:
                updated = await service.ingest_utterance(
                    call_id,
                    UtteranceRequest(text=transcript, source="transcription"),
                    Principal(subject="acs-media-stream", roles={"system"}),
                )
                await deliver_voice_response(updated)
    except WebSocketDisconnect:
        return
    finally:
        if call_id:
            media_hub.detach(call_id)
