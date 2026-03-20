// ─── Activity Page — Live Download Client Status & History ────────────────
const ActivityPage = (() => {
    const root = () => document.getElementById('page-root');

    let activeTab    = 'qbittorrent';
    let pollTimer    = null;
    let liveData     = null;
    let sortState    = { qbittorrent: 'date', sabnzbd: 'name', slskd: 'name', youtube: 'date' };
    let sortDir      = { qbittorrent: 'desc', sabnzbd: 'asc', slskd: 'asc', youtube: 'desc' };
    let historyFilter = 'all';
    let stylesInjected = false;

    function injectStyles() {
        if (stylesInjected) return;
        stylesInjected = true;
        const s = document.createElement('style');
        s.textContent = `
            @keyframes shimmer {
                0%   { background-position: -400px 0; }
                100% { background-position:  400px 0; }
            }
            .progress-rainbow {
                background: linear-gradient(90deg,#ff006e 0%,#8338ec 25%,#3a86ff 50%,#06d6a0 75%,#ffd166 100%);
            }
            .progress-indeterminate {
                background: linear-gradient(90deg,transparent 0%,#8338ec 20%,#3a86ff 40%,#06d6a0 60%,#a855f7 80%,transparent 100%);
                background-size:400px 100%;
                animation:shimmer 1.4s linear infinite;
            }
            .live-card {
                background:var(--bg-card);border:1px solid var(--border);
                border-radius:10px;padding:12px 14px;
                transition:border-color .15s;
            }
            .live-card:hover { border-color:var(--accent); }
            .live-card.stalled { border-color:var(--text-dim); opacity:0.75; }
            .live-card-title { font-size:.875rem;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }
            .live-card-meta  { font-size:.73rem;color:var(--text-dim);margin-top:2px; }
            .live-progress { height:4px;background:var(--bg-elevated);border-radius:999px;overflow:hidden;margin-top:8px; }
            .live-progress-bar { height:100%;border-radius:999px;transition:width .4s; }
            .badge { font-size:.68rem;padding:2px 7px;border-radius:999px;font-weight:500;border:1px solid currentColor; }
            .badge-blue   { color:#3a86ff; }
            .badge-green  { color:#22c55e; }
            .badge-orange { color:#f97316; }
            .badge-red    { color:#ef4444; }
            .badge-purple { color:#a855f7; }
            .badge-dim    { color:var(--text-dim); }
            .sort-btn { background:none;border:1px solid var(--border);border-radius:5px;padding:3px 9px;font-size:.75rem;color:var(--text-dim);cursor:pointer; }
            .sort-btn.active { border-color:var(--accent);color:var(--accent); }
            .sort-btn:hover { border-color:var(--text-dim);color:var(--text); }
        `;
        document.head.appendChild(s);
    }

    // ── Scaffold ──────────────────────────────────────────────────
    function render() {
        injectStyles();
        root().innerHTML = `
            <div style="padding:20px;max-width:960px;margin:0 auto">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
                    <h1 style="margin:0;font-size:1.4rem;font-weight:700">Live Downloads</h1>
                    <button class="btn btn-sm" id="act-refresh">↻ Refresh</button>
                </div>
                <div class="tab-bar" id="act-tabs" style="margin-bottom:20px">
                    <button class="tab-btn ${activeTab==='qbittorrent'?'active':''}" data-tab="qbittorrent">qBittorrent</button>
                    <button class="tab-btn ${activeTab==='sabnzbd'?'active':''}" data-tab="sabnzbd">SABnzbd</button>
                    <button class="tab-btn ${activeTab==='slskd'?'active':''}" data-tab="slskd">Soulseek</button>
                    <button class="tab-btn ${activeTab==='youtube'?'active':''}" data-tab="youtube">YouTube</button>
                    <button class="tab-btn ${activeTab==='history'?'active':''}" data-tab="history">History</button>
                </div>
                <div id="act-content"></div>
            </div>`;

        document.getElementById('act-tabs').addEventListener('click', e => {
            const btn = e.target.closest('[data-tab]');
            if (!btn) return;
            document.querySelectorAll('#act-tabs .tab-btn').forEach(b =>
                b.classList.toggle('active', b === btn));
            activeTab = btn.dataset.tab;
            renderTab();
        });

        document.getElementById('act-refresh').addEventListener('click', refreshCurrent);
        renderTab();
        startPolling();
    }

    function renderTab() {
        const el = document.getElementById('act-content');
        if (!el) return;
        if (activeTab === 'history') renderHistoryTab(el);
        else renderClientTab(el, activeTab);
    }

    async function refreshCurrent() {
        if (activeTab === 'history') return;
        try {
            liveData = await api.get('/downloads/live-status');
            renderClientTab(document.getElementById('act-content'), activeTab);
        } catch (e) {
            console.error('Live status refresh error', e);
        }
    }

    // ── Client tabs ───────────────────────────────────────────────
    function renderClientTab(el, client) {
        if (!liveData) {
            el.innerHTML = `<div style="color:var(--text-dim);font-size:.85rem">Loading…</div>`;
            loadLive(el, client);
            return;
        }
        buildClientUI(el, client, liveData);
    }

    async function loadLive(el, client) {
        try {
            liveData = await api.get('/downloads/live-status');
            if (activeTab === client) buildClientUI(el, client, liveData);
        } catch(e) {
            el.innerHTML = `<div style="color:#ef4444;font-size:.85rem">Failed to load: ${esc(String(e))}</div>`;
        }
    }

    function buildClientUI(el, client, data) {
        const items = (data[client] || []);
        const err   = data[client + '_error'];

        if (client === 'qbittorrent') renderQbit(el, items, err);
        else if (client === 'sabnzbd') renderSab(el, items, err);
        else if (client === 'slskd')   renderSlskd(el, items, err);
        else if (client === 'youtube') renderYoutube(el, items, err);
    }

    // ── Sort helpers ──────────────────────────────────────────────
    function sortItems(items, client) {
        const key = sortState[client];
        const dir = sortDir[client] === 'asc' ? 1 : -1;
        return [...items].sort((a, b) => {
            let av, bv;
            if (client === 'qbittorrent') {
                if (key === 'name')     { av = a.name.toLowerCase(); bv = b.name.toLowerCase(); }
                else if (key === 'progress') { av = a.progress; bv = b.progress; }
                else if (key === 'speed')    { av = a.dlspeed; bv = b.dlspeed; }
                else if (key === 'status')   { av = a.state; bv = b.state; }
                else { av = a.added_on; bv = b.added_on; } // date
            } else if (client === 'sabnzbd') {
                if (key === 'progress') { av = a.progress; bv = b.progress; }
                else if (key === 'status') { av = a.status; bv = b.status; }
                else { av = a.name.toLowerCase(); bv = b.name.toLowerCase(); } // name
            } else { // slskd
                if (key === 'progress') { av = a.progress; bv = b.progress; }
                else if (key === 'speed') { av = a.average_speed; bv = b.average_speed; }
                else if (key === 'state') { av = a.state; bv = b.state; }
                else { av = a.filename.toLowerCase(); bv = b.filename.toLowerCase(); } // name
            }
            if (av < bv) return -1 * dir;
            if (av > bv) return  1 * dir;
            return 0;
        });
    }

    function sortBar(client, keys) {
        return `<div style="display:flex;gap:5px;align-items:center">
            <span style="font-size:.73rem;color:var(--text-dim);margin-right:2px">Sort:</span>
            ${keys.map(([k, label]) => `
                <button class="sort-btn ${sortState[client]===k?'active':''}" data-sort="${k}" data-client="${client}">
                    ${label}${sortState[client]===k ? (sortDir[client]==='asc'?' ↑':' ↓') : ''}
                </button>`).join('')}
        </div>`;
    }

    function bindSortBtns(el, client, rerender) {
        el.querySelectorAll(`[data-sort][data-client="${client}"]`).forEach(btn => {
            btn.addEventListener('click', () => {
                const k = btn.dataset.sort;
                if (sortState[client] === k) {
                    sortDir[client] = sortDir[client] === 'asc' ? 'desc' : 'asc';
                } else {
                    sortState[client] = k;
                    sortDir[client] = 'asc';
                }
                rerender();
            });
        });
    }

    // ── qBittorrent ───────────────────────────────────────────────
    function renderQbit(el, items, err) {
        const now = Date.now() / 1000;
        // Hide seeding torrents — they're done, qBit handles them
        items = items.filter(t => !['uploading','stalledUP'].includes(t.state));
        const totalCount = items.length;
        items = items.map(t => {
            const isStalled = (
                ['stalledDL','error','missingFiles','pausedDL'].includes(t.state) ||
                (t.state === 'metaDL' && (now - t.added_on) > 10)
            );
            return {...t, isStalled};
        });

        const stalled = items.filter(t => t.isStalled);
        const sorted  = sortItems(items, 'qbittorrent');

        const stateLabel = { downloading:'Downloading', stalledDL:'Stalled', stalledUP:'Seeding (Stalled)', uploading:'Seeding', checkingDL:'Checking', pausedDL:'Paused', metaDL:'Fetching Metadata', error:'Error', missingFiles:'Missing Files', queuedDL:'Queued' };

        el.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px">
                ${sortBar('qbittorrent', [['date','Date Added'],['name','Name'],['progress','Progress'],['speed','Speed'],['status','Status']])}
                <div style="display:flex;gap:8px;align-items:center">
                    <span style="font-size:.75rem;color:var(--text-dim)">${totalCount} torrent${totalCount !== 1 ? 's' : ''}</span>
                    ${stalled.length ? `<button class="btn btn-sm" id="qbit-clear-stalled" style="color:var(--text-dim);border-color:var(--text-dim)">
                        Remove ${stalled.length} Stalled
                    </button>` : ''}
                    ${err ? `<span style="font-size:.75rem;color:#ef4444">⚠ ${esc(err)}</span>` : ''}
                </div>
            </div>
            ${!items.length ? `<div style="text-align:center;padding:40px 0;color:var(--text-dim)">No music torrents in queue</div>` : ''}
            <div style="display:flex;flex-direction:column;gap:8px" id="qbit-list">
                ${sorted.map(t => {
                    const sl = stateLabel[t.state] || t.state;
                    const speed = t.dlspeed > 0 ? (t.dlspeed/1024).toFixed(0)+' KB/s' : '';
                    const eta   = t.eta > 0 && t.eta < 8640000 ? fmtEta(t.eta) : '';
                    const badgeColor = {
                        downloading:'blue', checkingDL:'blue', queuedDL:'blue',
                        uploading:'green', stalledUP:'dim',
                        stalledDL:'dim', pausedDL:'dim', metaDL:'dim',
                        error:'red', missingFiles:'red',
                    }[t.state] ?? 'dim';
                    const pct = t.progress;
                    const isIndet = !t.isStalled && (t.state === 'metaDL' || pct === 0);
                    return `
                        <div class="live-card ${t.isStalled ? 'stalled' : ''}">
                            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
                                <div style="min-width:0;flex:1">
                                    <div class="live-card-title">${esc(t.name)}</div>
                                    <div class="live-card-meta">
                                        <span class="badge badge-${badgeColor}" style="margin-right:5px">${sl}</span>
                                        ${speed ? speed + ' · ' : ''}${t.num_seeds} seeds${eta ? ' · ETA '+eta : ''}
                                    </div>
                                </div>
                                <div style="font-size:.8rem;color:var(--text-dim);white-space:nowrap">${pct}%</div>
                            </div>
                            <div class="live-progress">
                                <div class="live-progress-bar ${isIndet ? 'progress-indeterminate' : 'progress-rainbow'}"
                                     style="width:${isIndet ? '100%' : pct+'%'}"></div>
                            </div>
                        </div>`;
                }).join('')}
            </div>`;

        bindSortBtns(el, 'qbittorrent', () => renderQbit(el, liveData?.qbittorrent || [], liveData?.qbittorrent_error));

        document.getElementById('qbit-clear-stalled')?.addEventListener('click', async () => {
            if (!confirm(`Remove ${stalled.length} stalled torrent${stalled.length !== 1 ? 's' : ''} from qBittorrent and blocklist them?`)) return;
            const btn = document.getElementById('qbit-clear-stalled');
            btn.disabled = true; btn.textContent = 'Removing\u2026';
            try {
                const r = await api.post('/downloads/qbittorrent/clear-stalled');
                toast(`Removed ${r.removed} stalled torrent${r.removed !== 1 ? 's' : ''}`, 'success');
                liveData = await api.get('/downloads/live-status');
                renderQbit(el, liveData.qbittorrent || [], liveData.qbittorrent_error);
            } catch(e) { toast('Failed: ' + (e.message || e), 'error'); btn.disabled = false; }
        });
    }

    // ── SABnzbd ───────────────────────────────────────────────────
    function renderSab(el, items, err) {
        const sorted = sortItems(items, 'sabnzbd');
        const statusColors = { Downloading:'blue', Paused:'dim', Queued:'dim', Fetching:'blue', Verifying:'purple', Repairing:'purple', Extracting:'purple', Failed:'red' };

        el.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px">
                ${sortBar('sabnzbd', [['name','Name'],['progress','Progress'],['status','Status']])}
                <span style="font-size:.75rem;color:var(--text-dim)">${items.length} item${items.length !== 1 ? 's' : ''}${err ? ` · <span style="color:#ef4444">⚠ ${esc(err)}</span>` : ''}</span>
            </div>
            ${!items.length ? `<div style="text-align:center;padding:40px 0;color:var(--text-dim)">No items in SABnzbd queue</div>` : ''}
            <div style="display:flex;flex-direction:column;gap:8px">
                ${sorted.map(s => `
                    <div class="live-card">
                        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
                            <div style="min-width:0;flex:1">
                                <div class="live-card-title">${esc(s.name)}</div>
                                <div class="live-card-meta">
                                    <span class="badge badge-${statusColors[s.status]||'dim'}" style="margin-right:5px">${esc(s.status)}</span>
                                    ${s.size_mb ? s.size_mb.toFixed(0)+' MB' : ''}${s.eta ? ' · '+esc(s.eta) : ''}
                                </div>
                            </div>
                            <div style="font-size:.8rem;color:var(--text-dim);white-space:nowrap">${s.progress}%</div>
                        </div>
                        <div class="live-progress">
                            <div class="live-progress-bar progress-rainbow" style="width:${s.progress}%"></div>
                        </div>
                    </div>`).join('')}
            </div>`;

        bindSortBtns(el, 'sabnzbd', () => renderSab(el, liveData?.sabnzbd || [], liveData?.sabnzbd_error));
    }

    // ── Soulseek ─────────────────────────────────────────────────
    function renderSlskd(el, items, err) {
        items = items.filter(f => !f.state.includes('Completed'));
        const sorted = sortItems(items, 'slskd');
        const stalled = items.filter(f => f.state.includes('Queued') || f.state === 'Requested' || f.state === 'Initializing');

        const slskStateLabel = s => {
            if (s.includes('InProgress')) return 'Downloading';
            if (s.includes('Queued'))     return 'Waiting';
            if (s.includes('Initializ'))  return 'Connecting';
            return s;
        };
        const stateColor = s => s.includes('InProgress') ? 'blue' : s.includes('Queued') ? 'orange' : s.includes('Initializ') ? 'dim' : 'orange';

        const ageStr = iso => {
            if (!iso) return '';
            const secs = (Date.now() - new Date(iso).getTime()) / 1000;
            if (secs < 60) return Math.round(secs) + 's';
            if (secs < 3600) return Math.round(secs/60) + 'm';
            return (secs/3600).toFixed(1) + 'h';
        };

        el.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px">
                ${sortBar('slskd', [['name','Name'],['progress','Progress'],['speed','Speed'],['state','State']])}
                <div style="display:flex;gap:8px;align-items:center">
                    <span style="font-size:.75rem;color:var(--text-dim)">${items.length} file${items.length !== 1 ? 's' : ''}${err ? ` · <span style="color:#ef4444">⚠ ${esc(err)}</span>` : ''}</span>
                    ${stalled.length ? `<button class="btn btn-sm" id="slskd-cancel-stalled" style="color:#f97316;border-color:#f97316">Cancel ${stalled.length} Waiting</button>` : ''}
                </div>
            </div>
            ${!items.length ? `<div style="text-align:center;padding:40px 0;color:var(--text-dim)">No active Soulseek transfers</div>` : ''}
            <div style="display:flex;flex-direction:column;gap:8px">
                ${sorted.map(f => {
                    const speed = f.average_speed > 0 ? (f.average_speed/1024).toFixed(0)+' KB/s' : '';
                    const age = ageStr(f.enqueued_at);
                    const isActive = f.state.includes('InProgress');
                    return `
                        <div class="live-card${f.state.includes('Queued') ? ' stalled' : ''}">
                            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
                                <div style="min-width:0;flex:1">
                                    <div class="live-card-title">${esc(f.filename)}</div>
                                    <div class="live-card-meta">
                                        <span class="badge badge-${stateColor(f.state)}" style="margin-right:5px">${esc(slskStateLabel(f.state))}</span>
                                        ${esc(f.username)}${speed ? ' · '+speed : ''}${age ? ' · waiting '+age : ''}
                                    </div>
                                </div>
                                <div style="display:flex;align-items:center;gap:8px;flex-shrink:0">
                                    <div style="font-size:.8rem;color:var(--text-dim);white-space:nowrap">${f.progress}%</div>
                                    ${f.id && f.state.includes('Queued') ? `<button class="btn-xs slskd-cancel-one" data-id="${esc(f.id)}" data-user="${esc(f.username)}" style="color:#ef4444;border-color:#ef4444">✕</button>` : ''}
                                </div>
                            </div>
                            ${isActive ? `
                            <div class="live-progress" style="margin-top:8px">
                                <div class="live-progress-bar progress-rainbow" style="width:${f.progress}%"></div>
                            </div>` : ''}
                        </div>`;
                }).join('')}
            </div>`;

        bindSortBtns(el, 'slskd', () => renderSlskd(el, liveData?.slskd || [], liveData?.slskd_error));

        document.getElementById('slskd-cancel-stalled')?.addEventListener('click', async btn => {
            const b = document.getElementById('slskd-cancel-stalled');
            if (b) b.disabled = true;
            try {
                const r = await api.post('/downloads/slskd/cancel-stalled');
                toast(`Cancelled ${r.cancelled} waiting transfer${r.cancelled !== 1 ? 's' : ''}`, 'info');
                liveData = await api.get('/downloads/live-status');
                renderSlskd(el, liveData?.slskd || [], liveData?.slskd_error);
            } catch(e) { toast('Cancel failed: ' + e.message, 'error'); if (b) b.disabled = false; }
        });

        el.querySelectorAll('.slskd-cancel-one').forEach(btn => {
            btn.addEventListener('click', async () => {
                btn.disabled = true;
                try {
                    await api.post('/downloads/slskd/cancel-stalled');
                    liveData = await api.get('/downloads/live-status');
                    renderSlskd(el, liveData?.slskd || [], liveData?.slskd_error);
                } catch(e) { toast('Cancel failed: ' + e.message, 'error'); btn.disabled = false; }
            });
        });
    }

    // ── YouTube (MeTube) ─────────────────────────────────────────
    function renderYoutube(el, items, err) {
        // Active first, then by timestamp desc
        const active = items.filter(f => f.status === 'downloading' || f.status === 'queued' || f.status === 'pending');
        const done   = items.filter(f => f.status === 'finished');
        const failed = items.filter(f => f.status === 'error');
        const sorted = [...active, ...failed, ...done];

        const badgeClass = s => s === 'finished' ? 'badge-green' : s === 'error' ? 'badge-red' : s === 'downloading' ? 'badge-blue' : 'badge-yellow';
        const badgeLabel = s => s === 'finished' ? 'Done' : s === 'error' ? 'Error' : s === 'downloading' ? 'Downloading' : s === 'queued' ? 'Queued' : s;

        el.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:12px">
                <span style="font-size:.75rem;color:var(--text-dim)">${sorted.length} item${sorted.length !== 1 ? 's' : ''} in MeTube${err ? ` · <span style="color:#ef4444">⚠ ${esc(err)}</span>` : ''}</span>
            </div>
            ${!sorted.length
                ? `<div style="text-align:center;padding:40px 0;color:var(--text-dim)">No YouTube downloads yet</div>`
                : `<div style="display:flex;flex-direction:column;gap:8px">
                    ${sorted.map(f => {
                        const isActive = f.status === 'downloading';
                        const pct = f.percent ?? 0;
                        const metaparts = [];
                        if (f.url) metaparts.push(esc(f.url));
                        if (f.filename) metaparts.push(esc(f.filename));
                        const speedStr = f.speed ? (f.speed > 1048576 ? (f.speed/1048576).toFixed(1)+' MB/s' : (f.speed/1024).toFixed(0)+' KB/s') : '';
                        const etaStr = f.eta ? fmtEta(f.eta) : '';
                        const tsStr = f.timestamp ? timeAgo(new Date(f.timestamp * 1000).toISOString()) : '';
                        return `<div class="live-card">
                            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
                                <div style="min-width:0;flex:1">
                                    <div class="live-card-title">${esc(f.title || f.url || '—')}</div>
                                    ${metaparts.length ? `<div class="live-card-meta" style="font-size:.7rem">${metaparts.join(' · ')}</div>` : ''}
                                    ${f.error ? `<div style="font-size:.7rem;color:#ef4444;margin-top:2px">${esc(f.error)}</div>` : ''}
                                </div>
                                <div style="display:flex;align-items:center;gap:8px;flex-shrink:0">
                                    ${speedStr ? `<span style="font-size:.72rem;color:var(--text-dim)">${speedStr}</span>` : ''}
                                    ${etaStr ? `<span style="font-size:.72rem;color:var(--text-dim)">ETA ${etaStr}</span>` : ''}
                                    <span class="badge ${badgeClass(f.status)}">${badgeLabel(f.status)}</span>
                                    ${tsStr ? `<span style="font-size:.72rem;color:var(--text-dim)">${tsStr}</span>` : ''}
                                </div>
                            </div>
                            ${isActive || (pct > 0 && pct < 100) ? `
                            <div style="display:flex;align-items:center;gap:8px;margin-top:6px">
                                <div style="font-size:.8rem;color:var(--text-dim);white-space:nowrap">${pct.toFixed(1)}%</div>
                            </div>
                            <div class="live-progress">
                                <div class="live-progress-bar progress-rainbow" style="width:${pct}%"></div>
                            </div>` : ''}
                        </div>`;
                    }).join('')}
                   </div>`}`;
    }

    function fmtEta(secs) {
        if (secs >= 3600) return Math.floor(secs/3600)+'h '+Math.floor((secs%3600)/60)+'m';
        if (secs >= 60)   return Math.floor(secs/60)+'m';
        return secs+'s';
    }

    // ── History tab ───────────────────────────────────────────────
    function renderHistoryTab(el) {
        el.innerHTML = `
            <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:14px">
                ${['all','completed','failed','cancelled'].map(f =>
                    `<button class="btn btn-sm ${historyFilter===f?'btn-primary':''}" data-hfilter="${f}">${f.charAt(0).toUpperCase()+f.slice(1)}</button>`
                ).join('')}
                <button class="btn btn-sm" id="hist-clear-failed" style="margin-left:auto;color:#ef4444;border-color:#ef4444">Clear Failed</button>
            </div>
            <div id="hist-count" style="font-size:.75rem;color:var(--text-dim);margin-bottom:10px"></div>
            <div id="hist-list" style="display:flex;flex-direction:column;gap:8px"></div>`;

        el.querySelectorAll('[data-hfilter]').forEach(btn => {
            btn.addEventListener('click', () => {
                historyFilter = btn.dataset.hfilter;
                el.querySelectorAll('[data-hfilter]').forEach(b =>
                    b.classList.toggle('btn-primary', b === btn));
                loadHistory(el);
            });
        });
        document.getElementById('hist-clear-failed')?.addEventListener('click', async () => {
            if (!confirm('Clear all failed download records? Affected tracks will be reset to Wanted.')) return;
            try {
                const r = await api.post('/downloads/clear-failed');
                const msg = r.tracks_reset > 0
                    ? `Cleared ${r.deleted} failed · ${r.tracks_reset} track${r.tracks_reset !== 1 ? 's' : ''} reset to Wanted`
                    : `Cleared ${r.deleted} failed downloads`;
                toast(msg, 'info');
                loadHistory(el);
            } catch { toast('Failed', 'error'); }
        });
        loadHistory(el);
    }

    async function loadHistory(el) {
        const listEl = document.getElementById('hist-list');
        if (!listEl) return;
        listEl.innerHTML = `<div style="color:var(--text-dim);font-size:.85rem">Loading\u2026</div>`;
        try {
            const [legacy, unified] = await Promise.all([
                api.get('/downloads/history?limit=100'),
                api.get('/downloads/unified/history?limit=100'),
            ]);
            let rows = [
                ...legacy.map(r => ({...r, _tbl:'legacy'})),
                ...unified.map(r => ({...r, _tbl:'unified'})),
            ].sort((a,b) => new Date(b.updated_at) - new Date(a.updated_at));

            if (historyFilter !== 'all') rows = rows.filter(r => r.status === historyFilter);

            if (!rows.length) {
                listEl.innerHTML = `<div style="color:var(--text-dim);font-size:.85rem;padding:20px 0;text-align:center">No history</div>`;
                const countEl = document.getElementById('hist-count');
                if (countEl) countEl.textContent = '';
                return;
            }
            const countEl = document.getElementById('hist-count');
            if (countEl) countEl.textContent = `${rows.length} record${rows.length !== 1 ? 's' : ''} · sorted by date completed`;
            const statusColor = { completed:'green', failed:'red', cancelled:'dim', pending:'blue', downloading:'blue' };
            listEl.innerHTML = rows.slice(0,100).map(r => {
                const title  = esc(r.title || r.name || '');
                const artist = esc(r.artist || r.artist_name || '');
                const src    = esc(r.source_label || r.source || '');
                const status = r.status || '';
                const err    = r.error_message ? `<span style="color:#ef4444;font-size:.71rem;margin-left:6px">${esc(r.error_message)}</span>` : '';
                return `
                    <div style="padding:10px 14px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;display:flex;align-items:center;gap:10px;min-width:0">
                        <div style="flex:1;min-width:0">
                            <div style="font-size:.85rem;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${title}</div>
                            <div style="font-size:.73rem;color:var(--text-dim)">${artist}</div>
                        </div>
                        <div style="display:flex;gap:5px;align-items:center;flex-shrink:0;flex-wrap:wrap;justify-content:flex-end">
                            <span class="badge badge-${statusColor[status]||'dim'}">${status}</span>
                            ${src ? `<span class="badge badge-purple">${src}</span>` : ''}
                            ${err}
                            <span style="font-size:.72rem;color:var(--text-dim)">${timeAgo(r.updated_at)}</span>
                        </div>
                    </div>`;
            }).join('');
        } catch(e) {
            if (listEl) listEl.innerHTML = `<div style="color:#ef4444">Failed to load history</div>`;
        }
    }

    // ── Polling ───────────────────────────────────────────────────
    function startPolling() {
        stopPolling();
        pollTimer = setInterval(async () => {
            if (activeTab !== 'history') {
                try {
                    liveData = await api.get('/downloads/live-status');
                    if (activeTab !== 'history') {
                        buildClientUI(document.getElementById('act-content'), activeTab, liveData);
                    }
                } catch {}
            }
        }, 5000);
    }

    function stopPolling() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    function load(params) {
        activeTab = params?.tab || 'qbittorrent';
        liveData  = null;
        render();
    }

    function unload() { stopPolling(); }

    return { load, unload };
})();
