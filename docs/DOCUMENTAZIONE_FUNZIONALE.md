# Documentazione funzionale – Monitor Bot

## 1. Introduzione

### 1.1 Obiettivo

Monitor Bot è un sistema di monitoraggio automatico pensato per aziende IT che partecipano a gare pubbliche e vogliono restare aggiornate su bandi, concorsi ed eventi di settore. L'obiettivo è ridurre il lavoro manuale di ricerca e screening, fornendo un report periodico con le opportunità più rilevanti.

### 1.2 Utenti tipici

- **Business development** e commerciale: individuare bandi e concorsi in linea con le competenze aziendali
- **Marketing e comunicazione**: scoprire eventi (conferenze, summit, webinar) per networking e visibilità
- **Management**: avere una visione aggregata delle opportunità IT sul mercato

### 1.3 Contesto d'uso

Il sistema e' disponibile come web application enterprise multi-utente con autenticazione e ruoli (`admin | user`). L'utente accede tramite login, viene guidato da un onboarding carousel alla prima visita, e puo' interagire con tutte le funzionalita' tramite interfaccia web. Il sistema puo' essere eseguito anche periodicamente (batch job schedulato) con notifica email dei risultati. Un chatbot AI integrato (con supporto voice mode) assiste l'utente nell'analisi dei risultati con contesto personalizzato per utente e ruolo.

---

## 2. Funzionalità

### 2.1 Raccolta dati (Collect)

Il sistema raccoglie opportunità da sei tipi di fonti:

| Fonte | Tipo | Descrizione |
|-------|------|-------------|
| **TED** | Bandi/Concorsi | Tenders Electronic Daily – gare UE, filtri per CPV (72, 48, 62, 64.2) e Paesi EMEA |
| **ANAC** | Bandi | Open Data ANAC – appalti italiani in formato OCDS |
| **Events (RSS)** | Eventi | Feed RSS/Atom: ForumPA, AgID, Innovazione Italia, EU Digital Strategy, SAP Community |
| **WebEvents** | Eventi | Pagine HTML: AI Week, Google Cloud Events, AWS Events, Azure, Databricks |
| **WebTenders** | Bandi regionali | Portali bandi delle Regioni italiane (Lombardia, Lazio, Emilia-Romagna, ecc.) e Italia Domani (PNRR) – scraping + Gemini |
| **WebSearch** | Bandi/Eventi | Ricerca Google tramite Gemini con grounding – scopre nuovi bandi/eventi non coperti dalle fonti configurate |

### 2.2 Tipi di opportunità

