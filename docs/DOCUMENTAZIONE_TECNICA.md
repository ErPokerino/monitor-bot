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
| Database | PostgreSQL + SQLAlchemy (async) + asyncpg |
| Frontend | Alpine.js + TailwindCSS + Vite |
| Voice AI | Gemini Live API (`gemini-live-2.5-flash-native-audio`) |
| Autenticazione | Sessioni DB-backed + Argon2 + RBAC (`admin | user`) + OIDC Google (Cloud Scheduler) |
| Timezone | Europe/Rome (zoneinfo) per tutti i timestamp |
| Deploy | Docker multi-stage + Cloud Run (GCP) + Cloud Build CI/CD |

---

## 3. Struttura del codice

```
src/monitor_bot/
├── __init__.py
├── app.py               # FastAPI app factory + middleware auth
├── auth.py              # Password hashing, session token, principal/RBAC
├── database.py          # SQLAlchemy async engine + migrazioni leggere runtime
├── db_models.py         # ORM models (multi-user)
├── schemas.py           # Pydantic schemas API
├── seed.py              # Bootstrap admin e backfill dati legacy
├── job.py               # Entry point Cloud Run Job
├── main.py              # CLI, arg parsing, orchestrazione pipeline
├── config.py            # Caricamento config.toml + .env
├── models.py            # Pydantic: Opportunity, Classification, ecc.
├── classifier.py        # GeminiClassifier – classificazione strutturata
├── date_enricher.py     # Fetch pagine + Gemini per estrarre date
├── notifier.py          # Report HTML, invio email
├── persistence.py       # PipelineCache – checkpoint su disco
├── progress.py          # ProgressTracker – barra progresso in italiano con icone
├── genai_client.py      # Factory client Google GenAI (Vertex AI / API key)
├── routes/
│   ├── api_agenda.py    # Agenda CRUD, share, notifiche
│   ├── api_auth.py      # Login/logout/me + directory utenti per share picker
│   ├── api_admin.py     # Gestione utenti admin (create/activate/deactivate/delete)
│   ├── api_chat.py      # Chatbot AI testuale
│   ├── api_voice.py     # Voice mode WebSocket (Gemini Live)
│   ├── api_dashboard.py # Dashboard stats
│   ├── api_sources.py   # CRUD link diretti
│   ├── api_queries.py   # CRUD ricerche internet
│   ├── api_runs.py      # Gestione esecuzioni pipeline
│   └── api_settings.py  # Impostazioni applicazione
├── services/
│   ├── agenda.py        # Isolamento dati per owner + share + notifiche
│   ├── users.py         # Lifecycle utenti + ricerca directory
│   ├── settings.py      # Settings user/system + sync scheduler GCP (pause/resume)
│   ├── runs.py          # Run service e persistenza risultati
│   ├── sources.py       # CRUD fonti con owner scope
│   ├── queries.py       # CRUD query con owner scope
│   ├── audit.py         # Audit log azioni sensibili
│   └── email.py         # Notifiche email pipeline
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
EventFormat     # IN_PRESENZA | STREAMING | ON_DEMAND
EventCost       # GRATUITO | A_PAGAMENTO | SU_INVITO
Opportunity      # id, title, description, deadline, source_url, ...
Classification  # relevance_score, category, reason, key_requirements, extracted_date,
                # event_format, event_cost, city, sector
ClassifiedOpportunity  # opportunity + classification
```

### 4.3b db_models.py – schema multi-user

Il modello dati e' multi-tenant logico: ogni record applicativo e' associato a un proprietario (`owner_user_id`) e le operazioni backend applicano sempre owner scoping.

Tabelle identity e sicurezza:

```python
User:
  id, username (unique), display_name, password_hash (Argon2),
  role (admin|user), is_active, must_reset_password,
  failed_login_attempts, locked_until, last_login_at, created_at, updated_at

AuthSession:
  id, user_id (FK), token_hash (sha256, unique), created_at, expires_at,
  revoked_at, last_seen_at

AuditLog:
  id, actor_user_id (FK nullable), action, target_type, target_id, payload_json, created_at

UserSetting:
  id, user_id (FK), key, value, UNIQUE(user_id, key)
```

