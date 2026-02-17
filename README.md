# Monitor Bot – Tender & Event Monitor

Monitoraggio automatico di bandi di gara, concorsi pubblici ed eventi IT rilevanti per aziende del settore tecnologico. Il sistema raccoglie opportunità da fonti pubbliche (TED, ANAC, feed RSS, pagine web), le classifica tramite intelligenza artificiale (Google Gemini) e genera report HTML in italiano.

## Caratteristiche principali

- **Bandi e concorsi**: TED (UE), ANAC (Italia), portali regionali italiani con filtri per CPV e Paesi
- **Eventi**: feed RSS (ForumPA, AgID, Innovazione Italia, EU Digital, SAP) e pagine web (AI Week, Google Cloud, AWS, Azure, Databricks)
- **Modalità Italia**: perimetro esclusivamente italiano con bandi regionali (Lombardia, Lazio, Emilia-Romagna, ecc.)
- **Classificazione AI**: punteggio di rilevanza (1–10) e categorizzazione (SAP, Data, AI, Cloud)
- **Date esplicite**: scadenze per bandi, date evento per eventi (estrazione automatica)
- **Report HTML**: interfaccia in italiano con filtri per tipo e categoria
- **Resume**: riprende da checkpoint in caso di interruzione

## Requisiti

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (consigliato) oppure pip

## Installazione

```bash
# Con uv (consigliato)
uv sync

# Oppure con pip
pip install -e .
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

3. (Opzionale) Configura SMTP in `.env` per l’invio via email.

4. Personalizza `config.toml` (profilo azienda, soglia rilevanza, fonti, ecc.).

## Utilizzo

```bash
# Esecuzione standard
uv run monitor-bot

# Esecuzione senza cache (raccolta completa da zero)
uv run monitor-bot --no-resume

# Configurazione personalizzata
uv run monitor-bot --config mio_config.toml
```

Il report HTML viene salvato in `output/report_YYYYMMDD_HHMMSS.html`.

### Modalità test

Per verificare rapidamente il funzionamento della pipeline end-to-end senza attendere una raccolta completa:

```bash
uv run monitor-bot --test --no-resume
```

Usa `config.test.toml` con una configurazione ridotta:

| Parametro | Produzione | Test |
|-----------|-----------|------|
| Paesi | 30+ (EMEA) | Solo Italia |
| Risultati per collector | Illimitati | Max 5 |
| Lookback | 7 giorni | 3 giorni |
| TED | Attivo | Attivo |
| ANAC | Attivo | **Disattivato** |
| Feed RSS | 5 feed | 1 (ForumPA) |
| WebEvents | 6 seed pages | 1 (AI Week) |
| Soglia rilevanza | 6 | 4 |

**Tempo di esecuzione**: ~1-2 minuti (vs 5-15 min in produzione).

> **Nota**: `--no-resume` è importante per evitare di riprendere dalla cache di un run precedente con scope più ampio.

### Modalità Italia

Per eseguire il monitoraggio solo sul perimetro italiano (bandi nazionali, regionali ed eventi IT in Italia):

```bash
uv run monitor-bot --italia --no-resume
```

Usa `config.italia.toml` con:

| Fonte | Descrizione |
|-------|-------------|
| **TED** | Solo bandi con country = IT |
| **ANAC** | Bandi nazionali italiani |
| **Bandi regionali** | Portali di Lombardia, Lazio, Emilia-Romagna, Piemonte, Veneto + Italia Domani (PNRR) |
| **Feed RSS** | ForumPA, AgID, Innovazione Italia |
| **WebEvents** | AI Week, Google Cloud Events IT, Microsoft AI Tour |

I bandi regionali vengono raccolti tramite scraping dei portali delle Regioni con estrazione intelligente via Gemini (stessa logica a due fasi degli eventi web).

## Struttura del progetto

```
monitor-bot/
├── config.toml          # Configurazione principale
├── .env                 # Chiavi API (non committare)
├── src/monitor_bot/     # Codice sorgente
│   ├── main.py         # CLI e pipeline
│   ├── collectors/     # TED, ANAC, Events, WebEvents, WebTenders
│   ├── classifier.py   # Classificazione Gemini
│   ├── date_enricher.py
│   └── ...
├── templates/           # Template report HTML
└── output/              # Report e cache
```

## Documentazione

- [Documentazione funzionale](docs/DOCUMENTAZIONE_FUNZIONALE.md) – obiettivi, funzionalità, casi d’uso
- [Documentazione tecnica](docs/DOCUMENTAZIONE_TECNICA.md) – architettura, API, moduli

## Licenza

POC – uso interno.
