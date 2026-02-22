"""WebSocket endpoint for Gemini Live native audio voice conversations."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from google.genai import types

from google import genai

from monitor_bot.config import Settings
from monitor_bot.database import async_session
from monitor_bot.routes.api_auth import validate_token
from monitor_bot.routes.api_chat import _build_system_prompt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["voice"])

LIVE_MODEL = "gemini-live-2.5-flash-native-audio"
LIVE_REGION = "europe-west4"


@router.websocket("/voice")
async def voice_session(
    ws: WebSocket,
    token: str = Query(...),
    run_id: int | None = Query(default=None),
):
    if not validate_token(token):
        await ws.close(code=4001, reason="Invalid token")
        return

    await ws.accept()
    logger.info("Voice session opened (run_id=%s)", run_id)

    settings = Settings()
    if settings.gcp_project_id:
        client = genai.Client(
            vertexai=True,
            project=settings.gcp_project_id,
            location=LIVE_REGION,
        )
    elif settings.gemini_api_key:
        client = genai.Client(api_key=settings.gemini_api_key)
    else:
        await ws.send_text(json.dumps({"type": "error", "message": "AI client not configured"}))
        await ws.close()
        return

    async with async_session() as db:
        system_prompt = await _build_system_prompt(db, run_id)

    voice_instructions = (
        system_prompt
        + "\n\n## Istruzioni aggiuntive per modalita' vocale\n"
        "Stai parlando con l'utente in tempo reale tramite audio. "
        "Rispondi in modo conciso e naturale, come in una conversazione parlata. "
        "Evita formattazione Markdown, elenchi puntati complessi o testo lungo. "
        "Vai dritto al punto. Parla SEMPRE in italiano."
    )

    try:
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=voice_instructions)]
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede",
                    )
                )
            ),
        )

        async with client.aio.live.connect(
            model=LIVE_MODEL, config=config
        ) as session:
            await ws.send_text(json.dumps({"type": "connected"}))

            async def _relay_client_to_gemini():
                """Read audio from browser WebSocket, forward to Gemini."""
                try:
                    while True:
                        data = await ws.receive()
                        if data.get("type") == "websocket.disconnect":
                            break
                        if "bytes" in data and data["bytes"]:
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=data["bytes"],
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        elif "text" in data and data["text"]:
                            msg = json.loads(data["text"])
                            if msg.get("type") == "close":
                                break
                except WebSocketDisconnect:
                    pass
                except Exception:
                    logger.debug("Client relay ended", exc_info=True)

            async def _relay_gemini_to_client():
                """Read responses from Gemini, forward audio/text to browser."""
                try:
                    while True:
                        async for response in session.receive():
                            server_content = response.server_content
                            if server_content is None:
                                continue

                            if server_content.model_turn:
                                for part in server_content.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        await ws.send_bytes(part.inline_data.data)
                                    elif part.text:
                                        await ws.send_text(json.dumps({
                                            "type": "transcript",
                                            "role": "assistant",
                                            "text": part.text,
                                        }))

                            if server_content.turn_complete:
                                await ws.send_text(json.dumps({
                                    "type": "turn_complete",
                                }))

                except WebSocketDisconnect:
                    pass
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.debug("Gemini relay ended", exc_info=True)

            client_task = asyncio.create_task(_relay_client_to_gemini())
            gemini_task = asyncio.create_task(_relay_gemini_to_client())

            done, pending = await asyncio.wait(
                [client_task, gemini_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    except WebSocketDisconnect:
        logger.info("Voice session disconnected normally")
    except Exception:
        logger.exception("Voice session error")
        try:
            await ws.send_text(json.dumps({"type": "error", "message": "Errore nella sessione vocale"}))
        except Exception:
            pass
    finally:
        logger.info("Voice session closed")
        try:
            await ws.close()
        except Exception:
            pass
