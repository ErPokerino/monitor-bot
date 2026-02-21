/* Alpine.js components and WebSocket client for Monitor Bot */

const STAGE_NAMES = {
    1: 'Raccolta dati',
    2: 'Deduplicazione',
    3: 'Filtro scaduti',
    4: 'Classificazione AI',
    5: 'Arricchimento date',
    6: 'Finalizzazione',
};

/* ----------------------------------------------------------------
 * Sources page
 * ---------------------------------------------------------------- */

function sourcesManager() {
    return {
        showAdd: false,
        showEdit: false,
        editId: null,
        filter: 'all',
        form: { name: '', url: '', category: 'eventi', source_type: 'web_page' },

        init() {
            this.$el.addEventListener('edit-source', (e) => {
                this.editId = e.detail.id;
                this.form = {
                    name: e.detail.name,
                    url: e.detail.url,
                    category: e.detail.category,
                    source_type: e.detail.sourceType,
                };
                this.showEdit = true;
            });
        },

        closeModals() {
            this.showAdd = false;
            this.showEdit = false;
            this.editId = null;
            this.form = { name: '', url: '', category: 'eventi', source_type: 'web_page' };
        },

        async addSource() {
            const resp = await fetch('/api/sources', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.form),
            });
            if (resp.ok) {
                this.closeModals();
                location.reload();
            } else {
                const err = await resp.json();
                alert(err.detail || 'Errore durante il salvataggio');
            }
        },

        async updateSource() {
            const resp = await fetch(`/api/sources/${this.editId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.form),
            });
            if (resp.ok) {
                this.closeModals();
                location.reload();
            } else {
                const err = await resp.json();
                alert(err.detail || 'Errore durante l\'aggiornamento');
            }
        },
    };
}

function sourceRow(id, initialActive, initialName, initialUrl, initialCategory, initialSourceType) {
    return {
        id,
        active: initialActive,
        name: initialName,
        url: initialUrl,
        category: initialCategory,
        sourceType: initialSourceType,

        async toggle() {
            const resp = await fetch(`/api/sources/${id}/toggle`, { method: 'POST' });
            if (resp.ok) {
                const data = await resp.json();
                this.active = data.is_active;
            }
        },

        async remove() {
            if (!confirm('Eliminare questa fonte?')) return;
            const resp = await fetch(`/api/sources/${id}`, { method: 'DELETE' });
            if (resp.ok) {
                this.$el.remove();
            }
        },
    };
}

/* ----------------------------------------------------------------
 * Queries page
 * ---------------------------------------------------------------- */

function queriesManager() {
    return {
        showAdd: false,
        showEdit: false,
        editId: null,
        filter: 'all',
        form: { query_text: '', category: 'bandi', max_results: 5 },

        init() {
            this.$el.addEventListener('edit-query', (e) => {
                this.editId = e.detail.id;
                this.form = {
                    query_text: e.detail.queryText,
                    category: e.detail.category,
                    max_results: e.detail.maxResults,
                };
                this.showEdit = true;
            });
        },

        closeModals() {
            this.showAdd = false;
            this.showEdit = false;
            this.editId = null;
            this.form = { query_text: '', category: 'bandi', max_results: 5 };
        },

        async addQuery() {
            const resp = await fetch('/api/queries', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.form),
            });
            if (resp.ok) {
                this.closeModals();
                location.reload();
            } else {
                const err = await resp.json();
                alert(err.detail || 'Errore durante il salvataggio');
            }
        },

        async updateQuery() {
            const resp = await fetch(`/api/queries/${this.editId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.form),
            });
            if (resp.ok) {
                this.closeModals();
                location.reload();
            } else {
                const err = await resp.json();
                alert(err.detail || 'Errore durante l\'aggiornamento');
            }
        },
    };
}

