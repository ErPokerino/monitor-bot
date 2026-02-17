# Documentazione funzionale – Monitor Bot

## 1. Introduzione

### 1.1 Obiettivo

Monitor Bot è un sistema di monitoraggio automatico pensato per aziende IT che partecipano a gare pubbliche e vogliono restare aggiornate su bandi, concorsi ed eventi di settore. L’obiettivo è ridurre il lavoro manuale di ricerca e screening, fornendo un report periodico con le opportunità più rilevanti.

### 1.2 Utenti tipici

- **Business development** e commerciale: individuare bandi e concorsi in linea con le competenze aziendali
- **Marketing e comunicazione**: scoprire eventi (conferenze, summit, webinar) per networking e visibilità
- **Management**: avere una visione aggregata delle opportunità IT sul mercato

### 1.3 Contesto d’uso

Il sistema viene eseguito periodicamente (es. schedulato con cron/Task Scheduler) e produce un report HTML. L’utente può consultare il report localmente o riceverlo via email.

---

## 2. Funzionalità

### 2.1 Raccolta dati (Collect)

Il sistema raccoglie opportunità da cinque tipi di fonti:

| Fonte | Tipo | Descrizione |
|-------|------|-------------|
| **TED** | Bandi/Concorsi | Tenders Electronic Daily – gare UE, filtri per CPV (72, 48, 62, 64.2) e Paesi EMEA |
| **ANAC** | Bandi | Open Data ANAC – appalti italiani in formato OCDS |
| **Events (RSS)** | Eventi | Feed RSS/Atom: ForumPA, AgID, Innovazione Italia, EU Digital Strategy, SAP Community |
| **WebEvents** | Eventi | Pagine HTML: AI Week, Google Cloud Events, AWS Events, Azure, Databricks |
| **WebTenders** | Bandi regionali | Portali bandi delle Regioni italiane (Lombardia, Lazio, Emilia-Romagna, ecc.) e Italia Domani (PNRR) – scraping + Gemini |

### 2.2 Tipi di opportunità

- **Bando**: gara d’appalto per servizi/prodotti IT
- **Concorso**: concorso di progettazione o simile
- **Evento**: conferenza, summit, workshop, webinar, hackathon

### 2.3 Classificazione AI

Ogni opportunità viene analizzata da Google Gemini con un **profilo aziendale** configurato. Per ciascuna vengono prodotti:

- **Punteggio di rilevanza** (1–10): quanto è in linea con le competenze aziendali
- **Categoria**: SAP, Data, AI, Cloud, Other
- **Motivazione**: breve spiegazione del punteggio
- **Requisiti chiave**: requisiti principali (bandi) o temi (eventi)
- **Data estratta**: scadenza o data evento, se presente nel testo

### 2.4 Estrazione date

- **Bandi/Concorsi**: scadenza per la presentazione delle offerte (da API o da pagina sorgente)
- **Eventi**: data dell’evento (da descrizione RSS o da pagina web)

Se la fonte non fornisce la data, il sistema può recuperarla dalla pagina web e usare Gemini per estrarla.

### 2.5 Deduplicazione

- **URL/titolo**: rimozione di duplicati esatti
- **Eventi**: rimozione di articoli diversi sullo stesso evento (stessa data, stessa fonte)

### 2.6 Report

Il report HTML include:

- Statistiche: analizzati, rilevanti, soglia minima
- Filtri per tipo: Tutti, Bandi, Concorsi, Eventi
- Filtri per data: Tutte, Prossimi 7/30/90 gg, Personalizzato (con date picker)
- Filtro per fonte/ente (dropdown con tutte le fonti presenti)
- Ripartizione per categoria
- Card per ogni opportunità con: titolo, data/scadenza, ente, valore, motivazione AI, link alla fonte
- Tempo di esecuzione nel footer

---

## 3. Casi d’uso

### UC1 – Report periodico

**Attore**: Utente schedulato  
**Precondizione**: Configurazione valida, GEMINI_API_KEY impostata  
**Flusso**:
1. L’utente esegue `uv run monitor-bot` (o via scheduler)
2. Il sistema raccoglie da tutte le fonti abilitate
3. Classifica le opportunità con Gemini
4. Genera il report HTML in `output/`
5. (Opzionale) Invia il report via email

**Postcondizione**: File `report_YYYYMMDD_HHMMSS.html` creato

### UC2 – Raccolta da zero (no cache)

**Attore**: Utente  
**Precondizione**: Cache di run precedenti presente  
**Flusso**:
1. L’utente esegue `uv run monitor-bot --no-resume`
2. Il sistema ignora la cache e raccoglie tutto da zero
3. Utile dopo modifiche a fonti (es. nuove web_pages) o per forzare un refresh completo

### UC3 – Test rapido della pipeline

**Attore**: Sviluppatore / Amministratore  
**Precondizione**: Configurazione valida, GEMINI_API_KEY impostata  
**Flusso**:
1. L'utente esegue `uv run monitor-bot --test --no-resume`
2. Il sistema carica `config.test.toml` (scope ridotto: solo Italia, max 5 risultati/collector, 1 feed RSS, 1 pagina web)
3. Esegue la pipeline completa end-to-end: collect → dedup → filter → classify → enrich → report
4. Genera il report in `output/`

