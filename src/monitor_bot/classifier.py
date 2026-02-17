"""Classify opportunities using Google Gemini with structured JSON output."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Callable

from google import genai
from google.genai import types

from monitor_bot.config import Settings
from monitor_bot.models import Classification, ClassifiedOpportunity, Opportunity

if TYPE_CHECKING:
    from monitor_bot.persistence import PipelineCache
    from monitor_bot.progress import ProgressTracker

logger = logging.getLogger(__name__)

# Seconds to sleep between individual Gemini calls (simple rate-limiter)
_RATE_LIMIT_DELAY = 1.0

_SYSTEM_PROMPT_TEMPLATE = """\
Sei un analista esperto di appalti pubblici e eventi IT. Il tuo compito è valutare se un \
bando / appalto pubblico / evento è rilevante per una specifica azienda IT.

IMPORTANTE: Rispondi SEMPRE in italiano.

## Profilo azienda
{company_profile}

## Istruzioni
Dati i dettagli di un'opportunità di appalto pubblico o di un evento, produci una valutazione JSON con:
- **relevance_score** (intero 1-10): quanto è rilevante questa opportunità per l'azienda.
- **category** (stringa, una tra: SAP, Data, AI, Cloud, Other): area di business corrispondente.
- **reason** (stringa, in italiano): spiegazione concisa (1-3 frasi) del punteggio assegnato.
- **key_requirements** (lista di stringhe, in italiano): i requisiti più importanti estratti dal bando, \
  oppure i temi/argomenti chiave se si tratta di un evento.
- **extracted_date** (stringa o null): la data rilevante estratta dal testo, in formato ISO (YYYY-MM-DD). \
  Per gli eventi: la data dell'evento (o la data di inizio se è un periodo). \
  Per i bandi/concorsi: la scadenza per la presentazione delle offerte. \
  Se non trovi alcuna data nel testo, restituisci null.

Sii rigoroso: assegna score >= 7 solo se l'opportunità corrisponde chiaramente alle competenze chiave. \
Score 4-6 per corrispondenze parziali. Score 1-3 per scarsa o nessuna corrispondenza.\
"""


class GeminiClassifier:
    """Classify a batch of opportunities via Gemini structured output."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model
        self._system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            company_profile=settings.company_profile or "Not specified.",
        )

    async def classify_all(
        self,
        opportunities: list[Opportunity],
        *,
        cache: PipelineCache | None = None,
        progress: ProgressTracker | None = None,
        on_classified: Callable[[ClassifiedOpportunity], None] | None = None,
    ) -> list[ClassifiedOpportunity]:
        """Classify every opportunity, persisting results incrementally.

        Args:
            opportunities: items to classify.
            cache: if provided, each result is saved immediately.
            progress: if provided, progress is reported after each item.
            on_classified: optional callback after each successful classification.
        """
        # Skip already-classified items (resume support)
        already_done: set[str] = set()
        results: list[ClassifiedOpportunity] = []
        if cache:
            already_done = cache.get_classified_ids()
            if already_done:
                results = cache.load_classified()
                logger.info(
                    "Classifier: resuming – %d already classified, %d remaining",
                    len(already_done),
                    len(opportunities) - len(already_done),
                )

        total = len(opportunities)
        for idx, opp in enumerate(opportunities, 1):
            if opp.id in already_done:
                if progress:
                    progress.update(idx, total, f"(cached) {opp.title[:40]}")
                continue

            if progress:
                progress.update(idx, total, opp.title[:40])

            logger.info("Classifying %d/%d: %s", idx, total, opp.title[:80])
            classification = await self._classify_one(opp)

            if classification:
                item = ClassifiedOpportunity(opportunity=opp, classification=classification)
                results.append(item)
                if cache:
                    cache.save_classified_one(item)
                if on_classified:
                    on_classified(item)

            # Simple rate-limiter
            if idx < total:
                await asyncio.sleep(_RATE_LIMIT_DELAY)

        return results

    async def _classify_one(self, opp: Opportunity) -> Classification | None:
        """Send a single opportunity to Gemini and parse the structured response."""
        user_prompt = self._build_user_prompt(opp)

        try:
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self._system_prompt,
                    response_mime_type="application/json",
                    response_schema=Classification,
                    temperature=0.2,
                ),
            )
            text = response.text
            if not text:
                logger.warning("Gemini returned empty response for %s", opp.id)
                return None

            data = json.loads(text)
            return Classification.model_validate(data)

        except Exception:
            logger.exception("Classification failed for %s", opp.id)
            return None

    @staticmethod
    def _build_user_prompt(opp: Opportunity) -> str:
        parts = [
            f"**Title:** {opp.title}",
            f"**Description:** {opp.description}" if opp.description else "",
            f"**Contracting authority:** {opp.contracting_authority}" if opp.contracting_authority else "",
            f"**Country:** {opp.country}" if opp.country else "",
            f"**CPV codes:** {', '.join(opp.cpv_codes)}" if opp.cpv_codes else "",
            f"**Estimated value:** {opp.estimated_value:,.0f} {opp.currency}" if opp.estimated_value else "",
            f"**Deadline:** {opp.deadline}" if opp.deadline else "",
            f"**Source:** {opp.source.value}",
        ]
        return "\n".join(p for p in parts if p)
