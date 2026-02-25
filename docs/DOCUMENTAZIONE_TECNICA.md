# Documentazione tecnica – Monitor Bot

## 1. Panoramica architetturale

Monitor Bot è un'applicazione Python asincrona che orchestra una pipeline di raccolta, classificazione e report. L'architettura è modulare: ogni collector è indipendente e il flusso è gestito da un orchestratore centrale.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           PIPELINE (main.py)                             │
├─────────────────────────────────────────────────────────────────────────┤
│  1. Collect   →  2. Deduplicate  →  3. Filter  →  4. Classify           │
│       │                  │               │              │                 │
│       ▼                  ▼               ▼              ▼                 │
│  ┌──────────┐      ┌──────────┐    ┌──────────┐   ┌─────────┐           │
│  │ TED      │      │ URL/     │    │ deadline │   │ Gemini  │           │
│  │ ANAC     │      │ title    │    │ >= today │   │ Flash   │           │
│  │ Events   │      │ dedup    │    │          │   │ Pro     │           │
│  │ WebEvents│      └──────────┘    └──────────┘   └─────────┘           │
│  │ WebTender│                                                            │
│  │ WebSearch│                                                            │
│  └──────────┘                                                            │
│                                                                          │
│  5. Enrich dates  →  5b. filter past  →  5c. dedup events  →  6. Notify  │
│       │                      │                    │                │      │
│       ▼                      ▼                    ▼                ▼      │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐  ┌────────┐  │
│  │ Fetch page  │      │ deadline    │      │ same date   │  │ HTML   │  │
│  │ + Gemini    │      │ < today?    │      │ same source │  │ report │  │
│  └─────────────┘      └─────────────┘      └─────────────┘  └────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Stack tecnologico

| Componente | Tecnologia |
|------------|------------|
| Linguaggio | Python 3.12+ |
| Package manager | uv (consigliato) / pip |
| HTTP client | httpx (async) |
| Parsing HTML | BeautifulSoup4 |
| Feed RSS/Atom | feedparser |
| AI | Google Gemini (google-genai) con Google Search grounding |
| Config | TOML (tomllib) + pydantic-settings |
| Validazione | Pydantic v2 |
| Template | Jinja2 |
| Web Framework | FastAPI (async) |
| Database | PostgreSQL + SQLAlchemy (async) |
| Frontend | Alpine.js + TailwindCSS + Vite |
| Voice AI | Gemini Live API (`gemini-2.5-flash-preview-native-audio-dialog`) |
| Autenticazione | Token-based (secrets.token_hex) |
| Deploy | Docker + Cloud Run (GCP) |

---

## 3. Struttura del codice

```
src/monitor_bot/
├── __init__.py
├── main.py              # CLI, arg parsing, orchestrazione pipeline
├── config.py            # Caricamento config.toml + .env
├── models.py            # Pydantic: Opportunity, Classification, ecc.
├── classifier.py        # GeminiClassifier – classificazione strutturata
├── date_enricher.py     # Fetch pagine + Gemini per estrarre date
├── notifier.py          # Report HTML, invio email
├── persistence.py       # PipelineCache – checkpoint su disco
├── progress.py          # ProgressTracker – barra progresso in italiano con icone
├── genai_client.py      # Factory client Google GenAI (Vertex AI / API key)
├── app.py               # FastAPI app factory + middleware auth
├── routes/
│   ├── api_agenda.py    # Agenda CRUD e valutazioni
│   ├── api_auth.py      # Login e validazione token
│   ├── api_chat.py      # Chatbot AI testuale
│   ├── api_voice.py     # Voice mode WebSocket (Gemini Live)
│   ├── api_dashboard.py # Dashboard stats
│   ├── api_sources.py   # CRUD link diretti
│   ├── api_queries.py   # CRUD ricerche internet
│   ├── api_runs.py      # Gestione esecuzioni pipeline
│   └── api_settings.py  # Impostazioni applicazione
└── collectors/
    ├── base.py          # BaseCollector (abstract)
    ├── ted.py           # TEDCollector – API TED
    ├── anac.py          # ANACCollector – ANAC OCDS
    ├── events.py        # EventsCollector – RSS/Atom
    ├── web_events.py    # WebEventsCollector – pagine HTML + Gemini
    ├── web_tenders.py   # WebTendersCollector – bandi regionali italiani
    └── web_search.py    # WebSearchCollector – ricerca Google + Gemini
```

---

## 4. Moduli principali

### 4.1 main.py

- **Entry point**: `cli()` → `run(args)`
- **Argomenti**: `--config`, `--test`, `--italia`, `--no-resume`
- **Pipeline**: `_collect` → `_deduplicate` → `_filter_future` → `classify_all` → `_patch_extracted_dates` → `enrich_missing_dates` → `_filter_past_after_enrichment` → `_dedup_events_by_date` → `notify`
- **Resume**: se `--no-resume` non è usato, usa `PipelineCache.find_latest_run()` e carica `collected.json`