- **Bando**: gara d'appalto per servizi/prodotti IT
- **Concorso**: concorso di progettazione o simile
- **Evento**: conferenza, summit, workshop, webinar, hackathon. Per ogni evento vengono raccolte informazioni aggiuntive: formato (in presenza / streaming / on demand), costo (gratuito / a pagamento / su invito), luogo (nazione e citta') e settore di riferimento

### 2.3 Classificazione AI

Ogni opportunità viene analizzata da Google Gemini con un **profilo aziendale** configurato. Per ciascuna vengono prodotti:

- **Punteggio di rilevanza** (1–10): quanto è in linea con le competenze aziendali
- **Categoria**: SAP, Data, AI, Cloud, Other
- **Motivazione**: breve spiegazione del punteggio
- **Requisiti chiave**: requisiti principali (bandi) o temi (eventi)
- **Data estratta**: scadenza o data evento, se presente nel testo

Per le opportunita' di tipo **Evento**, vengono estratti anche:

- **Formato evento**: In presenza, Streaming, On demand (opzioni esclusive)
- **Costo**: Gratuito, A pagamento, Su invito
- **Citta'**: luogo fisico dell'evento (solo per eventi in presenza)
- **Settore**: mercato verticale a cui si rivolge l'evento (es. Healthcare, Finance, PA, Manufacturing, Retail, Energy, Telco, Education, Cross-sector)

### 2.4 Estrazione date

- **Bandi/Concorsi**: scadenza per la presentazione delle offerte (da API o da pagina sorgente)
- **Eventi**: data dell'evento (da descrizione RSS o da pagina web)

Se la fonte non fornisce la data, il sistema può recuperarla dalla pagina web e usare Gemini per estrarla.

### 2.5 Deduplicazione

- **URL/titolo**: rimozione di duplicati esatti
- **Eventi**: deduplicazione intelligente con fuzzy matching sui titoli. Eventi con la stessa data vengono confrontati normalizzando i titoli (rimozione anno, edizione, punteggiatura) e verificando sovrapposizione di parole chiave. Ad esempio, "AI WEEK 2026" e "AI WEEK - 7th Edition" vengono riconosciuti come lo stesso evento. Viene mantenuto quello con il punteggio più alto.

### 2.6 Ricerca web automatica

Il sistema può eseguire ricerche Google configurabili per scoprire nuovi bandi/eventi che non sono coperti dai siti/feed configurati. La funzione utilizza Gemini con Google Search grounding per:

1. Eseguire le query di ricerca configurate
2. Analizzare i risultati e filtrare quelli rilevanti
3. Visitare le pagine trovate ed estrarre informazioni strutturate
4. Includere le opportunità scoperte nel report

Le query sono configurabili nel file `config.toml` (sezione `[web_search]`).

### 2.7 Report

Il report HTML include:

- Statistiche: analizzati, rilevanti, soglia minima
- Filtri per tipo: Tutti, Bandi, Concorsi, Eventi
- Filtri per data: Tutte, Prossimi 7/30/90 gg, Personalizzato (con date picker)
- Filtro per fonte/ente (dropdown con tutte le fonti presenti)
- Filtro per categoria: SAP, Cloud, AI, Data, Other (con contatori)
- Ripartizione per categoria
- Card per ogni opportunità con: titolo, data/scadenza, ente, valore, motivazione AI, link alla fonte, e per gli eventi: formato, costo, luogo e settore
- Tempo di esecuzione nel footer

### 2.8 Agenda

L'Agenda e' la pagina principale dell'applicazione e raccoglie tutte le opportunita' trovate dalle ricerche in una vista unificata e deduplicata. Funzionalita':

- **Valutazione**: ogni opportunita' puo' essere valutata con pollice su (interessante) o pollice giu' (scartata). Gli elementi scartati vengono esclusi dalle ricerche future.
- **Iscrizione eventi**: per le opportunita' di tipo Evento, l'utente puo' segnare l'iscrizione.
- **Condivisione opportunita'**: l'utente puo' condividere un item con un altro utente usando un selettore utenti con filtro automatico durante la digitazione.
- **Pannello scadenze**: mostra gli elementi in scadenza entro N giorni (configurabile: 7/14/30/60).
- **Feedback eventi passati**: per gli eventi a cui l'utente si e' iscritto e la cui data e' passata, e' possibile dare un feedback ("Lo consiglieresti?" e "Torneresti il prossimo anno?").
- **Notifiche**: la campanella nella navbar mostra badge numerico e, al click, apre un pannello con lista notifiche (agenda non viste + condivise non viste). Non avviene redirect automatico.
- **Filtri e ricerca**: filtraggio per tipo (Bando/Evento/Concorso), categoria, stato iscrizione, ricerca testuale e ordinamento.
- **Esclusione automatica**: gli elementi scartati e quelli con data di scadenza passata vengono automaticamente esclusi dalle ricerche future dello stesso utente.

Tab disponibili:
1. **Da valutare**: elementi non ancora valutati
2. **Interessanti**: elementi valutati positivamente
3. **Shared with me**: elementi condivisi da altri utenti
4. **Eventi passati**: eventi con iscrizione e data passata, per consultazione e feedback

### 2.9 Pagina Esecuzioni

La pagina Esecuzioni mostra lo storico completo delle ricerche eseguite con tabella interattiva: data, stato, raccolti, rilevanti, durata. Supporta selezione multipla e cancellazione batch. Da ogni riga si accede alla pagina di dettaglio della singola esecuzione.

### 2.10 Autenticazione

L'accesso all'applicazione richiede autenticazione tramite username e password. La password e' verificata in backend con hashing Argon2.

Caratteristiche:
- Sessioni persistenti su database (token hashato + scadenza + revoca)
- Logout esplicito con invalidazione sessione
- Protezione anti brute-force (blocco temporaneo dopo tentativi falliti)
- Controllo ruoli lato API e lato UI (`admin | user`)
- Redirect automatico al login in caso di token non valido/scaduto

### 2.11 Gestione utenti (Admin)

Gli utenti con ruolo admin hanno accesso alla pagina `/admin.html` con:

- **Creazione utente**: username, nome visualizzato, password, ruolo
- **Disattivazione utente**: blocco accesso e revoca sessioni attive
- **Riattivazione utente**: ripristino accesso
- **Eliminazione definitiva utente**: rimozione account e dati correlati
- **Overview operativa**: utenti totali/attivi, sessioni attive, run in corso

Vincoli funzionali:
- un admin non puo' disattivare o eliminare il proprio account
- deve esistere sempre almeno un admin attivo

### 2.12 Onboarding

Al primo accesso dopo il login, viene presentato un carousel di benvenuto con 4 slide:
1. **Benvenuto**: introduzione a Opportunity Radar
2. **Agenda**: come valutare le opportunita', gestire iscrizioni e monitorare scadenze
3. **Settings e Configurazioni**: come configurare fonti, profilo e schedulazione
4. **Bot e Voice Mode**: come utilizzare il chatbot AI e la conversazione vocale

L'utente puo' navigare tra le slide, saltare l'onboarding o completarlo. La scelta viene memorizzata e l'onboarding non viene riproposto nelle visite successive.

### 2.13 Chatbot AI (Opportunity Bot)

Il chatbot AI integrato permette di:
- Comprendere il funzionamento dell'applicazione
- Analizzare i risultati delle esecuzioni in linguaggio naturale
- Ottenere dettagli su singoli bandi, eventi e opportunita'
- Avviare nuove ricerche tramite conversazione

Il contesto della conversazione include automaticamente le configurazioni, lo storico esecuzioni e i risultati dell'esecuzione selezionata.

La toolbar del chatbot e' responsive: su desktop mostra titolo, selettore esecuzioni e pulsante "Nuova chat" su una riga; su mobile il titolo e il pulsante nuova chat sono sulla prima riga, il selettore esecuzioni va a capo sulla seconda riga a larghezza piena.

Il pulsante "Nuova chat" richiede una conferma a due click per evitare cancellazioni accidentali: al primo click mostra l'icona cestino con il testo "Conferma?", al secondo click resetta la conversazione.

### 2.14 Voice Mode

La modalita' vocale utilizza Gemini Live native audio per conversazioni in tempo reale. L'audio viene processato nativamente dal modello AI (senza passaggi intermedi STT/TTS), risultando in conversazioni naturali e fluenti in italiano.

Per attivare il voice mode, l'utente clicca il pulsante "Voce" (icona microfono con onde laterali) nella pagina chatbot. Viene mostrato un overlay fullscreen con indicatore di stato animato (cerchio pulsante con anelli concentrici). L'utente parla naturalmente e riceve risposte audio immediate. I transcript delle conversazioni vengono salvati nella chat. Per terminare, l'utente clicca il pulsante "Termina conversazione" nell'overlay.

---

## 3. Casi d'uso

### UC1 – Report periodico

**Attore**: Utente schedulato  
**Precondizione**: Configurazione valida, GEMINI_API_KEY impostata  
**Flusso**:
1. L'utente esegue `uv run monitor-bot` (o via scheduler)
2. Il sistema raccoglie da tutte le fonti abilitate
3. Classifica le opportunità con Gemini
4. Genera il report HTML in `output/`
5. (Opzionale) Invia il report via email

**Postcondizione**: File `report_YYYYMMDD_HHMMSS.html` creato

### UC2 – Raccolta da zero (no cache)

**Attore**: Utente  
**Precondizione**: Cache di run precedenti presente  
**Flusso**:
1. L'utente esegue `uv run monitor-bot --no-resume`
2. Il sistema ignora la cache e raccoglie tutto da zero
3. Utile dopo modifiche a fonti (es. nuove web_pages, nuove query web search) o per forzare un refresh completo

### UC3 – Test rapido della pipeline

**Attore**: Sviluppatore / Amministratore  
**Precondizione**: Configurazione valida, GEMINI_API_KEY impostata  
**Flusso**:
1. L'utente esegue `uv run monitor-bot --test --no-resume`
2. Il sistema carica `config.test.toml` (scope ridotto: solo Italia, max 5 risultati/collector, 1 feed RSS, 1 pagina web, 1 query web search)
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
5. Esegue ricerche web con query focalizzate su Italia
6. Classifica, arricchisce date e genera report

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
3. Per ricerche web: aggiunge query in `[web_search].queries`
4. Rilancia con `--no-resume` per includere le nuove fonti

### UC7 – Ripresa dopo interruzione

**Attore**: Sistema  
**Precondizione**: Run precedente interrotto (Ctrl+C, errore di rete, quota Gemini)  
**Flusso**:
1. L'utente esegue `uv run monitor-bot` senza `--no-resume`
2. Il sistema carica i dati dalla cache
3. Riprende dalla classificazione (o dalla fase successiva)
4. Evita di rifare la raccolta e le classificazioni già completate

### UC8 – Accesso all'applicazione

**Attore**: Utente  
**Precondizione**: Credenziali valide  
**Flusso**:
1. L'utente accede a `/login.html`
2. Inserisce username e password
3. Il sistema valida le credenziali e genera un token di sessione
4. L'utente viene reindirizzato alla Dashboard
5. Al primo accesso viene mostrato l'onboarding carousel

**Postcondizione**: Utente autenticato con accesso a tutte le funzionalita'

### UC9 – Conversazione con il chatbot

**Attore**: Utente autenticato  
**Precondizione**: Almeno un'esecuzione completata  
**Flusso**:
1. L'utente accede alla pagina Bot
2. Seleziona un'esecuzione dal menu
3. Pone domande sui risultati in linguaggio naturale
4. Il chatbot risponde con informazioni contestuali

**Postcondizione**: L'utente ha ottenuto insight sui risultati

### UC10 – Conversazione vocale

**Attore**: Utente autenticato  
**Precondizione**: Browser con supporto microfono  
**Flusso**:
1. L'utente attiva il voice mode nella pagina Bot
2. Il browser richiede l'accesso al microfono
3. L'utente parla in italiano
4. Il sistema processa l'audio tramite Gemini Live e risponde in tempo reale con voce nativa
5. I transcript vengono salvati nella conversazione

**Postcondizione**: Conversazione vocale completata con transcript persistito

### UC11 – Condivisione opportunita' tra utenti

**Attore**: Utente autenticato  
**Precondizione**: Presenza di almeno un'opportunita' in agenda e almeno un altro utente attivo  
**Flusso**:
1. L'utente clicca `Condividi` su un elemento agenda
2. Si apre la modale con selettore utenti
3. L'utente digita nome/username e la lista si filtra automaticamente
4. Seleziona il destinatario, opzionalmente inserisce una nota, conferma
5. Il destinatario vede una nuova notifica in campanella e l'elemento nella tab `Shared with me`

**Postcondizione**: Share registrato e notificabile al destinatario

### UC12 – Lifecycle utente in area Admin

**Attore**: Admin  
**Precondizione**: Accesso autenticato con ruolo admin  
**Flusso**:
1. Admin accede a `/admin.html`
2. Crea un nuovo utente o seleziona un utente esistente
3. Può disattivarlo, riattivarlo o eliminarlo definitivamente
4. In caso di disattivazione, le sessioni attive dell'utente vengono invalidate
5. In caso di eliminazione definitiva, vengono rimossi anche i dati correlati dell'utente

**Postcondizione**: Stato utente aggiornato in modo consistente con policy di sicurezza

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
| `scheduler_enabled` | UI `/configurazioni.html` (admin) | Abilita/disabilita esecuzione programmata senza perdere giorno/orario | 1 (attivo) |
| `scheduler_day` | UI `/configurazioni.html` (admin) | Giorno esecuzione settimanale (0 domenica ... 6 sabato) | 1 |
| `scheduler_hour` | UI `/configurazioni.html` (admin) | Ora esecuzione settimanale | 2 |
| `notification_emails` | UI `/configurazioni.html` (admin) | Destinatari report pipeline (CSV separato da virgola) | configurabile |

I parametri scheduler/notifiche sono salvati nel database (settings di sistema) e sincronizzati su Cloud Scheduler in ambiente GCP.

### 4.2 Configurazione fonti

I file di configurazione sono strutturati con commenti guida che spiegano ogni sezione e come aggiungere nuove fonti. Le fonti sono raggruppate per tipologia:

| Sezione | Descrizione | Come aggiungere |
|---------|-------------|-----------------|
| `[events].feeds` | Feed RSS/Atom | Incollare l'URL del feed |
| `[events].web_pages` | Pagine web eventi (seed pages) | Incollare l'URL della pagina |
| `[regional_tenders].web_pages` | Portali bandi regionali | Incollare l'URL del portale |
| `[web_search].queries` | Query di ricerca Google | Scrivere una query efficace |

### 4.3 Modalità test

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
| Query WebSearch | 6 | 1 (3 risultati max) |
| Soglia rilevanza | 6 | 4 |

`--no-resume` è necessario per evitare di riprendere dalla cache di run precedenti con scope più ampio.

### 4.4 Modelli Gemini

- `gemini-2.5-flash`: più veloce, costo inferiore (default)
- `gemini-2.5-pro`: più accurato, più lento
- `gemini-live-2.5-flash-native-audio`: voice mode conversazionale

### 4.5 Abilitazione/disabilitazione fonti

In `config.toml`, sezione `[collectors]`:

- `ted = true/false`
- `anac = true/false`
- `events = true/false`
- `web_events = true/false`
- `web_tenders = true/false` (bandi regionali italiani – default: disattivato)
- `web_search = true/false` (ricerca web Google – default: attivato)

---

## 5. Output e report

### 5.1 Report HTML

- **Lingua**: italiano
- **Formato**: HTML standalone con CSS inline
- **Posizione**: `output/report_YYYYMMDD_HHMMSS.html`
- **Contenuto**: header, statistiche, filtri (tipo, data, fonte/ente), card opportunità, footer

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
- **Pagine SPA**: siti che caricano contenuti via JavaScript non sono analizzabili (es. TED web); per TED si usa l'API
- **Lingua**: classificazione e report sono in italiano; le fonti possono essere multilingua
- **Google Search grounding**: richiede supporto nel modello Gemini e potrebbe avere limiti di quota

---

## 7. Glossario

| Termine | Significato |
|---------|-------------|
| **TED** | Tenders Electronic Daily – banca dati UE delle gare pubbliche |
| **ANAC** | Autorità Nazionale Anticorruzione – portale dati aperti italiani |
| **CPV** | Common Procurement Vocabulary – codici classificazione appalti |
| **RSS** | Really Simple Syndication – formato per feed di notizie |
| **Resume** | Ripresa da checkpoint salvato |
| **Seed page** | Pagina "seme" che il bot visita per scoprire link a pagine specifiche di eventi o bandi |
| **WebSearch grounding** | Capacità di Gemini di accedere a Google Search per risposte basate su informazioni aggiornate |
| **Gemini Live** | API di Google per conversazioni audio bidirezionali in tempo reale con modelli AI |
| **Voice mode** | Modalità di interazione vocale con il chatbot tramite Gemini Live native audio |
| **Onboarding** | Guida introduttiva a carousel mostrata al primo accesso post-login |
