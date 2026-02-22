"""REST API routes for the Opportunity Bot chatbot."""

from __future__ import annotations

import asyncio
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from google.genai import types

from monitor_bot.config import Settings
from monitor_bot.database import get_session
from monitor_bot.genai_client import create_genai_client
from monitor_bot.services import queries as query_svc
from monitor_bot.services import runs as run_svc
from monitor_bot.services import settings as settings_svc
from monitor_bot.services import sources as source_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

_history: list[dict[str, str]] = []
_loaded_run_id: int | None = None

_APP_CONTEXT = (
    "Sei **Opportunity Bot**, l'assistente AI dell'applicazione **Opportunity Radar**.\n\n"
    "## Cosa fa Opportunity Radar\n"
    "Opportunity Radar e' un'applicazione enterprise che monitora e analizza bandi di gara pubblici, "
    "eventi e opportunita' di finanziamento. Raccoglie dati da fonti configurate (feed RSS, pagine web, "
    "portali bandi) e query di ricerca internet, li classifica tramite AI in base al profilo aziendale "
    "dell'utente e produce punteggi di rilevanza (1-10).\n\n"
    "Le sezioni principali dell'app sono:\n"
    "- **Dashboard**: panoramica con statistiche e storico esecuzioni\n"
    "- **Configurazioni**: gestione link diretti (fonti), ricerche internet e impostazioni generali\n"
    "- **Esegui**: avvio manuale della pipeline di raccolta e analisi\n"
    "- **Opportunity Bot**: questo chatbot (tu)\n\n"
    "L'app supporta anche esecuzioni programmate (batch job settimanale) con notifica email.\n"
)

_INSTRUCTIONS = (
    "## Istruzioni\n"
    "- Rispondi SEMPRE in italiano\n"
    "- Aiuta l'utente a comprendere i risultati, le impostazioni e il funzionamento dell'app\n"
    "- Quando i risultati di un'esecuzione sono caricati nel contesto, rispondi a domande "
    "specifiche su singoli bandi, eventi o opportunita' facendo riferimento ai dati concreti\n"
    "- Sii preciso e cita dati specifici quando rispondi\n"
    "- Se l'utente chiede di un risultato specifico, fornisci titolo, score, categoria, "
    "ragionamento AI, requisiti chiave e link sorgente\n"
    "- Usa un tono professionale ma amichevole\n"
    "- Formatta le risposte in modo chiaro usando elenchi puntati quando appropriato\n"
    "\n## Azione: avvio nuova ricerca\n"
    "Se l'utente chiede esplicitamente di avviare una nuova ricerca, lanciare la pipeline, "
    "eseguire un nuovo report o creare un nuovo report, DEVI:\n"
    "1. Riepilogare brevemente le configurazioni attive (fonti e ricerche attive)\n"
    "2. Aggiungere la stringa esatta [AVVIA_RICERCA] come ULTIMA riga della tua risposta\n"
    "NON aggiungere [AVVIA_RICERCA] se l'utente non ha chiesto esplicitamente di avviare "
    "una ricerca. La stringa [AVVIA_RICERCA] serve a mostrare all'utente un pulsante di conferma.\n"
)

_ACTION_MARKER = "[AVVIA_RICERCA]"


class ChatRequest(BaseModel):
    message: str
    run_id: int | None = None


class ChatResponse(BaseModel):
    reply: str
    run_id: int | None = None
    action: str | None = None


def _format_settings(all_settings: dict[str, str]) -> str:
    lines = ["## Profilo azienda e impostazioni correnti"]
    if all_settings.get("company_name"):
        lines.append(f"- **Azienda**: {all_settings['company_name']}")
    if all_settings.get("company_sector"):
        lines.append(f"- **Settore**: {all_settings['company_sector']}")
    if all_settings.get("company_competencies"):
        lines.append(f"- **Competenze**: {all_settings['company_competencies']}")
    bmin = all_settings.get("company_budget_min", "")
    bmax = all_settings.get("company_budget_max", "")
    if bmin or bmax:
        lines.append(f"- **Budget target**: {bmin} - {bmax} EUR")
    if all_settings.get("company_regions"):
        lines.append(f"- **Regioni**: {all_settings['company_regions']}")
    if all_settings.get("company_description"):
        lines.append(f"- **Descrizione**: {all_settings['company_description'][:500]}")
    lines.append(f"- **Soglia rilevanza**: {all_settings.get('relevance_threshold', '6')}")
    sday = all_settings.get("scheduler_day", "1")
    shour = all_settings.get("scheduler_hour", "2")
    day_names = {"0": "Domenica", "1": "Lunedi", "2": "Martedi", "3": "Mercoledi",
                 "4": "Giovedi", "5": "Venerdi", "6": "Sabato"}
    lines.append(f"- **Esecuzione programmata**: {day_names.get(sday, sday)} ore {shour}:00")
    return "\n".join(lines)


def _format_sources(sources: list) -> str:
    if not sources:
        return "## Fonti configurate\nNessuna fonte configurata."
    lines = [f"## Fonti configurate ({len(sources)} totali)"]
    for s in sources:
        status = "attiva" if s.is_active else "disattivata"
        lines.append(f"- [{status}] {s.name} ({s.source_type.value}) - {s.category.value}")
    return "\n".join(lines)


