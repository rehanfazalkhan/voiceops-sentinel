from __future__ import annotations

import asyncio
import base64
from typing import Any

from fastapi import WebSocket

from .config import Settings


class MediaHub:
    """Tracks ACS media WebSockets for the lifetime of a connected call."""

    def __init__(self) -> None:
        self.connections: dict[str, WebSocket] = {}

    async def attach(self, call_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.bind(call_id, websocket)

    def bind(self, call_id: str, websocket: WebSocket) -> None:
        self.connections[call_id] = websocket

    def detach(self, call_id: str) -> None:
        self.connections.pop(call_id, None)

    async def send_pcm(self, call_id: str, audio: bytes) -> bool:
        websocket = self.connections.get(call_id)
        if not websocket:
            return False
        await websocket.send_json({"Kind": "AudioData", "AudioData": {"Data": base64.b64encode(audio).decode("ascii")}})
        return True


class AcsCallGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def answer_incoming(self, incoming_call_context: str) -> str:
        return await asyncio.to_thread(self._answer_incoming, incoming_call_context)

    def _answer_incoming(self, incoming_call_context: str) -> str:
        from azure.communication.callautomation import (
            AudioFormat,
            CallAutomationClient,
            MediaStreamingAudioChannelType,
            MediaStreamingContentType,
            MediaStreamingOptions,
            StreamingTransportType,
        )
        from azure.identity import DefaultAzureCredential

        media_streaming = MediaStreamingOptions(
            transport_url=self.settings.media_websocket_url,
            transport_type=StreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.MIXED,
            start_media_streaming=True,
            enable_bidirectional=True,
            enable_dtmf_tones=True,
            audio_format=AudioFormat.PCM24_K_MONO,
        )
        client = CallAutomationClient(self.settings.communication_endpoint, credential=DefaultAzureCredential())
        result = client.answer_call(
            incoming_call_context=incoming_call_context,
            media_streaming=media_streaming,
            callback_url=self.settings.communication_callback_url,
        )
        return result.call_connection_id


class AzureSpeechSynthesizer:
    """Synthesizes 24k mono PCM so ACS can return audio over its media WebSocket."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def synthesize_pcm(self, text: str) -> bytes:
        return await asyncio.to_thread(self._synthesize_pcm, text)

    def _synthesize_pcm(self, text: str) -> bytes:
        import azure.cognitiveservices.speech as speechsdk
        from azure.identity import DefaultAzureCredential

        token = DefaultAzureCredential().get_token("https://cognitiveservices.azure.com/.default").token
        speech_config = speechsdk.SpeechConfig(auth_token=token, endpoint=self.settings.speech_endpoint)
        speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm)
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        result = synthesizer.speak_text_async(text).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise RuntimeError(f"Azure Speech synthesis failed: {result.reason}")
        return bytes(result.audio_data)


def read_transcription_event(payload: dict[str, Any]) -> str | None:
    """Accepts ACS transcription callback shapes without treating raw audio as a transcript."""
    candidates = (
        payload.get("text"),
        payload.get("Text"),
        payload.get("transcription", {}).get("text") if isinstance(payload.get("transcription"), dict) else None,
        payload.get("TranscriptionData", {}).get("Text") if isinstance(payload.get("TranscriptionData"), dict) else None,
    )
    return next((value.strip() for value in candidates if isinstance(value, str) and value.strip()), None)
