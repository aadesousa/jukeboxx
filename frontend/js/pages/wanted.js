// ─── Wanted Page ──────────────────────────────────────────────────
const WantedPage = (() => {
    const root = () => document.getElementById('page-root');

    let trackItems  = [];
    let trackTotal  = 0;
    let trackOffset = 0;
    let trackSort   = 'artist';
    let selectedTracks = new Set();
    let summary = null;

    // Dispatch progress polling
    let _dispatchPollTimer = null;

    // Manual search modal state
    let msContext = null; // {spotify_id, item_type, title, artist, album}
    let msActiveTab = 'torrents';

    // ── Load ──────────────────────────────────────────────────────────
    async function load(params) {
        trackItems = []; trackOffset = 0; trackTotal = 0;
        selectedTracks = new Set();
        summary = null;

        root().innerHTML = buildShell();
        bindShellEvents();
        buildSearchModal();
        await Promise.all([fetchSummary(), fetchTracks(true)]);

        // Reconnect to any dispatch already running in the background
        try {
            const p = await api.get('/downloads/dispatch-progress');
            if (p.running || p.phase === 'searching') {
                const btn = document.getElementById('search-all-btn');
                if (btn) btn.disabled = true;
                _startDispatchPoll();
            }
        } catch {}
    }

    function unload() {
        trackItems = []; selectedTracks = new Set();
        _stopDispatchPoll();
        const modal = document.getElementById('manual-search-modal');
        if (modal) modal.remove();
    }

    // ── Shell ─────────────────────────────────────────────────────────
    function buildShell() {
        return `
        <div class="page-header">
            <div class="page-header-left">
                <h1 class="page-title">Wanted</h1>
                <div class="page-subtitle" id="wanted-subtitle">Missing albums and tracks</div>
            </div>
            <div class="page-header-right">
                <button class="btn" id="search-all-btn">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                    </svg>
                    Search All
                </button>
            </div>
        </div>

        <div class="filter-bar" id="wanted-filter-bar">
            <div class="filter-group" id="wanted-sort-btns">
                <span style="font-size:.75rem;color:var(--text-muted);align-self:center;margin-right:4px">Sort</span>
            </div>
        </div>

        <div id="wanted-content" style="flex:1;overflow-y:auto;padding-bottom:60px">
            ${buildTableSkeleton()}
        </div>

        <div class="mass-edit-bar" id="wanted-mass-bar" hidden>
            <span id="wanted-mass-count">0 selected</span>
            <div style="display:flex;gap:6px">
                <button class="btn btn-sm" id="wanted-ignore-sel">Ignore</button>
            </div>
            <button class="btn btn-sm" id="wanted-clear-sel">Clear</button>
        </div>`;
    }

    function buildTableSkeleton() {
        return `<div style="padding:0 24px">${
            Array.from({length: 10}, () => `
            <div style="display:flex;gap:12px;padding:10px 0;border-top:1px solid var(--border);align-items:center">
                <div class="skeleton" style="width:16px;height:16px;border-radius:3px;flex-shrink:0"></div>
                <div class="skeleton" style="width:40px;height:40px;border-radius:2px;flex-shrink:0"></div>
                <div style="flex:1">
                    <div class="skeleton" style="height:12px;width:50%;border-radius:3px;margin-bottom:5px"></div>
                    <div class="skeleton" style="height:10px;width:30%;border-radius:3px"></div>
                </div>
                <div class="skeleton" style="width:80px;height:20px;border-radius:3px"></div>
            </div>`).join('')
        }</div>`;
    }

    // ── Data fetch ────────────────────────────────────────────────────
    async function fetchSummary() {
        try {
            summary = await api.get('/wanted/summary');
            const el = document.getElementById('wanted-subtitle');
            if (el && summary) {
                const parts = [];
                if (summary.missing_tracks > 0) parts.push(`${summary.missing_tracks} wanted`);
                if (summary.downloading > 0) parts.push(`${summary.downloading} dispatched`);
                el.textContent = parts.join(' · ') || 'Nothing wanted';
            }
        } catch {}
    }

    async function fetchTracks(reset = false) {
        if (reset) { trackItems = []; trackOffset = 0; trackTotal = 0; }
        try {
            const data = await api.get(`/wanted/missing-tracks?sort=${trackSort}&offset=${trackOffset}&limit=200`);
            trackItems = reset ? (data.items || []) : trackItems.concat(data.items || []);
            trackTotal = data.total || 0;
            trackOffset = trackItems.length;
            renderTracks();
        } catch (e) {
            document.getElementById('wanted-content').innerHTML = `
                <div class="empty-state" style="padding-top:40px">
                    <div class="empty-state-title">Failed to load</div>
                    <div class="empty-state-body">${esc(e.message)}</div>
                </div>`;
        }
    }

    // ── Render: Wanted Tracks ─────────────────────────────────────────
    function renderTracks() {
        const content = document.getElementById('wanted-content');
        if (!content) return;

        if (trackItems.length === 0) {
            content.innerHTML = `<div class="empty-state" style="padding-top:60px">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" width="64" height="64">
                    <path d="M9 19V6l12-3v13"/><circle cx="6" cy="19" r="3"/><circle cx="18" cy="16" r="3"/>
                </svg>
                <div class="empty-state-title">No Wanted Tracks</div>
                <div class="empty-state-body">Import tracks from your Spotify Liked Songs to see them here.</div>
                <a class="btn btn-primary" href="#/import" style="margin-top:8px">Import from Spotify</a>
            </div>`;
            return;
        }

        const hasMore = trackOffset < trackTotal;
        content.innerHTML = `
        <div style="padding:6px 24px;font-size:.8rem;color:var(--text-dim)">
            ${trackTotal} wanted track${trackTotal !== 1 ? 's' : ''}${summary?.downloading > 0 ? ` · <span style="color:var(--accent)">${summary.downloading} dispatched</span>` : ''}
        </div>
        <table class="arr-table" style="width:100%">
            <thead>
                <tr>
                    <th style="width:36px"><input type="checkbox" id="track-select-all" style="accent-color:var(--accent)"></th>
                    <th style="width:44px"></th>
                    <th>Track</th>
                    <th>Artist</th>
                    <th>Album</th>
                    <th style="width:70px;text-align:right">Duration</th>
                    <th style="width:120px">Status</th>
                    <th style="width:120px;text-align:right">Actions</th>
                </tr>
            </thead>
            <tbody>${trackItems.map(buildTrackRow).join('')}</tbody>
        </table>
        ${hasMore ? `<div style="text-align:center;padding:16px">
            <button class="btn" id="tracks-load-more">Load More (${trackTotal - trackOffset} more)</button>
        </div>` : ''}`;

        bindTrackRowEvents();
        syncSelectAll();
        document.getElementById('track-select-all')?.addEventListener('change', e => {
            const checked = e.target.checked;
            if (checked) trackItems.forEach(t => selectedTracks.add(t.id));
            else selectedTracks.clear();
            document.querySelectorAll('.track-cb').forEach(cb => { cb.checked = checked; });
            updateMassBar();
        });
        document.getElementById('tracks-load-more')?.addEventListener('click', () => fetchTracks(false));
        updateMassBar();
    }

    function buildTrackRow(t) {
        const isSelected = selectedTracks.has(t.id);
        const thumb = t.album_image
            ? `<img src="${esc(t.album_image)}" style="width:36px;height:36px;object-fit:cover;border-radius:2px">`
            : `<div style="width:36px;height:36px;background:var(--bg-raised);border-radius:2px"></div>`;
        const dur = t.duration_ms ? formatDuration(t.duration_ms) : '—';

        return `
        <tr class="arr-table-row" data-track-id="${t.id}" data-spotify-id="${esc(t.spotify_id || '')}" data-name="${esc(t.name)}" data-artist="${esc(t.artist_display || t.artist_name || '')}" data-album="${esc(t.album_display || t.album_name || '')}">
            <td><input type="checkbox" class="track-cb" data-id="${t.id}" ${isSelected ? 'checked' : ''} style="accent-color:var(--accent)"></td>
            <td style="padding:6px 4px">${thumb}</td>
            <td style="max-width:220px">
                <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:500">${esc(t.name)}</div>
            </td>
            <td style="max-width:160px;color:var(--text-dim)">
                <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.artist_display || t.artist_name || '')}</div>
            </td>
            <td style="max-width:180px;color:var(--text-muted)">
                <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
                    ${t.album_id
                        ? `<a href="#/albums/${t.album_id}" style="color:var(--text-muted)">${esc(t.album_display || t.album_name || '')}</a>`
                        : esc(t.album_display || t.album_name || '')}
                </div>
            </td>
            <td style="text-align:right;color:var(--text-muted)">${dur}</td>
            <td>
                <span class="status-badge missing" style="font-size:.72rem">○ Wanted</span>
            </td>
            <td style="text-align:right">
                <div style="display:flex;gap:4px;justify-content:flex-end">
                    <button class="btn btn-sm btn-primary track-search-btn" data-id="${t.id}" title="Manual Search">🔍 Search</button>
                    <button class="btn btn-sm track-ignore-btn" data-id="${t.id}" style="color:var(--text-muted)" title="Ignore">Ignore</button>
                </div>
            </td>
        </tr>`;
    }

    function syncSelectAll() {
        const cb = document.getElementById('track-select-all');
        if (!cb) return;
        if (selectedTracks.size === 0) {
            cb.checked = false; cb.indeterminate = false;
        } else if (selectedTracks.size >= trackItems.length) {
            cb.checked = true; cb.indeterminate = false;
        } else {
            cb.checked = false; cb.indeterminate = true;
        }
    }

    function bindTrackRowEvents() {
        document.querySelectorAll('.track-cb').forEach(cb => {
            cb.addEventListener('change', e => {
                const id = parseInt(e.target.dataset.id);
                if (e.target.checked) selectedTracks.add(id); else selectedTracks.delete(id);
                syncSelectAll();
                updateMassBar();
            });
        });
        document.querySelectorAll('.track-search-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const row = btn.closest('tr');
                openSearchModal({
                    spotify_id: row.dataset.spotifyId || '',
                    item_type: 'track',
                    title: row.dataset.name || '',
                    artist: row.dataset.artist || '',
                    album: row.dataset.album || '',
                });
            });
        });
        document.querySelectorAll('.track-ignore-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const id = parseInt(btn.dataset.id);
                try {
                    await api.patch(`/wanted/missing-tracks/${id}`, { status: 'ignored' });
                    trackItems = trackItems.filter(t => t.id !== id);
                    trackTotal = Math.max(0, trackTotal - 1);
                    if (summary) summary.missing_tracks = Math.max(0, (summary.missing_tracks || 0) - 1);
                    renderTracks();
                    toast('Track ignored', 'info');
                } catch (e) { toast('Failed: ' + e.message, 'error'); }
            });
        });

    }

    // ── Mass Edit Bar ─────────────────────────────────────────────────
    function updateMassBar() {
        const bar = document.getElementById('wanted-mass-bar');
        if (!bar) return;
        const n = selectedTracks.size;
        bar.hidden = n === 0;
        const el = document.getElementById('wanted-mass-count');
        if (el) el.textContent = `${n} selected`;
    }

    function buildStatusBadge(status) {
        const map = {
            wanted:      `<span class="status-badge missing">Missing</span>`,
            partial:     `<span class="status-badge" style="background:var(--orange-dim);color:var(--orange)">Partial</span>`,
            downloading: `<span class="status-badge downloading">Downloading</span>`,
            have:        `<span class="status-badge have">Have</span>`,
        };
        return map[status] || `<span class="status-badge">${esc(status || 'unknown')}</span>`;
    }

    // ── Sort buttons ──────────────────────────────────────────────────
    function renderSortBtns() {
        const wrap = document.getElementById('wanted-sort-btns');
        if (!wrap) return;

        const sorts = [{ id: 'artist', label: 'Artist' }, { id: 'added', label: 'Added' }, { id: 'name', label: 'Name' }];
        const btns = sorts.map(s =>
            `<button class="filter-btn ${s.id === trackSort ? 'active' : ''}" data-sort="${s.id}">${s.label}</button>`
        ).join('');

        wrap.innerHTML = `<span style="font-size:.75rem;color:var(--text-muted);align-self:center;margin-right:4px">Sort</span>${btns}`;

        wrap.querySelectorAll('[data-sort]').forEach(btn => {
            btn.addEventListener('click', () => {
                trackSort = btn.dataset.sort;
                fetchTracks(true);
                wrap.querySelectorAll('[data-sort]').forEach(b => b.classList.toggle('active', b.dataset.sort === trackSort));
            });
        });
    }

    // ── Shell event bindings ──────────────────────────────────────────
    function bindShellEvents() {
        renderSortBtns();

        document.getElementById('search-all-btn')?.addEventListener('click', async () => {
            const btn = document.getElementById('search-all-btn');
            btn.disabled = true;
            showDispatchBar('Starting search…', null, null);
            try {
                await api.post('/downloads/dispatch-now', {});
                _startDispatchPoll();
            } catch (e) {
                finishDispatchBar('Search All failed: ' + e.message, true);
                btn.disabled = false;
            }
        });

        document.getElementById('wanted-ignore-sel')?.addEventListener('click', async () => {
            const ids = [...selectedTracks];
            let ok = 0;
            for (const id of ids) {
                try { await api.patch(`/wanted/missing-tracks/${id}`, { status: 'ignored' }); ok++; } catch {}
            }
            trackItems = trackItems.filter(t => !selectedTracks.has(t.id));
            trackTotal = Math.max(0, trackTotal - ok);
            if (summary) summary.missing_tracks = Math.max(0, (summary.missing_tracks || 0) - ok);
            selectedTracks.clear();
            renderTracks();
            toast(`Ignored ${ok} track${ok !== 1 ? 's' : ''}`, 'info');
            updateMassBar();
        });

        document.getElementById('wanted-clear-sel')?.addEventListener('click', () => {
            selectedTracks.clear();
            renderTracks();
            updateMassBar();
        });
    }

    // ── Dispatch progress bar ─────────────────────────────────────────
    function _dispatchBarEl() { return document.getElementById('dispatch-progress-wrap'); }

    function showDispatchBar(label, pct, sub) {
        const header = document.querySelector('.page-header');
        let wrap = _dispatchBarEl();
        if (!wrap) {
            wrap = document.createElement('div');
            wrap.id = 'dispatch-progress-wrap';
            wrap.style.cssText = 'padding:0 24px 12px';
            header?.insertAdjacentElement('afterend', wrap);
        }
        const safePct = pct == null ? null : Math.max(0, Math.min(100, pct));
        wrap.innerHTML = `
            <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:10px;padding:14px 16px">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <span style="font-size:.85rem;font-weight:500;color:var(--text)">${esc(label)}</span>
                    ${safePct != null ? `<span style="font-size:.78rem;color:var(--text-dim)">${safePct}%</span>` : ''}
                </div>
                <div style="height:5px;background:var(--bg-elevated);border-radius:99px;overflow:hidden">
                    ${safePct != null
                        ? `<div style="height:100%;width:${safePct}%;background:var(--accent);border-radius:99px;transition:width .25s ease"></div>`
                        : `<div style="height:100%;width:100%;background:linear-gradient(90deg,transparent 0%,var(--accent) 40%,transparent 100%);background-size:300px 100%;animation:shimmer 1.2s linear infinite"></div>`}
                </div>
                ${sub ? `<div style="font-size:.75rem;color:var(--text-dim);margin-top:6px">${esc(sub)}</div>` : ''}
            </div>`;
    }

    function finishDispatchBar(msg, isError = false) {
        _stopDispatchPoll();
        const wrap = _dispatchBarEl();
        if (!wrap) return;
        const color = isError ? '#ef4444' : 'var(--green)';
        wrap.innerHTML = `
            <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:10px;padding:12px 16px;display:flex;align-items:center;gap:10px">
                <span style="font-size:1rem">${isError ? '✗' : '✓'}</span>
                <span style="font-size:.85rem;color:${color}">${esc(msg)}</span>
                <button onclick="this.closest('#dispatch-progress-wrap').remove();const b=document.getElementById('search-all-btn');if(b)b.disabled=false;" style="margin-left:auto;background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:.85rem">✕</button>
            </div>`;
        // Re-enable button and refresh
        const btn = document.getElementById('search-all-btn');
        if (btn) btn.disabled = false;
        fetchSummary();
        fetchTracks(true);
    }

    function _startDispatchPoll() {
        _stopDispatchPoll();
        _dispatchPollTimer = setInterval(_pollDispatch, 300);
        _pollDispatch();
    }

    function _stopDispatchPoll() {
        if (_dispatchPollTimer) { clearInterval(_dispatchPollTimer); _dispatchPollTimer = null; }
    }

    async function _pollDispatch() {
        let p;
        try { p = await api.get('/downloads/dispatch-progress'); } catch { return; }

        const phase = p.phase || '';
        const ti = p.track_index || 0;
        const tt = p.track_total || 0;
        const name = p.track_name || '';
        const artist = p.track_artist || '';
        const dispatched = p.dispatched || 0;
        const bd = p.breakdown || {};
        const pct = tt > 0 ? Math.round(ti / tt * 100) : null;

        // tt === -1 means dispatch just started and hasn't counted tracks yet — keep polling
        if (tt === -1 && p.running) return;

        if (phase === 'done' || (!p.running && phase !== 'searching')) {
            _stopDispatchPoll();
            if (tt === 0) {
                finishDispatchBar('No wanted tracks to search right now');
            } else {
                const parts = Object.entries(bd).map(([src, cnt]) => `${cnt} via ${src}`);
                const msg = dispatched > 0
                    ? `Search complete — ${dispatched} of ${tt} track${tt !== 1 ? 's' : ''} dispatched${parts.length ? ' (' + parts.join(', ') + ')' : ''}`
                    : `Search complete — no sources found for ${tt} track${tt !== 1 ? 's' : ''}`;
                finishDispatchBar(msg, dispatched === 0);
            }
            return;
        }

        if (p.running) {
            const bdParts = Object.entries(bd).map(([src, cnt]) => `${cnt} ${src}`);
            const trackLabel = name ? `"${name}"${artist ? ' — ' + artist : ''}` : `track ${ti}/${tt}`;
            const sub = `Searching ${trackLabel}${bdParts.length ? ' · Songs dispatched so far — ' + bdParts.join(', ') : ''}`;
            showDispatchBar(`Searching ${tt} track${tt !== 1 ? 's' : ''} by source priority…`, pct, sub);
        }
    }

    // ── Manual Search Modal ───────────────────────────────────────────

    function buildSearchModal() {
        if (document.getElementById('manual-search-modal')) return;
        const div = document.createElement('div');
        div.innerHTML = `
        <div id="manual-search-modal" class="modal-backdrop hidden">
          <div class="modal-box" style="max-width:780px;width:95vw">
            <div class="modal-header">
              <span id="ms-modal-title">Manual Search</span>
              <button class="modal-close" id="ms-close">✕</button>
            </div>
            <div class="section-tabs" id="ms-tabs" style="margin:0;border-bottom:1px solid var(--border)"></div>
            <div id="ms-content" style="min-height:200px;max-height:60vh;overflow-y:auto;padding:12px 16px"></div>
          </div>
        </div>`;
        document.body.appendChild(div.firstElementChild);

        document.getElementById('ms-close').addEventListener('click', closeSearchModal);
        document.getElementById('manual-search-modal').addEventListener('mousedown', e => {
            if (e.target === e.currentTarget) closeSearchModal();
        });
    }

    function openSearchModal(ctx) {
        msContext = ctx;
        msActiveTab = 'torrents';
        const modal = document.getElementById('manual-search-modal');
        const title = document.getElementById('ms-modal-title');
        if (title) title.textContent = `Search: ${ctx.title}${ctx.artist ? ' — ' + ctx.artist : ''}`;
        renderMsTabs();
        modal.classList.remove('hidden');
        loadMsTab(msActiveTab);
    }

    function closeSearchModal() {
        const modal = document.getElementById('manual-search-modal');
        if (modal) modal.classList.add('hidden');
        msContext = null;
    }

    function renderMsTabs() {
        const tabs = [
            { id: 'torrents',  label: 'Torrents' },
            { id: 'usenet',    label: 'Usenet' },
            { id: 'soulseek',  label: 'Soulseek' },
            { id: 'youtube',   label: 'YouTube' },
        ];
        const wrap = document.getElementById('ms-tabs');
        if (!wrap) return;
        wrap.innerHTML = tabs.map(t =>
            `<button class="section-tab ${t.id === msActiveTab ? 'active' : ''}" data-ms-tab="${t.id}">${t.label}</button>`
        ).join('');
        wrap.querySelectorAll('[data-ms-tab]').forEach(btn => {
            btn.addEventListener('click', () => {
                msActiveTab = btn.dataset.msTab;
                wrap.querySelectorAll('[data-ms-tab]').forEach(b => b.classList.toggle('active', b.dataset.msTab === msActiveTab));
                loadMsTab(msActiveTab);
            });
        });
    }

    async function loadMsTab(tab) {
        const content = document.getElementById('ms-content');
        if (!content || !msContext) return;
        content.innerHTML = `<div style="padding:24px;text-align:center;color:var(--text-muted)">Loading…</div>`;

        try {
            if (tab === 'torrents' || tab === 'usenet') {
                await renderMsIndexers(content, tab);
            } else if (tab === 'soulseek') {
                await renderMsSoulseek(content);
            } else if (tab === 'youtube') {
                await renderMsYoutube(content);
            }
        } catch (e) {
            content.innerHTML = `<div style="padding:16px;color:var(--red)">Error: ${esc(e.message)}</div>`;
        }
    }

    async function renderMsIndexers(content, tabType) {
        const ctx = msContext;
        const data = await api.get(`/search/indexers?q=${encodeURIComponent(ctx.title)}&artist=${encodeURIComponent(ctx.artist)}`);
        const items = tabType === 'torrents' ? (data.torrents || []) : (data.usenet || []);

        if (items.length === 0) {
            content.innerHTML = `<div class="empty-state" style="padding:32px 0">
                <div class="empty-state-title">No Results</div>
                <div class="empty-state-body">No ${tabType} results for "${esc(data.query || ctx.title)}".<br>Check indexer configuration in Settings.</div>
            </div>`;
            return;
        }

        content.innerHTML = `
        <div style="font-size:.8rem;color:var(--text-dim);margin-bottom:8px">${items.length} results for "${esc(data.query || ctx.title)}"</div>
        <table class="arr-table" style="width:100%">
            <thead><tr><th>Title</th><th style="width:80px">Size</th>${tabType === 'torrents' ? '<th style="width:60px">Seeds</th>' : ''}<th style="width:100px">Indexer</th><th style="width:80px;text-align:right">Action</th></tr></thead>
            <tbody>${items.map((item, i) => `
                <tr class="arr-table-row">
                    <td style="max-width:340px"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(item.title)}">${esc(item.title)}</div></td>
                    <td style="color:var(--text-muted)">${formatBytes(item.size)}</td>
                    ${tabType === 'torrents' ? `<td style="color:${(item.seeders||0)>0?'var(--teal)':'var(--red)'}">${item.seeders||0}</td>` : ''}
                    <td style="color:var(--text-muted)">${esc(item.indexer || '')}</td>
                    <td style="text-align:right"><button class="btn btn-sm btn-primary ms-grab-btn" data-idx="${i}">Grab</button></td>
                </tr>`).join('')}
            </tbody>
        </table>`;

        content.querySelectorAll('.ms-grab-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const item = items[parseInt(btn.dataset.idx)];
                if (!item.download_url) {
                    toast('No download URL available', 'error');
                    return;
                }
                btn.disabled = true; btn.textContent = '…';
                const endpoint = tabType === 'torrents' ? '/search/grab-torrent' : '/search/grab-usenet';
                try {
                    const result = await api.post(endpoint, { download_url: item.download_url });
                    toast(result.message || 'Queued!', 'success');
                    btn.textContent = '✓';
                } catch(e) {
                    toast('Failed: ' + e.message, 'error');
                    btn.disabled = false; btn.textContent = 'Grab';
                }
            });
        });
    }

    async function renderMsSoulseek(content) {
        const ctx = msContext;

        // Show loading state while both searches run
        content.innerHTML = `<div style="padding:24px;text-align:center;color:var(--text-muted)">
            Searching Soulseek…
            ${ctx.album ? `<div style="font-size:.8rem;margin-top:4px;color:var(--text-dim)">Running track + album search in parallel</div>` : ''}
        </div>`;

        const params = new URLSearchParams({ q: ctx.title, artist: ctx.artist });
        if (ctx.album) params.set('album', ctx.album);
        const data = await api.get(`/search/soulseek?${params}`);

        if (data.error) {
            content.innerHTML = `<div class="empty-state" style="padding:32px 0">
                <div class="empty-state-title">Soulseek Unavailable</div>
                <div class="empty-state-body">${esc(data.error)}</div>
            </div>`;
            return;
        }

        const folders = data.folders || [];
        const results = data.results || [];

        if (folders.length === 0 && results.length === 0) {
            content.innerHTML = `<div class="empty-state" style="padding:32px 0">
                <div class="empty-state-title">No Results</div>
                <div class="empty-state-body">No Soulseek results for "${esc(data.query || ctx.title)}".</div>
            </div>`;
            return;
        }

        let html = `<div style="font-size:.8rem;color:var(--text-dim);margin-bottom:12px">
            ${folders.length} album${folders.length !== 1 ? 's' : ''} · ${results.length} individual file${results.length !== 1 ? 's' : ''}
            ${data.album_query ? `<span style="margin-left:8px;color:var(--text-muted)">Searched: <em>${esc(data.query)}</em> + <em>${esc(data.album_query)}</em></span>` : ''}
        </div>`;

        if (folders.length > 0) {
            html += `
            <div style="margin-bottom:16px">
                <div style="font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);margin-bottom:6px">
                    Albums / Folders
                </div>
                <table class="arr-table" style="width:100%">
                    <thead><tr>
                        <th>Folder</th>
                        <th style="width:50px;text-align:center">Files</th>
                        <th style="width:75px">Size</th>
                        <th style="width:70px">Format</th>
                        <th style="width:110px">User</th>
                        <th style="width:140px;text-align:right">Actions</th>
                    </tr></thead>
                    <tbody>
                    ${folders.map((f, i) => `
                        <tr class="arr-table-row">
                            <td style="max-width:200px">
                                <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:500" title="${esc(f.folder)}">${esc(f.folder_name)}</div>
                            </td>
                            <td style="text-align:center;color:var(--text-muted)">${f.file_count}</td>
                            <td style="color:var(--text-muted)">${formatBytes(f.total_size)}</td>
                            <td style="color:var(--text-muted);font-size:.8rem">${esc((f.formats || []).join('/'))}</td>
                            <td style="color:var(--text-muted);max-width:110px"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(f.username)}</div></td>
                            <td style="text-align:right">
                                <div style="display:flex;gap:4px;justify-content:flex-end">
                                    <button class="btn btn-sm btn-primary slsk-grab-album" data-idx="${i}" title="Download entire folder">Album</button>
                                    <button class="btn btn-sm slsk-grab-track" data-idx="${i}" title="Download only the matched track">Track</button>
                                </div>
                            </td>
                        </tr>`).join('')}
                    </tbody>
                </table>
            </div>`;
        }

        if (results.length > 0) {
            html += `
            <div>
                <div style="font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);margin-bottom:6px">
                    Individual Files
                </div>
                <table class="arr-table" style="width:100%">
                    <thead><tr>
                        <th>Filename</th>
                        <th style="width:75px">Size</th>
                        <th style="width:65px">Bitrate</th>
                        <th style="width:110px">User</th>
                        <th style="width:70px;text-align:right">Action</th>
                    </tr></thead>
                    <tbody>
                    ${results.map((r, i) => `
                        <tr class="arr-table-row">
                            <td style="max-width:280px"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(r.filename)}">${esc(r.filename.split(/[\\/]/).pop() || r.filename)}</div></td>
                            <td style="color:var(--text-muted)">${formatBytes(r.size)}</td>
                            <td style="color:var(--text-muted)">${r.bitrate ? r.bitrate + 'k' : '—'}</td>
                            <td style="color:var(--text-muted)">${esc(r.username)}</td>
                            <td style="text-align:right"><button class="btn btn-sm ms-slsk-grab" data-idx="${i}">Grab</button></td>
                        </tr>`).join('')}
                    </tbody>
                </table>
            </div>`;
        }

        content.innerHTML = html;

        // Album grab — download entire folder
        content.querySelectorAll('.slsk-grab-album').forEach(btn => {
            btn.addEventListener('click', async () => {
                const folder = folders[parseInt(btn.dataset.idx)];
                btn.disabled = true; btn.textContent = '…';
                try {
                    const r = await api.post('/search/grab-soulseek', {
                        username: folder.username,
                        files: folder.files,
                    });
                    toast(`Queued ${r.queued} files from "${folder.folder_name}"`, 'success');
                    btn.textContent = '✓ Queued';
                } catch(e) {
                    toast('Grab failed: ' + e.message, 'error');
                    btn.disabled = false; btn.textContent = 'Album';
                }
            });
        });

        // Track grab — find the best-matching file in the folder
        content.querySelectorAll('.slsk-grab-track').forEach(btn => {
            btn.addEventListener('click', async () => {
                const folder = folders[parseInt(btn.dataset.idx)];
                const titleLower = ctx.title.toLowerCase();
                let bestFile = folder.files[0], bestScore = -1;
                for (const f of folder.files) {
                    const fname = f.filename.split(/[\\/]/).pop().toLowerCase();
                    let score = titleLower.split(' ').filter(w => w && fname.includes(w)).length;
                    if (score > bestScore) { bestScore = score; bestFile = f; }
                }
                btn.disabled = true; btn.textContent = '…';
                try {
                    await api.post('/search/grab-soulseek', {
                        username: folder.username,
                        files: [bestFile],
                    });
                    toast(`Queued track from "${folder.folder_name}"`, 'success');
                    btn.textContent = '✓ Queued';
                } catch(e) {
                    toast('Grab failed: ' + e.message, 'error');
                    btn.disabled = false; btn.textContent = 'Track';
                }
            });
        });

        // Individual file grab
        content.querySelectorAll('.ms-slsk-grab').forEach(btn => {
            btn.addEventListener('click', async () => {
                const file = results[parseInt(btn.dataset.idx)];
                btn.disabled = true; btn.textContent = '…';
                try {
                    await api.post('/search/grab-soulseek', {
                        username: file.username,
                        files: [{ filename: file.filename, size: file.size }],
                    });
                    toast('Queued', 'success');
                    btn.textContent = '✓';
                } catch(e) {
                    toast('Grab failed: ' + e.message, 'error');
                    btn.disabled = false; btn.textContent = 'Grab';
                }
            });
        });
    }

    async function renderMsYoutube(content) {
        const ctx = msContext;
        const data = await api.get(`/search/youtube?q=${encodeURIComponent(ctx.title)}&artist=${encodeURIComponent(ctx.artist)}`);
        const results = data.results || [];

        if (results.length === 0) {
            content.innerHTML = `<div class="empty-state" style="padding:32px 0">
                <div class="empty-state-title">No Results</div>
                <div class="empty-state-body">No YouTube results found.${data.error ? ' Error: ' + esc(data.error) : ''}</div>
            </div>`;
            return;
        }

        content.innerHTML = `
        <div style="font-size:.8rem;color:var(--text-dim);margin-bottom:8px">${results.length} results for "${esc(data.query || ctx.title)}"</div>
        <table class="arr-table" style="width:100%">
            <thead><tr><th>Title</th><th style="width:100px">Channel</th><th style="width:70px">Duration</th><th style="width:140px;text-align:right">Actions</th></tr></thead>
            <tbody>${results.map((r, i) => `
                <tr class="arr-table-row">
                    <td style="max-width:260px"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(r.title)}">${esc(r.title)}</div></td>
                    <td style="color:var(--text-muted);max-width:100px"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.uploader || '')}</div></td>
                    <td style="color:var(--text-muted)">${r.duration ? fmtSecs(r.duration) : '—'}</td>
                    <td style="text-align:right">
                        <div style="display:flex;gap:4px;justify-content:flex-end">
                            <button class="btn btn-sm btn-primary yt-download-btn" data-idx="${i}" data-url="${esc(r.url)}">Download</button>
                            <a class="btn btn-sm" href="${esc(r.url)}" target="_blank" rel="noopener">View</a>
                        </div>
                    </td>
                </tr>`).join('')}
            </tbody>
        </table>`;

        content.querySelectorAll('.yt-download-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const url = btn.dataset.url;
                btn.disabled = true; btn.textContent = '…';
                try {
                    await api.post('/youtube/download', { url });
                    toast('Queued for download in MeTube', 'success');
                    btn.textContent = '✓ Queued';
                } catch(e) {
                    toast('Download failed: ' + e.message, 'error');
                    btn.disabled = false; btn.textContent = 'Download';
                }
            });
        });
    }

    // ── Helpers ───────────────────────────────────────────────────────
    function formatBytes(bytes) {
        if (!bytes) return '—';
        if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + 'GB';
        return Math.round(bytes / 1048576) + 'MB';
    }

    function fmtSecs(s) {
        if (!s) return '—';
        return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    }

    return { load, unload };
})();
