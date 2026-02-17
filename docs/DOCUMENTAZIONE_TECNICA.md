# Documentazione tecnica – Monitor Bot

## 1. Panoramica architetturale

Monitor Bot è un’applicazione Python asincrona che orchestra una pipeline di raccolta, classificazione e report. L’architettura è modulare: ogni collector è indipendente e il flusso è gestito da un orchestratore centrale.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           PIPELINE (main.py)                             │
├─────────────────────────────────────────────────────────────────────────┤
│  1. Collect   →  2. Deduplicate  →  3. Filter  →  4. Classify           │
│       │                  │               │              │                 │
│       ▼                  ▼               ▼              ▼                 │
│  ┌─────────┐      ┌──────────┐    ┌──────────┐   ┌─────────┐            │
│  │ TED     │      │ URL/     │    │ deadline │   │ Gemini  │            │
│  │ ANAC    │      │ title    │    │ >= today │   │ Flash   │            │
│  │ Events  │      │ dedup    │    │          │   │ Pro     │            │
│  │ WebEvents│     └──────────┘    └──────────┘   └─────────┘            │
│  └─────────┘                                                             │
│                                                                          │
│  5. Enrich dates  →  5b. dedup events  →  6. Notify                       │
│       │                      │                    │                       │
│       ▼                      ▼                    ▼                       │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐              │
│  │ Fetch page  │      │ same date   │      │ HTML report │              │
│  │ + Gemini    │      │ same source │      │ or email    │              │
│  └─────────────┘      └─────────────┘      └─────────────┘              │
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
| AI | Google Gemini (google-genai) |
| Config | TOML (tomllib) + pydantic-settings |
| Validazione | Pydantic v2 |
| Template | Jinja2 |

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
├── progress.py          # ProgressTracker – output progresso
└── collectors/
    ├── base.py          # BaseCollector (abstract)
    ├── ted.py           # TEDCollector – API TED
    ├── anac.py          # ANACCollector – ANAC OCDS
    ├── events.py        # EventsCollector – RSS/Atom
    ├── web_events.py    # WebEventsCollector – pagine HTML + Gemini
    └── web_tenders.py   # WebTendersCollector – bandi regionali italiani
```

---

## 4. Moduli principali

### 4.1 main.py

- **Entry point**: `cli()` → `run(args)`
- **Argomenti**: `--config`, `--test`, `--italia`, `--no-resume`
- **Pipeline**: `_collect` → `_deduplicate` → `_filter_future` → `classify_all` → `_patch_extracted_dates` → `enrich_missing_dates` → `_dedup_events_by_date` → `notify`
- **Resume**: se `--no-resume` non è usato, usa `PipelineCache.find_latest_run()` e carica `collected.json`

### 4.2 config.py

- **Secrets**: `.env` via `pydantic_settings` (GEMINI_API_KEY, SMTP, ecc.)
- **Parametri**: `config.toml` via `tomllib`
- **Classe**: `Settings` – merge di secrets e parametri

### 4.3 models.py

```python
# Modelli principali
Source          # TED | ANAC | EVENT
OpportunityType # BANDO | CONCORSO | EVENTO
Category        # SAP | DATA | AI | CLOUD | OTHER
Opportunity      # id, title, description, deadline, source_url, ...
Classification  # relevance_score, category, reason, key_requirements, extracted_date
ClassifiedOpportunity  # opportunity + classification
```

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
- Source: `Regionale`, OpportunityType: `Bando`
- Attivato con `web_tenders = true` in config (default: disattivato, attivo in `--italia`)

### 4.5 classifier.py

- **GeminiClassifier**: `classify_all(opportunities, cache, progress)`
- **Prompt**: system prompt con profilo azienda + istruzioni per JSON
- **Output**: `Classification` (Pydantic) con `response_schema`
- **Structured output**: `response_mime_type="application/json"`

### 4.6 date_enricher.py

- **enrich_missing_dates(classified, settings)**
- Per ogni opportunità senza `deadline` e con `source_url`:
  - Fetch pagina
  - Estrazione testo HTML
  - Invio a Gemini con prompt dedicato all’estrazione date
  - Parsing JSON e patch del campo `deadline`

### 4.7 persistence.py

- **PipelineCache**: directory `output/.cache/run_YYYYMMDD_HHMMSS/`
- **File**: `collected.json`, `classified.json` (JSONL), `classified_ids.json`, `metadata.json`
- **find_latest_run()**: ritorna la cache più recente

### 4.8 notifier.py

- **Notifier.notify(classified, total_analyzed)**
- Filtra per `relevance_threshold`
- Render Jinja2 con `templates/report.html`
- Salvataggio in `output/report_*.html` o invio email

---

## 5. Flusso dati

```
Collectors (TED, ANAC, Events, WebEvents)
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
_dedup_events_by_date (stesso evento, stessa data/fonte)
    │
    ▼