### 4.2 config.py

- **Secrets**: `.env` via `pydantic_settings` (GEMINI_API_KEY, SMTP, ecc.)
- **Parametri**: `config.toml` via `tomllib`
- **Classe**: `Settings` – merge di secrets e parametri
- **Nuovi campi**: `enable_web_search`, `web_search_queries`, `web_search_max_per_query`

### 4.3 models.py

```python
# Modelli principali
Source          # TED | ANAC | EVENT | REGIONALE | WEB_SEARCH
OpportunityType # BANDO | CONCORSO | EVENTO
Category        # SAP | DATA | AI | CLOUD | OTHER
Opportunity      # id, title, description, deadline, source_url, ...
Classification  # relevance_score, category, reason, key_requirements, extracted_date
ClassifiedOpportunity  # opportunity + classification
```

### 4.3b db_models.py – AgendaItem

Tabella `agenda_items` per la gestione cross-run delle opportunita' con valutazione utente:

```python
AgendaItem:
  id, source_url (unique, chiave dedup),
  opportunity_id, title, description, contracting_authority,
  deadline, estimated_value, currency, country, source,
  opportunity_type, relevance_score, category, ai_reasoning, key_requirements,
  evaluation (Enum: INTERESTED | REJECTED, nullable),
  is_enrolled (Boolean), feedback_recommend (Boolean), feedback_return (Boolean),
  is_seen (Boolean), first_seen_at, evaluated_at, first_run_id (FK)
```

La tabella viene popolata automaticamente dopo ogni esecuzione pipeline (upsert per `source_url`). Gli elementi con `evaluation=REJECTED` o `deadline < today` vengono esclusi dalle ricerche future.

### 4.4 collectors/

**BaseCollector** (abstract):
- `collect() -> list[Opportunity]`

**TEDCollector**:
- API: `POST https://api.ted.europa.eu/v3/notices/search`
- Query: CPV, paesi, notice-type, date
- Parsing date: `deadline-receipt-tender-date-lot` (rimozione timezone `+01:00`)

**ANACCollector**:
- API: CKAN bulk JSON (OCDS)
- Streaming: parsing incrementale, filtri CPV e data

**EventsCollector**:
- Feed RSS/Atom via feedparser
- Filtri: keywords eventi, lookback su pubblicazione

**WebEventsCollector**:
- Crawling a due fasi: discovery link da seed pages + extraction dettagli
- Estrazione testo con BeautifulSoup
- Estrazione eventi con Gemini (JSON)

**WebTendersCollector**:
- Crawling a due fasi: discovery link bandi da portali regionali + extraction dettagli
- Seed pages: portali bandi delle Regioni italiane (Lombardia, Lazio, Emilia-Romagna, ecc.)
- Gemini filtra i link IT-rilevanti, poi estrae titolo, scadenza, dotazione, ente, requisiti
- **URL specifici**: i link nella pagina vengono passati a Gemini durante l'estrazione, in modo da ottenere l'URL della pagina di dettaglio del bando (non della pagina-elenco generica)
- Source: `Regionale`, OpportunityType: `Bando`
- Attivato con `web_tenders = true` in config (default: disattivato, attivo in `--italia`)

**WebSearchCollector** (nuovo):
- Usa Gemini con Google Search grounding per eseguire query di ricerca configurabili
- Due fasi:
  1. **Ricerca**: per ogni query configurata, invoca Gemini con `Tool(google_search=GoogleSearch())` per ottenere URL rilevanti
  2. **Estrazione**: per ogni URL trovato, fetch della pagina e invio a Gemini per estrarre informazioni strutturate (titolo, scadenza, ente, tipo, ecc.)
- Source: `WEB_SEARCH`, OpportunityType: determinato da Gemini (`BANDO` o `EVENTO`)
- Attivato con `web_search = true` in config
- Query configurabili in `[web_search].queries`
- `max_results_per_query`: limite risultati per ogni query (default: 5)
- Rate limiting: 1.5s tra ogni richiesta

### 4.5 classifier.py

- **GeminiClassifier**: `classify_all(opportunities, cache, progress)`
- **Prompt**: system prompt con profilo azienda + istruzioni per JSON
- **Output**: `Classification` (Pydantic) con `response_schema`
- **Structured output**: `response_mime_type="application/json"`

### 4.6 date_enricher.py

- **enrich_missing_dates(classified, settings, progress)**
- Per ogni opportunità senza `deadline` e con `source_url`:
  - Fetch pagina
  - Estrazione testo HTML
  - Invio a Gemini con prompt dedicato all'estrazione date
  - Parsing JSON e patch del campo `deadline`
- Aggiorna la barra di progresso item per item (se `progress` è fornito)

