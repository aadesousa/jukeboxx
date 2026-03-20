// ─── Spotizerr Page — Spotizerr Queue & Manual Dispatch ───────────────────
const SpotizerPage = (() => {
    const root = () => document.getElementById('page-root');

    let activeTab          = 'queue';
    let pollTimer          = null;
    let queuePaused        = false;
    let candidates         = [];
    let selected           = new Set();
    let sending            = false;
    let stylesInjected     = false;

    function injectStyles() {
        if (stylesInjected) return;
        stylesInjected = true;
        const s = document.createElement('style');
        s.textContent = `
            .sp-item {
                background:var(--bg-card);border:1px solid var(--border);border-radius:10px;
                padding:12px 14px;display:grid;grid-template-columns:44px 1fr auto;gap:10px;align-items:start;
            }
            .sp-item:hover { border-color:var(--accent); }
            .sp-item.failed { border-color:#ef4444; }
            .sp-item.cooling { border-color:#f97316; }
            .sp-thumb { width:44px;height:44px;border-radius:6px;object-fit:cover;background:var(--bg-elevated);flex-shrink:0; }
            .sp-thumb-ph { width:44px;height:44px;border-radius:6px;background:var(--bg-elevated);display:flex;align-items:center;justify-content:center;font-size:1.1rem;font-weight:700;color:var(--text-dim); }
            .sp-title { font-size:.875rem;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }
            .sp-meta  { font-size:.73rem;color:var(--text-dim);margin-top:2px; }
            .sp-badges { display:flex;gap:5px;flex-wrap:wrap;margin-top:6px; }
            .badge { font-size:.68rem;padding:2px 7px;border-radius:999px;font-weight:500;border:1px solid currentColor; }
            .badge-blue   { color:#3a86ff; }
            .badge-green  { color:#22c55e; }
            .badge-orange { color:#f97316; }
            .badge-red    { color:#ef4444; }
            .badge-purple { color:#a855f7; }
            .badge-dim    { color:var(--text-dim); }
            .sp-btn { background:none;border:1px solid var(--border);border-radius:6px;padding:5px 8px;color:var(--text-dim);cursor:pointer;font-size:.75rem;white-space:nowrap; }
            .sp-btn:hover { color:var(--text);border-color:var(--text-dim); }
            .sp-btn.danger:hover { color:#ef4444;border-color:#ef4444; }
            .cand-row {
                background:var(--bg-card);border:1px solid var(--border);border-radius:10px;
                padding:12px 14px;display:grid;grid-template-columns:20px 44px 1fr auto;gap:10px;align-items:center;
                cursor:pointer;transition:border-color .15s;
            }
            .cand-row:hover { border-color:var(--accent); }
            .cand-row.selected { border-color:#a855f7;background:rgba(168,85,247,.08); }
            .cand-check { width:18px;height:18px;border-radius:4px;border:2px solid var(--border);display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all .15s; }
            .cand-row.selected .cand-check { background:#a855f7;border-color:#a855f7; }
            .dispatch-bar { background:var(--bg-card);border:1px solid var(--border);border-radius:10px;padding:12px 16px;display:flex;align-items:center;gap:12px; }
        `;
        document.head.appendChild(s);
    }

    function render() {
        injectStyles();
        root().innerHTML = `
            <div style="padding:20px;max-width:900px;margin:0 auto">
                <div style="margin-bottom:20px">
                    <h1 style="margin:0 0 4px;font-size:1.4rem;font-weight:700">Spotizerr</h1>
                    <div style="font-size:.82rem;color:var(--text-dim)">Last-resort direct Spotify download. Use only when all other sources have failed.</div>
                </div>
                <div class="tab-bar" id="sp-tabs" style="margin-bottom:20px">
                    <button class="tab-btn ${activeTab==='queue'?'active':''}" data-tab="queue">Queue</button>
                    <button class="tab-btn ${activeTab==='dispatch'?'active':''}" data-tab="dispatch">Dispatch <span class="nav-badge nav-badge-blue" id="sp-cand-badge" hidden style="position:relative;top:-1px;margin-left:2px"></span></button>
                </div>
                <div id="sp-content"></div>
            </div>`;

        document.getElementById('sp-tabs').addEventListener('click', e => {
            const btn = e.target.closest('[data-tab]');
            if (!btn) return;
            document.querySelectorAll('#sp-tabs .tab-btn').forEach(b => b.classList.toggle('active', b === btn));
            activeTab = btn.dataset.tab;
            renderTab();
        });

        renderTab();
        startPolling();
    }

    function renderTab() {
        const el = document.getElementById('sp-content');
        if (!el) return;
        if (activeTab === 'queue')    renderQueueTab(el);
        else if (activeTab === 'dispatch') renderDispatchTab(el);
    }

    // ── Queue tab ─────────────────────────────────────────────────
    function renderQueueTab(el) {
        el.innerHTML = `
            <div id="sp-dispatch-bar" style="margin-bottom:16px"></div>
            <div id="sp-active" style="margin-bottom:20px"></div>
            <div id="sp-pending"></div>`;
        loadQueueData();
    }

    async function loadQueueData() {
        try {
            const [stats, active] = await Promise.all([
                api.get('/downloads/queue-stats'),
                api.get('/downloads/active'),
            ]);
            renderDispatchBar(stats);
            renderActiveItems(active);
            renderPendingItems(active);
        } catch(e) { console.error('Spotizerr queue load error', e); }
    }

    function renderDispatchBar(data) {
        const el = document.getElementById('sp-dispatch-bar');
        if (!el) return;
        queuePaused = !!data.queue_paused;
        const nd = data.next_dispatch;
        let countdown = '';
        if (nd) {
            const diff = Math.max(0, Math.round((new Date(nd) - Date.now()) / 1000));
            countdown = diff < 60 ? `${diff}s` : `${Math.ceil(diff/60)}m`;
        }
        el.innerHTML = `
            <div class="dispatch-bar">
                <div style="flex:1;min-width:0">
                    <div style="font-size:.8rem;font-weight:600;margin-bottom:2px">
                        Dispatch \u2014 ${queuePaused ? '<span style="color:#f97316">Paused</span>' : '<span style="color:#22c55e">Running</span>'}
                    </div>
                    <div style="font-size:.73rem;color:var(--text-dim)">${queuePaused ? 'Resume to restart' : `Next run${countdown ? ' in '+countdown : ''}`}</div>
                </div>
                <button class="btn btn-sm" id="sp-dispatch-now">Dispatch Now</button>
                <button class="btn btn-sm" id="sp-pause-btn">${queuePaused ? 'Resume' : 'Pause'}</button>
            </div>`;
        document.getElementById('sp-dispatch-now')?.addEventListener('click', async () => {
            try { await api.post('/downloads/dispatch-now'); toast('Dispatch triggered', 'success'); }
            catch { toast('Failed', 'error'); }
        });
        document.getElementById('sp-pause-btn')?.addEventListener('click', async () => {
            try {
                await api.post(queuePaused ? '/downloads/queue/resume' : '/downloads/queue/pause');
                loadQueueData();
            } catch { toast('Failed', 'error'); }
        });
    }

    function renderActiveItems(data) {
        const el = document.getElementById('sp-active');
        if (!el) return;
        const items = [
            ...(data.downloading || []),
            ...(data.failed      || []),
            ...(data.cooling     || []),
        ];
        if (!items.length) {
            el.innerHTML = `<div style="color:var(--text-dim);font-size:.85rem;padding:8px 0">No active Spotizerr downloads</div>`;
            return;
        }
        el.innerHTML = `
            <div style="font-size:.8rem;font-weight:600;color:var(--text-dim);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Active (${items.length})</div>
            <div style="display:flex;flex-direction:column;gap:8px">${items.map(it => buildSpItem(it)).join('')}</div>`;
        bindItemActions(el);
    }

    function renderPendingItems(data) {
        const el = document.getElementById('sp-pending');
        if (!el) return;
        const items = (data.queued || []);
        if (!items.length) { el.innerHTML = ''; return; }
        el.innerHTML = `
            <div style="font-size:.8rem;font-weight:600;color:var(--text-dim);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Pending (${items.length})</div>
            <div style="display:flex;flex-direction:column;gap:8px">${items.slice(0,100).map(it => buildSpItem(it, true)).join('')}</div>
            ${items.length > 100 ? `<div style="font-size:.8rem;color:var(--text-dim);margin-top:8px;text-align:center">+ ${items.length-100} more</div>` : ''}`;
        bindItemActions(el);
    }

    function buildSpItem(item, isPending = false) {
        const title  = esc(item.title || item.name || 'Unknown');
        const artist = esc(item.artist || item.artist_name || '');
        const src    = esc(item.source_label || item.source || 'Spotizerr');
        const status = item.status || 'pending';
        const sc     = { downloading:'blue', pending:'dim', failed:'red', cooling:'orange', queued:'dim' };
        const img    = item.image_url;
        const thumb  = img
            ? `<img class="sp-thumb" src="${img}" alt="" onerror="this.style.display='none'">`
            : `<div class="sp-thumb-ph">${title.charAt(0)}</div>`;
        const errMsg = item.error_message
            ? `<div style="font-size:.72rem;color:#ef4444;margin-top:3px">${esc(item.error_message)}</div>` : '';
        const retry  = item.retry_count > 0
            ? `<span class="badge badge-dim">${item.retry_count} retries</span>` : '';
        return `
            <div class="sp-item ${status}">
                ${thumb}
                <div>
                    <div class="sp-title">${title}</div>
                    <div class="sp-meta">${artist}</div>
                    <div class="sp-badges">
                        <span class="badge badge-${sc[status]||'dim'}">${status}</span>
                        <span class="badge badge-purple">${src}</span>
                        ${retry}
                    </div>
                    ${errMsg}
                </div>
                <div style="display:flex;flex-direction:column;gap:5px;align-items:flex-end">
                    <button class="sp-btn danger" data-cancel-id="${item.id}" data-cancel-path="downloads" title="Cancel">\u2715</button>
                    ${!isPending && status === 'failed' ? `<button class="sp-btn" data-retry-id="${item.id}" title="Retry">\u21bb</button>` : ''}
                </div>
            </div>`;
    }

    function bindItemActions(el) {
        el.querySelectorAll('[data-cancel-id]').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (!confirm('Cancel this download?')) return;
                try {
                    await api.post(`/downloads/${btn.dataset.cancelId}/cancel`);
                    toast('Cancelled', 'info'); loadQueueData();
                } catch { toast('Cancel failed', 'error'); }
            });
        });
        el.querySelectorAll('[data-retry-id]').forEach(btn => {
            btn.addEventListener('click', async () => {
                try {
                    await api.post(`/downloads/${btn.dataset.retryId}/retry`);
                    toast('Queued for retry', 'success'); loadQueueData();
                } catch { toast('Retry failed', 'error'); }
            });
        });
    }

    // ── Dispatch tab ──────────────────────────────────────────────
    function renderDispatchTab(el) {
        selected.clear();
        el.innerHTML = `
            <div style="font-size:.85rem;color:var(--text-dim);line-height:1.5;margin-bottom:14px">
                These tracks could not be found via torrents, usenet, or Soulseek.
                Select tracks and send them to Spotizerr for direct download.
            </div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px">
                <button class="btn btn-sm" id="cand-sel-all">Select All</button>
                <button class="btn btn-sm" id="cand-sel-none" style="display:none">Deselect All</button>
                <button class="btn btn-primary" id="cand-send" disabled style="margin-left:auto">
                    Send to Spotizerr (<span id="cand-count">0</span>)
                </button>
            </div>
            <div id="cand-list" style="display:flex;flex-direction:column;gap:8px">
                <div style="color:var(--text-dim);font-size:.85rem">Loading\u2026</div>
            </div>`;

        document.getElementById('cand-sel-all').addEventListener('click', () => {
            candidates.forEach(c => selected.add(c.id));
            refreshCandidateUI();
        });
        document.getElementById('cand-sel-none').addEventListener('click', () => {
            selected.clear();
            refreshCandidateUI();
        });
        document.getElementById('cand-send').addEventListener('click', sendToSpotizerr);

        loadCandidates();
    }

    async function loadCandidates() {
        try {
            candidates = await api.get('/downloads/spotizerr-candidates');
            refreshCandidateUI(true);
        } catch(e) {
            const el = document.getElementById('cand-list');
            if (el) el.innerHTML = `<div style="color:#ef4444;font-size:.85rem">Failed: ${esc(String(e))}</div>`;
        }
    }

    function refreshCandidateUI(rebuild = false) {
        const badge  = document.getElementById('sp-cand-badge');
        const send   = document.getElementById('cand-send');
        const count  = document.getElementById('cand-count');
        const selAll = document.getElementById('cand-sel-all');
        const selNone= document.getElementById('cand-sel-none');
        const listEl = document.getElementById('cand-list');

        if (badge)   { badge.textContent = candidates.length; badge.hidden = !candidates.length; }
        if (count)   count.textContent = selected.size;
        if (send)    send.disabled = selected.size === 0 || sending;
        if (selAll)  selAll.style.display  = selected.size === candidates.length && candidates.length > 0 ? 'none' : '';
        if (selNone) selNone.style.display = selected.size > 0 ? '' : 'none';

        if (!rebuild || !listEl) return;

        if (!candidates.length) {
            listEl.innerHTML = `<div style="text-align:center;padding:40px 0;color:var(--text-dim)">
                <div style="font-size:1.1rem;margin-bottom:8px">Nothing to dispatch!</div>
                <div style="font-size:.82rem">All wanted tracks are either downloading or not yet searched</div>
            </div>`;
            return;
        }

        listEl.innerHTML = candidates.map(c => {
            const sel   = selected.has(c.id);
            const title = esc(c.name || 'Unknown');
            const artist= esc(c.artist_name || '');
            const album = esc(c.album_name || '');
            const img   = c.image_url;
            const thumb = img
                ? `<img class="sp-thumb" src="${img}" alt="" onerror="this.style.display='none'">`
                : `<div class="sp-thumb-ph">${title.charAt(0)}</div>`;
            const attempts = c.failed_attempts || 0;
            return `
                <div class="cand-row ${sel?'selected':''}" data-id="${c.id}">
                    <div class="cand-check">${sel ? '\u2713' : ''}</div>
                    ${thumb}
                    <div style="min-width:0">
                        <div class="sp-title">${title}</div>
                        <div class="sp-meta">${artist}${album?' \u00b7 '+album:''}</div>
                        ${attempts>0?`<div style="font-size:.72rem;color:#f97316;margin-top:3px">${attempts} failed auto-source attempt${attempts!==1?'s':''}</div>`:''}
                    </div>
                    <div style="font-size:.75rem;color:var(--text-dim)">${timeAgo(c.added_at)}</div>
                </div>`;
        }).join('');

        listEl.querySelectorAll('.cand-row').forEach(row => {
            row.addEventListener('click', () => {
                const id = parseInt(row.dataset.id);
                selected.has(id) ? selected.delete(id) : selected.add(id);
                refreshCandidateUI(true);
            });
        });
    }

    async function sendToSpotizerr() {
        if (sending || !selected.size) return;
        sending = true;
        const btn = document.getElementById('cand-send');
        if (btn) { btn.disabled = true; btn.textContent = 'Sending\u2026'; }
        try {
            const r = await api.post('/downloads/spotizerr-send', { monitored_track_ids: [...selected] });
            toast(`Sent ${r.sent} track${r.sent!==1?'s':''} to Spotizerr`, r.sent>0?'success':'info');
            selected.clear();
            await loadCandidates();
        } catch(e) {
            toast('Failed: '+(e.message||e), 'error');
        } finally {
            sending = false;
            const b = document.getElementById('cand-send');
            if (b) { b.disabled = false; b.innerHTML = `Send to Spotizerr (<span id="cand-count">${selected.size}</span>)`; }
        }
    }

    // ── Polling ───────────────────────────────────────────────────
    function startPolling() {
        stopPolling();
        pollTimer = setInterval(() => {
            if (activeTab === 'queue') loadQueueData();
        }, 5000);
    }
    function stopPolling() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    function load(params) {
        activeTab = params?.tab || 'queue';
        selected.clear();
        candidates = [];
        render();
    }
    function unload() { stopPolling(); }

    return { load, unload };
})();
