// ─── Logs Page ────────────────────────────────────────────────────
const LogsPage = (() => {
    const root = () => document.getElementById('page-root');

    let currentLevel = 'all';
    let offset = 0;
    const LIMIT = 100;
    const LEVELS = ['all', 'info', 'warning', 'error'];

    async function load(params) {
        currentLevel = 'all';
        offset = 0;

        root().innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1.2rem;padding:24px 24px 0">
            <h1 style="margin:0;font-size:1.4rem;font-weight:300">Logs</h1>
            <div style="display:flex;gap:8px;align-items:center">
                <span id="logs-count" style="color:var(--text-muted);font-size:.85rem"></span>
                <div style="display:flex;gap:4px">
                    ${LEVELS.map(l => `<button class="btn btn-sm level-filter-btn ${l === currentLevel ? 'btn-primary' : 'btn-secondary'}" data-level="${l}">${l.charAt(0).toUpperCase()+l.slice(1)}</button>`).join('')}
                </div>
                <button class="btn btn-sm btn-danger" id="clear-logs-btn">Clear All</button>
            </div>
        </div>
        <div style="overflow-x:auto;padding:0 24px">
            <table class="arr-table" style="width:100%">
                <thead><tr>
                    <th style="width:160px">Time</th>
                    <th style="width:160px">Action</th>
                    <th>Detail</th>
                </tr></thead>
                <tbody id="logs-tbody"><tr><td colspan="3" style="text-align:center;padding:2rem">Loading…</td></tr></tbody>
            </table>
        </div>
        <div style="text-align:center;margin-top:1rem;padding-bottom:2rem">
            <button class="btn btn-secondary" id="logs-load-more" style="display:none">Load More</button>
        </div>`;

        root().addEventListener('click', async e => {
            const lvlBtn = e.target.closest('.level-filter-btn');
            if (lvlBtn) {
                currentLevel = lvlBtn.dataset.level;
                offset = 0;
                root().querySelectorAll('.level-filter-btn').forEach(b => {
                    b.classList.toggle('btn-primary', b.dataset.level === currentLevel);
                    b.classList.toggle('btn-secondary', b.dataset.level !== currentLevel);
                });
                await loadLogs();
            }
            if (e.target.id === 'logs-load-more') await loadLogs(true);
            if (e.target.id === 'clear-logs-btn') {
                if (!confirm('Clear all log entries?')) return;
                await api.del('/logs');
                offset = 0;
                await loadLogs();
            }
        });

        await loadLogs();
    }

    function unload() {}

    async function loadLogs(append = false) {
        if (!append) offset = 0;
        const qs = new URLSearchParams({ limit: LIMIT, offset, level: currentLevel });
        try {
            const data = await api.get('/logs?' + qs);
            const tbody = document.getElementById('logs-tbody');
            if (!tbody) return;
            const html = (data.logs || []).map(l => {
                const action = (l.action || '').toLowerCase();
                const ts = l.created_at ? new Date(l.created_at).toLocaleString() : '';
                return `<tr>
                    <td style="white-space:nowrap;color:var(--text-muted);font-size:.8rem">${ts}</td>
                    <td style="color:var(--text-dim);font-size:.8rem;font-weight:500">${esc(l.action || '')}</td>
                    <td style="word-break:break-word;font-size:.85rem">${esc(l.detail || '')}</td>
                </tr>`;
            }).join('');
            if (append) {
                tbody.insertAdjacentHTML('beforeend', html || '');
            } else {
                tbody.innerHTML = html || '<tr><td colspan="3" style="text-align:center;color:var(--text-muted);padding:2rem">No log entries</td></tr>';
            }
            const countEl = document.getElementById('logs-count');
            if (countEl) countEl.textContent = `${data.total} entries`;
            const btn = document.getElementById('logs-load-more');
            const currentOffset = append ? offset + (data.logs || []).length : (data.logs || []).length;
            if (btn) btn.style.display = (currentOffset < data.total) ? '' : 'none';
            if (!append) offset = (data.logs || []).length;
            else offset += (data.logs || []).length;
        } catch (e) {
            const tbody = document.getElementById('logs-tbody');
            if (tbody) tbody.innerHTML = `<tr><td colspan="3" style="color:var(--red);padding:1rem">Failed to load logs: ${esc(e.message)}</td></tr>`;
        }
    }

    return { load, unload };
})();