function queryRow(id, initialActive, initialQueryText, initialCategory, initialMaxResults) {
    return {
        id,
        active: initialActive,
        queryText: initialQueryText,
        category: initialCategory,
        maxResults: initialMaxResults,

        async toggle() {
            const resp = await fetch(`/api/queries/${id}/toggle`, { method: 'POST' });
            if (resp.ok) {
                const data = await resp.json();
                this.active = data.is_active;
            }
        },

        async remove() {
            if (!confirm('Eliminare questa ricerca?')) return;
            const resp = await fetch(`/api/queries/${id}`, { method: 'DELETE' });
            if (resp.ok) {
                this.$el.remove();
            }
        },
    };
}

/* ----------------------------------------------------------------
 * Pipeline runner (run page)
 * ---------------------------------------------------------------- */

function pipelineRunner(isRunning, currentRunId) {
    return {
        state: isRunning ? 'running' : 'idle',
        runId: currentRunId,
        ws: null,
        stopping: false,
        stageLabel: 'Inizializzazione...',
        overallPct: 0,
        itemCurrent: 0,
        itemTotal: 0,
        itemLabel: '',
        finishSummary: '',
        stages: Object.entries(STAGE_NAMES).map(([id, name]) => ({
            id: parseInt(id),
            name,
            status: 'pending',
            summary: '',
        })),

        init() {
            if (this.state === 'running') {
                this.connectWs();
            }
        },

        async start() {
            this.state = 'running';
            this.stopping = false;
            this.resetStages();

            const resp = await fetch('/api/runs/start', { method: 'POST' });
            if (!resp.ok) {
                const err = await resp.json();
                this.state = 'error';
                this.finishSummary = err.detail || 'Errore avvio pipeline';
                return;
            }
            const data = await resp.json();
            this.runId = data.id;
            this.connectWs();
        },

        async stop() {
            if (this.stopping) return;
            this.stopping = true;
            const resp = await fetch('/api/runs/stop', { method: 'POST' });
            if (!resp.ok) {
                this.stopping = false;
            }
        },

        connectWs() {
            const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            this.ws = new WebSocket(`${proto}//${location.host}/api/runs/ws`);

            this.ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                this.handleWsMessage(msg);
            };

            this.ws.onclose = () => {
                if (this.state === 'running') {
                    setTimeout(() => this.connectWs(), 2000);
                }
            };
        },

        handleWsMessage(msg) {
            switch (msg.type) {
                case 'stage_begin':
                    this.stages = this.stages.map(s =>
                        s.id === msg.stage ? { ...s, status: 'running', summary: msg.detail } : s
                    );
                    this.stageLabel = `${STAGE_NAMES[msg.stage] || 'Fase ' + msg.stage} - ${msg.detail}`;
                    this.overallPct = Math.round(((msg.stage - 1) / msg.total_stages) * 100);
                    this.itemCurrent = 0;
                    this.itemTotal = 0;
                    break;

                case 'stage_end':
                    this.stages = this.stages.map(s =>
                        s.id === msg.stage ? { ...s, status: 'done', summary: msg.summary } : s
                    );
                    this.overallPct = Math.round((msg.stage / msg.total_stages) * 100);
                    break;

                case 'item_progress':
                    this.itemCurrent = msg.current;
                    this.itemTotal = msg.total;
                    this.itemLabel = msg.label;
                    break;

                case 'finished':
                    this.state = this.stopping ? 'cancelled' : 'completed';
                    this.overallPct = this.stopping ? this.overallPct : 100;
                    this.finishSummary = msg.summary;
                    this.stopping = false;
                    if (this.ws) this.ws.close();
                    break;
            }
        },

        reset() {
            this.state = 'idle';
            this.runId = null;
            this.overallPct = 0;
            this.finishSummary = '';
            this.itemCurrent = 0;
            this.itemTotal = 0;
            this.resetStages();
        },

        resetStages() {
            this.stages = Object.entries(STAGE_NAMES).map(([id, name]) => ({
                id: parseInt(id),
                name,
                status: 'pending',
                summary: '',
            }));
        },
    };
}
