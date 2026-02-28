# Opportunity Radar – Tender & Event Monitor

Monitoraggio automatico di bandi di gara, concorsi pubblici ed eventi IT rilevanti per aziende del settore tecnologico. Il sistema raccoglie opportunità da fonti pubbliche (TED, ANAC, feed RSS, pagine web, ricerche Google), le classifica tramite intelligenza artificiale (Google Gemini) e presenta i risultati in una web app enterprise multi-utente con ruoli `admin | user`, condivisione opportunità e chatbot contestuale al profilo utente.

## Architettura

Il progetto è composto da due processi separati:

| Componente | Tecnologia | Porta | Comando |
|------------|-----------|-------|---------|
| **Backend (API)** | FastAPI + SQLAlchemy + PostgreSQL + Gemini 2.5 Flash + Gemini Live | 8000 | `uv run monitor-web` |
| **Frontend (UI)** | Vite + Alpine.js + TailwindCSS | 5173 | `npm run dev` (da `frontend/`) |

In sviluppo, il frontend proxya le chiamate API (`/api/*`) al backend. In produzione, `npm run build` genera file statici servibili da nginx o dal backend stesso.

## Requisiti

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (consigliato) oppure pip
- Node.js 18+ e npm

## Installazione

```bash
# Backend
uv sync

# Frontend
cd frontend
npm install
```

## Configurazione

1. Copia `.env.example` in `.env`:
   ```bash
   cp .env.example .env
   ```

2. Inserisci la chiave API Gemini in `.env`:
   ```
   GEMINI_API_KEY=your-gemini-api-key-here
   ```

3. (Opzionale) Configura SMTP in `.env` per l'invio via email.
4. Personalizza `config.toml` (profilo azienda, fonti, ricerche web, ecc.).

## Avvio in sviluppo

Aprire **due terminali separati**:

**Terminale 1 – Backend:**
```bash
uv run monitor-web
```

**Terminale 2 – Frontend:**
```bash
cd frontend
npm run dev
```

Aprire il browser su **http://localhost:5173**.

## Pagine dell'applicazione