def _format_queries(queries: list) -> str:
    if not queries:
        return "## Ricerche internet configurate\nNessuna ricerca configurata."
    lines = [f"## Ricerche internet configurate ({len(queries)} totali)"]
    for q in queries:
        status = "attiva" if q.is_active else "disattivata"
        lines.append(f"- [{status}] \"{q.query_text}\" ({q.category.value}, max {q.max_results} risultati)")
    return "\n".join(lines)


def _format_run_history(runs: list) -> str:
    if not runs:
        return "## Storico esecuzioni\nNessuna esecuzione ancora effettuata."
    lines = [f"## Storico esecuzioni (ultime {len(runs)})"]
    for r in runs:
        started = r.started_at.strftime("%d/%m/%Y %H:%M") if r.started_at else "?"
        elapsed = ""
        if r.elapsed_seconds:
            m = int(r.elapsed_seconds) // 60
            s = int(r.elapsed_seconds) % 60
            elapsed = f" - durata {m}m{s}s"
        lines.append(
            f"- **Run #{r.id}** ({started}) - stato: {r.status.value} - "
            f"raccolte: {r.total_collected}, classificate: {r.total_classified}, "
            f"rilevanti: {r.total_relevant}{elapsed}"
        )
    return "\n".join(lines)


def _format_run_results(run, results: list) -> str:
    started = run.started_at.strftime("%d/%m/%Y %H:%M") if run.started_at else "?"
    lines = [
        f"## RISULTATI ESECUZIONE #{run.id} (selezionata dall'utente)",
        f"Data: {started} | Stato: {run.status.value} | "
        f"Raccolte: {run.total_collected} | Classificate: {run.total_classified} | "
        f"Rilevanti: {run.total_relevant}",
        "",
        "### Dettaglio risultati",
    ]
    sorted_results = sorted(results, key=lambda r: r.relevance_score, reverse=True)
    for i, r in enumerate(sorted_results, 1):
        reqs = ""
        if r.key_requirements:
            try:
                req_list = json.loads(r.key_requirements)
                if req_list:
                    reqs = " | Requisiti: " + "; ".join(req_list[:5])
            except (json.JSONDecodeError, TypeError):
                pass
        deadline_str = r.deadline.strftime("%d/%m/%Y") if r.deadline else "N/D"
        value_str = ""
        if r.estimated_value:
            value_str = f" | Valore: {r.estimated_value:,.0f} {r.currency}"
        lines.append(
            f"\n**{i}. {r.title}**\n"
            f"   Tipo: {r.opportunity_type} | Categoria: {r.category} | "
            f"Score: {r.relevance_score}/10 | Scadenza: {deadline_str}{value_str}\n"
            f"   Ente: {r.contracting_authority or 'N/D'} | Paese: {r.country or 'N/D'}\n"
            f"   Ragionamento AI: {r.ai_reasoning}{reqs}\n"
            f"   Link: {r.source_url}"
        )
    return "\n".join(lines)


async def _build_system_prompt(db: AsyncSession, run_id: int | None) -> str:
    all_settings = await settings_svc.get_all(db)
    sources = await source_svc.list_sources(db)
    queries = await query_svc.list_queries(db)
    runs = await run_svc.list_runs(db, limit=15)

    sections = [_APP_CONTEXT]
    sections.append(_format_settings(all_settings))
    sections.append(_format_sources(sources))
    sections.append(_format_queries(queries))
    sections.append(_format_run_history(runs))

    if run_id:
        run = await run_svc.get_run(db, run_id)
        if run and run.results:
            sections.append(_format_run_results(run, run.results))
        elif run:
            sections.append(f"\n## Esecuzione #{run_id} selezionata\nQuesta esecuzione non ha risultati.")

    sections.append(_INSTRUCTIONS)
    return "\n\n".join(sections)


@router.post("/message", response_model=ChatResponse)
async def send_message(
    req: ChatRequest,
    db: AsyncSession = Depends(get_session),
):
    global _loaded_run_id, _history

    if req.run_id != _loaded_run_id:
        _history = []
        _loaded_run_id = req.run_id

    system_prompt = await _build_system_prompt(db, _loaded_run_id)

    _history.append({"role": "user", "content": req.message})

    contents = []
    for m in _history:
        contents.append(
            types.Content(role=m["role"], parts=[types.Part.from_text(text=m["content"])])
        )

    try:
        settings = Settings()
        client = create_genai_client(settings)

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.7,
                max_output_tokens=4096,
            ),
        )

        reply = response.text or "Mi dispiace, non sono riuscito a generare una risposta."
    except Exception:
        logger.exception("Chat generation failed")
        _history.pop()
        raise HTTPException(status_code=502, detail="Errore nella generazione della risposta AI")

    action = None
    if _ACTION_MARKER in reply:
        reply = reply.replace(_ACTION_MARKER, "").rstrip()
        action = "start_run"

    _history.append({"role": "model", "content": reply})

    if len(_history) > 40:
        _history[:] = _history[-30:]

    return ChatResponse(reply=reply, run_id=_loaded_run_id, action=action)


@router.delete("/history")
async def reset_history():
    global _history, _loaded_run_id
    _history = []
    _loaded_run_id = None
    return {"status": "ok"}


@router.get("/status")
async def chat_status():
    return {
        "message_count": len(_history),
        "loaded_run_id": _loaded_run_id,
    }