**Postcondizione**: Pipeline verificata in ~1-2 minuti con un report di pochi risultati  
**Note**: `--no-resume` evita di riprendere dalla cache di run precedenti con scope più ampio. Il file `config.test.toml` è versionato e pronto all'uso.

### UC4 – Monitoraggio solo Italia

**Attore**: Utente  
**Precondizione**: Configurazione valida, GEMINI_API_KEY impostata  
**Flusso**:
1. L'utente esegue `uv run monitor-bot --italia --no-resume`
2. Il sistema carica `config.italia.toml` (perimetro italiano)
3. Raccoglie bandi da TED (solo IT), ANAC, portali regionali (Lombardia, Lazio, Emilia-Romagna, Piemonte, Veneto, Italia Domani)
4. Raccoglie eventi da feed RSS italiani e pagine web (AI Week, Google Cloud IT, Microsoft AI Tour)
5. Classifica, arricchisce date e genera report

**Postcondizione**: Report con sole opportunità italiane (bandi nazionali, regionali, eventi IT in Italia)

### UC5 – Personalizzazione profilo aziendale

**Attore**: Amministratore  
**Flusso**:
1. Modifica la sezione `[company]` in `config.toml`
2. Inserisce competenze, ambiti e range di valore
3. Le successive classificazioni useranno il nuovo profilo

### UC6 – Aggiunta nuove fonti eventi

**Attore**: Amministratore  
**Flusso**:
1. Per feed RSS: aggiunge URL in `[events].feeds`
2. Per pagine web: aggiunge URL in `[events].web_pages`
3. Rilancia con `--no-resume` per includere le nuove fonti

### UC7 – Ripresa dopo interruzione

**Attore**: Sistema  
**Precondizione**: Run precedente interrotto (Ctrl+C, errore di rete, quota Gemini)  
**Flusso**:
1. L’utente esegue `uv run monitor-bot` senza `--no-resume`
2. Il sistema carica i dati dalla cache
3. Riprende dalla classificazione (o dalla fase successiva)
4. Evita di rifare la raccolta e le classificazioni già completate

---

## 4. Configurazione funzionale

### 4.1 Parametri principali

| Parametro | File | Descrizione | Default |
|-----------|------|-------------|---------|
| `relevance_threshold` | config.toml | Soglia minima (1–10) per includere nel report | 6 |
| `lookback_days` | config.toml | Giorni indietro per la ricerca | 7 |
| `max_results` | config.toml | Limite risultati per collector (0 = illimitato) | 0 |
| `cpv_codes` | config.toml | Codici CPV per filtrare bandi IT | 72, 48, 62, 64.2 |
| `countries` | config.toml | Paesi per TED | EMEA |

### 4.2 Modalità test

Il file `config.test.toml` contiene una configurazione ridotta per test rapidi (~1-2 min):

```bash
uv run monitor-bot --test --no-resume
```

| Parametro | Produzione | Test |
|-----------|-----------|------|
| Paesi | 30+ (EMEA) | Solo Italia |
| Risultati/collector | Illimitati | Max 5 |
| Lookback | 7 giorni | 3 giorni |
| ANAC | Attivo | Disattivato |
| Feed RSS | 5 | 1 (ForumPA) |
| Seed pages WebEvents | 6 | 1 (AI Week) |
| Soglia rilevanza | 6 | 4 |

`--no-resume` è necessario per evitare di riprendere dalla cache di run precedenti con scope più ampio.

### 4.3 Modelli Gemini

- `gemini-3-flash-preview`: più veloce, costo inferiore
- `gemini-3-pro-preview`: più accurato, più lento

### 4.4 Abilitazione/disabilitazione fonti

In `config.toml`, sezione `[collectors]`:

- `ted = true/false`
- `anac = true/false`
- `events = true/false`
- `web_events = true/false`
- `web_tenders = true/false` (bandi regionali italiani – default: disattivato)

---

## 5. Output e report

### 5.1 Report HTML

- **Lingua**: italiano
- **Formato**: HTML standalone con CSS inline
- **Posizione**: `output/report_YYYYMMDD_HHMMSS.html`
- **Contenuto**: header, statistiche, filtri, card opportunità, footer

### 5.2 Email

Se configurati SMTP e indirizzi in `config.toml`:

- **Oggetto**: `Monitor Bandi: N opportunità rilevanti trovate`
- **Corpo**: HTML del report

### 5.3 Cache

- **Directory**: `output/.cache/run_YYYYMMDD_HHMMSS/`
- **Scopo**: checkpoint per resume
- **Contenuto**: `collected.json`, `classified.json`, `classified_ids.json`, `metadata.json`

---

## 6. Limitazioni e vincoli

- **Gemini API**: richiede chiave valida e quota sufficiente
- **Rate limit**: ritardi tra richieste per rispettare API esterne
- **Pagine SPA**: siti che caricano contenuti via JavaScript non sono analizzabili (es. TED web); per TED si usa l’API
- **Lingua**: classificazione e report sono in italiano; le fonti possono essere multilingua

---

## 7. Glossario

| Termine | Significato |
|---------|-------------|
| **TED** | Tenders Electronic Daily – banca dati UE delle gare pubbliche |
| **ANAC** | Autorità Nazionale Anticorruzione – portale dati aperti italiani |
| **CPV** | Common Procurement Vocabulary – codici classificazione appalti |
| **RSS** | Really Simple Syndication – formato per feed di notizie |
| **Resume** | Ripresa da checkpoint salvato |