| Pagina | Percorso | Descrizione |
|--------|----------|-------------|
| Login | `/login.html` | Autenticazione utente (username/password, toggle visibilita' password) |
| Agenda | `/` | Valutazione opportunità (pollice su/giù), condivisione con altri utenti, tab "Shared with me", iscrizione eventi, pannello scadenze, feedback eventi passati |
| Esecuzioni | `/esecuzioni.html` | Storico completo delle esecuzioni con selezione multipla e cancellazione |
| Settings | `/configurazioni.html` | Link diretti, ricerche internet, impostazioni (soglia pertinenza, profilo azienda, scheduler on/off, schedulazione, notifiche email) |
| Ricerca | `/esegui.html` | Avvio pipeline con barra di progresso in tempo reale |
| Dettaglio | `/dettaglio.html?id=N` | Risultati di una singola esecuzione con filtri (tipo, categoria, scadenza) e export multi-formato (CSV, HTML, PDF) |
| Bot | `/chatbot.html` | Chatbot AI con supporto voice mode (Gemini Live native audio), layout responsive mobile |
| Admin | `/admin.html` | Gestione utenti (crea/disattiva/riattiva/elimina), overview utenti/sessioni/run |

## API Endpoints

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/api/agenda` | Lista elementi agenda (filtri: tab, type, category, sort, search) |
| GET | `/api/agenda/stats` | Contatori notifiche (non visti, da valutare, in scadenza, condivisi) |
| GET | `/api/agenda/notifications` | Lista notifiche (agenda non viste + condivise non viste) |
| GET | `/api/agenda/shared` | Elementi condivisi con l'utente corrente |
| GET | `/api/agenda/shared/stats` | Contatore condivisi non visti |
| POST | `/api/agenda/{id}/share` | Condivisione opportunità verso un altro utente |
| POST | `/api/agenda/shared/mark-seen` | Segna condivisi come letti |
| GET | `/api/agenda/expiring` | Elementi in scadenza entro N giorni |
| GET | `/api/agenda/past-events` | Eventi passati con iscrizione per feedback |
| PATCH | `/api/agenda/{id}/evaluate` | Valutazione elemento (interested/rejected) |
| PATCH | `/api/agenda/{id}/enroll` | Iscrizione/disiscrizione evento |
| PATCH | `/api/agenda/{id}/feedback` | Feedback post-evento (consiglio, ritorno) |
| POST | `/api/agenda/mark-seen` | Segna elementi agenda come visti |
| GET | `/api/dashboard` | Statistiche dashboard |
| GET/POST | `/api/sources` | Lista e creazione link diretti |
| PATCH/DELETE | `/api/sources/{id}` | Modifica e cancellazione |
| POST | `/api/sources/{id}/toggle` | Attiva/disattiva |
| GET/POST | `/api/queries` | Lista e creazione ricerche internet |
| PATCH/DELETE | `/api/queries/{id}` | Modifica e cancellazione |
| POST | `/api/queries/{id}/toggle` | Attiva/disattiva |
| GET/PUT | `/api/settings` | Lettura e aggiornamento impostazioni utente/sistema |
| GET | `/api/runs` | Lista esecuzioni |
| GET | `/api/runs/{id}` | Dettaglio esecuzione con risultati |
| GET | `/api/runs/{id}/progress` | Progresso esecuzione (polling) |
| POST | `/api/runs/start` | Avvia nuova esecuzione |
| POST | `/api/runs/stop` | Interrompi esecuzione in corso |
| DELETE | `/api/runs/{id}` | Cancella esecuzione |
| POST | `/api/runs/delete-batch` | Cancellazione multipla |
| POST | `/api/chat/message` | Invio messaggio al chatbot AI |
| DELETE | `/api/chat/history` | Reset storico conversazione |
| GET | `/api/chat/status` | Stato contesto chatbot |
| WS | `/api/chat/voice` | Sessione vocale real-time (Gemini Live native audio) |
| POST | `/api/auth/login` | Autenticazione utente |
| POST | `/api/auth/logout` | Logout e revoca sessione |
| GET | `/api/auth/me` | Verifica sessione corrente |
| GET | `/api/auth/users` | Directory utenti attivi (ricerca per share picker) |
| GET | `/api/admin/users` | Lista utenti (admin) |
| POST | `/api/admin/users` | Crea utente (admin) |
| DELETE | `/api/admin/users/{id}` | Disattiva utente (admin) |
| POST | `/api/admin/users/{id}/activate` | Riattiva utente (admin) |
| DELETE | `/api/admin/users/{id}/hard` | Elimina definitivamente utente (admin) |
| GET | `/api/admin/overview` | KPI amministrativi (utenti/sessioni/run) |

## CLI (uso diretto pipeline)

```bash
uv run monitor-bot                              # Esecuzione standard
uv run monitor-bot --no-resume                   # Senza cache
uv run monitor-bot --config mio_config.toml      # Config custom
uv run monitor-bot --test --no-resume            # Test rapido
uv run monitor-bot --italia --no-resume          # Solo Italia
```

## Struttura del progetto

```
monitor-bot/
├── config.toml                # Configurazione principale (EMEA)
├── config.italia.toml         # Configurazione Italia
├── config.test.toml           # Configurazione test rapido
├── .env                       # Chiavi API (non committare)
├── pyproject.toml             # Dipendenze Python
├── infra/                     # Terraform (GCP infrastructure)
├── src/monitor_bot/           # Backend Python
│   ├── app.py                 # FastAPI app factory + auth middleware
│   ├── auth.py                # Password hashing Argon2, sessioni DB, principal/RBAC
│   ├── main.py                # CLI entry point
│   ├── job.py                 # Entry point Cloud Run Job
│   ├── pipeline.py            # Pipeline engine
│   ├── config.py              # Configurazione TOML + secrets
│   ├── database.py            # SQLAlchemy async engine
│   ├── db_models.py           # ORM models
│   ├── schemas.py             # Pydantic schemas
│   ├── routes/                # API endpoints
│   │   ├── api_agenda.py      # Agenda (valutazioni, share, notifiche)
│   │   ├── api_auth.py        # Auth sessioni + directory utenti
│   │   ├── api_admin.py       # Gestione utenti e overview admin
│   │   ├── api_chat.py        # Chatbot AI (testo)
│   │   ├── api_voice.py       # Voice mode (Gemini Live WebSocket)
│   │   ├── api_dashboard.py
│   │   ├── api_sources.py
│   │   ├── api_queries.py
│   │   ├── api_runs.py
│   │   └── api_settings.py
│   ├── services/              # Business logic
│   │   ├── agenda.py
│   │   ├── sources.py
│   │   ├── queries.py
│   │   ├── runs.py
│   │   ├── settings.py        # Impostazioni + sync Cloud Scheduler
│   │   ├── users.py           # Lifecycle utenti (create/activate/deactivate/delete)
│   │   ├── audit.py           # Audit log azioni sensibili
│   │   └── email.py           # Notifiche email pipeline
│   ├── collectors/            # Data collectors
│   │   ├── ted.py
│   │   ├── anac.py
│   │   ├── events.py
│   │   ├── web_events.py
│   │   ├── web_tenders.py
│   │   └── web_search.py
│   ├── classifier.py          # Classificazione Gemini
│   └── date_enricher.py       # Arricchimento date
├── frontend/                  # Frontend Vite
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── index.html             # Agenda + shared + share modal
│   ├── esecuzioni.html        # Storico esecuzioni
│   ├── login.html             # Login page
│   ├── chatbot.html           # Chatbot + voice mode
│   ├── configurazioni.html    # Settings (3 tab)
│   ├── esegui.html            # Esecuzione pipeline
│   ├── dettaglio.html         # Dettaglio risultati
│   ├── admin.html             # Console amministrativa utenti
│   └── src/
│       ├── main.js            # Alpine.js setup
│       ├── style.css          # TailwindCSS
│       ├── api.js             # Client API centralizzato
│       └── components/        # Alpine.js components (agenda/config/admin/chatbot/...)
├── templates/                 # Jinja2 templates (report HTML)
├── cloudbuild.yaml            # CI/CD Cloud Build
├── Dockerfile                 # Multi-stage build (Node + Python)
└── output/                    # Report e cache CLI
```

## Licenza

POC – uso interno.