### 4.7 persistence.py

- **PipelineCache**: directory `output/.cache/run_YYYYMMDD_HHMMSS/`
- **File**: `collected.json`, `classified.json` (JSONL), `classified_ids.json`, `metadata.json`
- **find_latest_run()**: ritorna la cache più recente

### 4.8 notifier.py

- **Notifier.notify(classified, total_analyzed, elapsed_seconds)**
- Filtra per `relevance_threshold`
- Render Jinja2 con `templates/report.html`
- Salvataggio in `output/report_*.html` o invio email

### 4.9 Web Application (routes/)

**api_auth.py**: Autenticazione token-based
- `POST /api/auth/login`: validazione credenziali, generazione token
- `GET /api/auth/me`: verifica sessione corrente
- Token in-memory con scadenza

**api_chat.py**: Chatbot AI testuale
- `POST /api/chat/message`: invio messaggio con contesto esecuzione
- System prompt dinamico con dati app (settings, fonti, query, storico run, risultati)
- Supporto azione `[AVVIA_RICERCA]` per trigger pipeline da chat

**api_voice.py**: Voice mode (Gemini Live)
- `WS /api/chat/voice?token=...&run_id=...`: WebSocket bidirezionale
- Proxy tra browser e Gemini Live API
- Audio: PCM 16-bit 16kHz (input) / 24kHz (output)
- Autenticazione via query parameter (WebSocket non supporta header)
- 3 task asincroni: relay client->Gemini, relay Gemini->client, gestione lifecycle
- Voice name: "Aoede", lingua: italiano

**api_agenda.py**: Gestione Agenda con valutazione opportunita', iscrizione eventi e feedback.
- `GET /api/agenda`: lista elementi attivi con filtri (tab, type, category, sort, search, paginazione)
- `GET /api/agenda/stats`: contatori per badge notifica (unseen_count, pending_count, expiring_count)
- `GET /api/agenda/expiring?days=N`: elementi in scadenza entro N giorni
- `GET /api/agenda/past-events`: eventi passati con iscrizione per feedback
- `PATCH /api/agenda/{id}/evaluate`: valutazione (interested/rejected)
- `PATCH /api/agenda/{id}/enroll`: toggle iscrizione evento
- `PATCH /api/agenda/{id}/feedback`: feedback post-evento
- `POST /api/agenda/mark-seen`: segna elementi come visti

**api_dashboard.py / api_sources.py / api_queries.py / api_runs.py / api_settings.py**: CRUD e business logic per le rispettive risorse.

### 4.10 Frontend

**main.js**: Setup Alpine.js, autenticazione guard, onboarding carousel, navbar
- Auth guard: redirect a `/login.html` se token assente
- Onboarding: carousel 4 slide post-login con persistenza in localStorage
- Navbar: links con icone SVG, layout responsive desktop/mobile

**chatbot.js**: Componente chatbot
- Chat testuale con persistenza localStorage
- Voice mode via WebSocket: cattura microfono (getUserMedia), invio PCM 16kHz, playback audio risposta
- Overlay fullscreen durante voice mode con indicatore di stato

---

## 5. Flusso dati

```
Collectors (TED, ANAC, Events, WebEvents, WebTenders, WebSearch)
    │
    ▼
list[Opportunity]  (raw)
    │
    ▼
_deduplicate (URL, title)
    │
    ▼
_filter_future (deadline >= today, eventi sempre)
    │
    ▼
classifier.classify_all() → list[ClassifiedOpportunity]
    │
    ▼
_patch_extracted_dates (extracted_date → deadline)
    │
    ▼
enrich_missing_dates (fetch page + Gemini; TED XML fallback)
    │
    ▼
_filter_past_after_enrichment (rimuove item con deadline < today)
    │
    ▼
_dedup_events_by_date (fuzzy matching titoli per stessa data)
    │
    ▼
notifier.notify() → HTML report (con tempo di esecuzione)
```

---

## 6. Configurazione tecnica

### 6.1 Struttura file di configurazione

Il progetto usa tre file TOML, tutti strutturati con commenti guida:

| File | Uso |
|------|-----|
| `config.toml` | Configurazione produzione (EMEA) |
| `config.italia.toml` | Configurazione solo Italia |
| `config.test.toml` | Configurazione test rapido |

### 6.2 Sezioni principali di config.toml

```toml
[gemini]
model = "gemini-3-flash-preview"

[classification]
relevance_threshold = 6

[scope]
lookback_days = 7
max_results = 0
cpv_codes = ["72", "48", "62", "64.2"]
countries = ["IT", "DE", ...]

[collectors]
ted = true
anac = true
events = true
web_events = true
web_tenders = false       # attivo in modalità Italia
web_search = true         # ricerca web Google

[events]
feeds = ["https://...", ...]
web_pages = ["https://www.aiweek.it/", ...]

[regional_tenders]          # solo con web_tenders = true
web_pages = ["https://...", ...]

[web_search]                # solo con web_search = true
queries = [
    "bandi innovazione digitale Italia 2026",
    "eventi conferenze AI Europa 2026",
    # ...
]
max_results_per_query = 5

[company]
profile = "..."
```