Tabelle dominio con ownership:

```python
MonitoredSource.owner_user_id
SearchQuery.owner_user_id
SearchRun.owner_user_id
SearchResult.owner_user_id
AgendaItem.owner_user_id
```

Vincoli di unicita' per owner (evita collisioni cross-user):

```python
UNIQUE(owner_user_id, monitored_sources.url)
UNIQUE(owner_user_id, search_queries.query_text)
UNIQUE(owner_user_id, agenda_items.source_url)
```

Condivisione agenda:

```python
AgendaShare:
  id, agenda_item_id (FK), sender_user_id (FK), recipient_user_id (FK),
  note, is_seen, created_at,
  UNIQUE(agenda_item_id, sender_user_id, recipient_user_id)
```

La tabella `agenda_items` mantiene i metadati di opportunita' (deadline, score, categoria, campi evento, valutazione, iscrizione, feedback, seen state) e viene popolata automaticamente post-run. Gli elementi `REJECTED` o scaduti sono esclusi dai run successivi per lo stesso utente.

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
- **Campi evento**: per le opportunita' di tipo Evento, il classificatore estrae anche `event_format` (In presenza/Streaming/On demand), `event_cost` (Gratuito/A pagamento/Su invito), `city` (citta' dell'evento) e `sector` (settore di mercato)

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

**api_auth.py**: autenticazione e directory utenti
- `POST /api/auth/login`: verifica password Argon2, lockout anti brute-force, issue sessione DB
- `POST /api/auth/logout`: revoca sessione corrente
- `GET /api/auth/me`: principal corrente (`username`, `display_name`, `role`)
- `GET /api/auth/users?q=&limit=`: directory utenti attivi (esclude caller), usata da share picker

**api_admin.py**: operazioni admin-only
- `GET /api/admin/users`: lista utenti (attivi + disattivati)
- `POST /api/admin/users`: creazione utente con ruolo
- `DELETE /api/admin/users/{id}`: disattivazione (revoca tutte le sessioni)
- `POST /api/admin/users/{id}/activate`: riattivazione utente
- `DELETE /api/admin/users/{id}/hard`: eliminazione definitiva con cleanup dati correlati
- `GET /api/admin/overview`: KPI utenti/sessioni/run

**api_agenda.py**: agenda, condivisione e notifiche
- `GET /api/agenda`: lista owner-scoped con filtri (`pending`, `interested`, `past_events`)
- `GET /api/agenda/shared`: elementi condivisi con l'utente corrente
- `POST /api/agenda/{id}/share`: condivisione verso altro utente attivo
- `GET /api/agenda/notifications`: payload aggregato notifiche (`agenda_unseen`, `shared_unseen`)
- `GET /api/agenda/stats`: badge counters (`unseen_count`, `shared_unseen_count`, ...)
- `POST /api/agenda/mark-seen` e `POST /api/agenda/shared/mark-seen`: mark read
- `PATCH /api/agenda/{id}/evaluate|enroll|feedback`: workflow valutazione e post-evento

**api_chat.py**: chatbot AI contestuale al principal
- system prompt arricchito con contesto utente/ruolo (admin capabilities incluse)
- stato conversazione isolato per utente
- supporto action marker `[AVVIA_RICERCA]`

**api_voice.py**: voice mode (Gemini Live)
- WebSocket bidirezionale browser <-> backend <-> Gemini Live
- autenticazione via token inviato come primo messaggio WS (non query string)
- audio PCM (input 16kHz / output 24kHz), relay asincrono in 3 task

**api_settings.py**: settings user/system
- update per-user settings sempre consentito
- update system settings consentito solo ad admin
- sync schedulazione GCP: update cron e gestione `pause/resume` in base a `scheduler_enabled`