notifier.notify() → HTML report (con tempo di esecuzione)
```

---

## 6. Configurazione tecnica

### 6.1 config.toml

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

[events]
feeds = ["https://...", ...]
web_pages = ["https://www.aiweek.it/", ...]

[company]
profile = "..."
```

### 6.2 Modalità Italia (config.italia.toml)

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

Configurazione aggiuntiva rispetto a `config.toml`:

```toml
[collectors]
web_tenders = true    # attiva il collector bandi regionali

[regional_tenders]
web_pages = [
    "https://www.bandi.regione.lombardia.it/servizi/servizio/catalogo/ricerca-innovazione",
    "https://imprese.regione.emilia-romagna.it/Finanziamenti/finanziamenti-in-corso",
    # ...
]
```

### 6.3 .env

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

---

## 8. Gestione errori e resilienza

- **Collectors**: `asyncio.gather(..., return_exceptions=True)` – un collector fallito non blocca gli altri
- **Gemini**: retry implicito; rate limit con `asyncio.sleep`
- **Resume**: checkpoint dopo collect e durante classificazione
- **TED**: retry su 429/5xx con backoff
- **ANAC**: streaming con fallback su download troncati

---

## 9. Estensibilità

### Aggiungere un nuovo collector

1. Creare `collectors/nuovo.py` con classe che estende `BaseCollector`
2. Implementare `async def collect() -> list[Opportunity]`
3. Registrare in `main.py` in `_collect()` e in `config.toml` se serve flag

### Aggiungere un nuovo campo a Opportunity

1. Aggiornare `models.Opportunity`
2. Aggiornare i collector che popolano il campo
3. Aggiornare `templates/report.html` se necessario

### Cambiare il formato del report

- Modificare `templates/report.html` (Jinja2)
- Variabili passate: `opportunities`, `total_analyzed`, `relevant_count`, `threshold`, `category_counts`, `type_counts`, `today`, `generated_at`, `lookback_days`

---

## 10. Testing e sviluppo

### 10.1 Modalità test

```bash
uv run monitor-bot --test --no-resume
```

Usa `config.test.toml` con scope ridotto per verificare la pipeline end-to-end in ~1-2 minuti:

- **Collectors**: TED (max 5 risultati, solo Italia) + 1 feed RSS (ForumPA) + 1 seed page WebEvents (AI Week)
- **ANAC**: disabilitato (lento, non necessario per verifiche rapide)
- **Soglia rilevanza**: 4 (più bassa per generare più risultati nel report di test)
- **Lookback**: 3 giorni

`--no-resume` è fondamentale per evitare che il test carichi dalla cache di un run precedente (in produzione con scope EMEA completo), falsando i risultati.

**Output atteso** (~91s con Gemini Flash):

```
[1/6] Collecting       – TED: 5, Events: 1, WebEvents: ~3
[2/6] Deduplicating    – ~8 unique
[3/6] Filtering        – rimozione bandi scaduti
[4/6] Classifying      – ~8 classificati con Gemini
[5/6] Enriching dates  – patch date mancanti
[6/6] Generating report – output/report_*.html
```

### 10.2 Sviluppo

```bash
# Installazione dipendenze
uv sync

# Run completo in produzione
uv run monitor-bot

# Run da zero (ignora cache)
uv run monitor-bot --no-resume

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