### 6.3 Modalità Italia (config.italia.toml)

```bash
uv run monitor-bot --italia --no-resume
```

Perimetro esclusivamente italiano:

| Collector | Fonte |
|-----------|-------|
| TED | Solo `countries = ["IT"]` |
| ANAC | Bandi nazionali italiani |
| WebTenders | Portali regionali: Lombardia, Lazio, Emilia-Romagna, Piemonte, Veneto + Italia Domani (PNRR) |
| Events RSS | ForumPA, AgID, Innovazione Italia |
| WebEvents | AI Week, Google Cloud Events IT, Microsoft AI Tour |
| WebSearch | Query focalizzate su bandi/eventi IT in Italia |

### 6.4 .env

```
GEMINI_API_KEY=...
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
```

---

## 7. API esterne

| API | Endpoint | Autenticazione |
|-----|----------|----------------|
| TED | `POST https://api.ted.europa.eu/v3/notices/search` | Nessuna |
| ANAC | CKAN bulk JSON (URL da portale) | Nessuna |
| Gemini | `google.genai.models.generate_content` | API key |
| Google Search | Via Gemini grounding (`Tool(google_search=GoogleSearch())`) | Stessa API key Gemini |

---

## 8. Gestione errori e resilienza

- **Collectors**: `asyncio.gather(..., return_exceptions=True)` – un collector fallito non blocca gli altri
- **Gemini**: retry implicito; rate limit con `asyncio.sleep`
- **Resume**: checkpoint dopo collect e durante classificazione
- **TED**: retry su 429/5xx con backoff
- **ANAC**: streaming con fallback su download troncati
- **WebSearch**: errori di singole query/pagine non bloccano le altre

---

## 9. Estensibilità

### Aggiungere un nuovo collector

1. Creare `collectors/nuovo.py` con classe che estende `BaseCollector`
2. Implementare `async def collect() -> list[Opportunity]`
3. Registrare in `main.py` in `_collect()` e in `config.py` per il flag di abilitazione

### Aggiungere nuove fonti (senza codice)

- **Feed RSS**: aggiungere URL in `[events].feeds` nel config TOML
- **Pagine web**: aggiungere URL in `[events].web_pages` nel config TOML
- **Bandi regionali**: aggiungere URL in `[regional_tenders].web_pages`
- **Query di ricerca**: aggiungere stringa in `[web_search].queries`

### Aggiungere un nuovo campo a Opportunity

1. Aggiornare `models.Opportunity`
2. Aggiornare i collector che popolano il campo
3. Aggiornare `templates/report.html` se necessario

### Cambiare il formato del report

- Modificare `templates/report.html` (Jinja2)
- Variabili passate: `opportunities`, `total_analyzed`, `relevant_count`, `threshold`, `category_counts`, `type_counts`, `today`, `generated_at`, `lookback_days`, `elapsed_display`
- Filtri client-side JavaScript: tipo, data (7/30/90gg + personalizzato), fonte/ente, categoria
- Attributi `data-*` su ogni card: `data-type`, `data-deadline`, `data-authority`, `data-category`

---

## 10. Testing e sviluppo

### 10.1 Modalità test

```bash
uv run monitor-bot --test --no-resume
```

Usa `config.test.toml` con scope ridotto per verificare la pipeline end-to-end in ~1-2 minuti:

- **Collectors**: TED (max 5 risultati, solo Italia) + 1 feed RSS (ForumPA) + 1 seed page WebEvents (AI Week) + 1 query WebSearch
- **ANAC**: disabilitato (lento, non necessario per verifiche rapide)
- **Soglia rilevanza**: 4 (più bassa per generare più risultati nel report di test)
- **Lookback**: 3 giorni

`--no-resume` è fondamentale per evitare che il test carichi dalla cache di un run precedente (in produzione con scope EMEA completo), falsando i risultati.

### 10.2 Sviluppo

```bash
# Installazione dipendenze
uv sync

# Run completo in produzione
uv run monitor-bot

# Run da zero (ignora cache)
uv run monitor-bot --no-resume

# Solo Italia
uv run monitor-bot --italia --no-resume

# Config personalizzata
uv run monitor-bot --config mio_config.toml
```

---

## 11. Dipendenze (pyproject.toml)

```
httpx>=0.28
pydantic>=2.10
pydantic-settings>=2.7
google-genai>=1.51
jinja2>=3.1
python-dotenv>=1.1
feedparser>=6.0.12
beautifulsoup4>=4.12
```