**api_runs.py**: run management
- avvio/stop run owner-scoped (admin puo' vedere tutto)
- progresso via polling `GET /api/runs/{id}/progress`
- trigger OIDC su `/api/runs/start` supportato per Cloud Scheduler

### 4.10 Frontend

**main.js**: setup Alpine, auth guard, navbar, notification bell
- auth guard + refresh `or-user` da `/api/auth/me`
- navbar role-aware (link Admin visibile solo a `role=admin`)
- notification bell con dropdown: lista notifiche agenda/shared, mark-all-seen, routing contestuale

**agenda.js**: agenda UX e condivisione
- tabs `pending|interested|shared|past_events`
- share modal con user picker, ricerca live/debounce e nota opzionale
- isolamento local state per filtri/sorting e mark shared seen

**config.js**: configurazioni
- separazione chiavi user/system lato payload
- toggle scheduler on/off (`scheduler_enabled`) per admin

**admin.js**: user lifecycle
- create user, deactivate, activate, hard delete
- feedback UI con stato azioni in corso

**chatbot.js**:
- storage chat key user-scoped (`or-chat-{username}`)
- welcome e contesto per utente corrente
- voice mode allineato al nuovo handshake token-first su WebSocket

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
model = "gemini-2.5-flash"

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

## 11. Gestione fuso orario

Tutti i timestamp dell'applicazione usano il fuso orario `Europe/Rome` (via `zoneinfo.ZoneInfo`). La funzione `_now_rome()` in `db_models.py` restituisce `datetime.now(Europe/Rome)` come datetime naive (senza tzinfo) per compatibilità con il database.

Punti di applicazione:
- **DB models**: `started_at`, `completed_at`, `created_at`, `updated_at` usano `_now_rome` come default
- **Services**: `runs.py` (complete_run), `email.py` (timestamp report), `notifier.py` (report HTML), `persistence.py` (cache directory)
- **Cleanup**: `app.py` (orphaned runs) usa `_now_rome()`

Cloud Run gira in UTC; senza questa configurazione esplicita i timestamp risulterebbero sfasati di 1-2 ore rispetto all'orario italiano.

---

## 12. Infrastruttura GCP (Terraform)

L'infrastruttura è definita in `infra/` con Terraform (state su GCS):

| Risorsa | Servizio GCP | Dettagli |
|---------|-------------|----------|
| Web app | Cloud Run Service | 1-2 istanze, 1 CPU / 512Mi |
| Pipeline batch | Cloud Run Job | 2 CPU / 1Gi, timeout 1h |
| Database | Cloud SQL PostgreSQL 15 | Istanza zonale |
| Schedulazione | Cloud Scheduler | Cron configurabile, tz Europe/Rome |
| CI/CD | Cloud Build | Trigger su push `main` via GitHub |
| Registry | Artifact Registry (Docker) | Immagini container |
| Storage | Cloud Storage | Cache/dati, retention 90gg |
| Secrets | Secret Manager | Password DB, SMTP |
| Networking | VPC Access Connector | Cloud Run <-> Cloud SQL |

Service account dedicati: `or-runtime` (Service), `or-pipeline` (Job), `or-scheduler` (Scheduler).

Il Cloud Scheduler invia una POST a `/api/runs/start` con token OIDC, che il middleware auth valida tramite `google.oauth2.id_token.verify_oauth2_token()`.

---

## 13. Dipendenze (pyproject.toml)

```
httpx>=0.28
pydantic>=2.10
pydantic-settings>=2.7
google-genai>=1.51
google-auth>=2.0
jinja2>=3.1
python-dotenv>=1.1
feedparser>=6.0.12
beautifulsoup4>=4.12
fastapi>=0.115
uvicorn[standard]>=0.34
sqlalchemy[asyncio]>=2.0
asyncpg>=0.30
aiosqlite>=0.21
python-multipart>=0.0.18
```
