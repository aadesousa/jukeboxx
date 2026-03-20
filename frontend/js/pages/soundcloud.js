// ─── SoundCloud Page ──────────────────────────────────────────────────────────
const SoundCloudPage = (() => {
    const root = () => document.getElementById('page-root');

    // State
    let syncItems    = [];
    let scanResults  = null;   // playlists found by profile scan
    let dlStatus     = {};     // live download status from /soundcloud/downloads
    let _pollTimer   = null;
    let _activeTab   = 'library'; // 'library' | 'scan' | 'downloads'

    // ── Load / Unload ─────────────────────────────────────────────
    async function load() {
        syncItems   = [];
        scanResults = null;
        dlStatus    = {};
        _activeTab  = 'library';
        root().innerHTML = buildShell();
        bindShellEvents();
        await refreshData();
    }

    function unload() {
        syncItems   = [];
        scanResults = null;
        dlStatus    = {};
        _stopPoll();
    }

    // ── Shell ─────────────────────────────────────────────────────
    function buildShell() {
        return `
        <div class="page-header">
            <div class="page-header-left">
                <div style="display:flex;align-items:center;gap:10px">
                    ${SC_ICON_LG}
                    <div>
                        <h1 class="page-title" style="margin:0">SoundCloud</h1>
                        <div class="page-subtitle">Download playlists directly to your music library</div>
                    </div>
                </div>
            </div>
            <div class="page-header-right" id="sc-header-right"></div>
        </div>

        <div style="padding:0 24px 80px">
            <div class="section-tabs" style="margin-bottom:20px">
                <button class="section-tab active" data-tab="library">Library</button>
                <button class="section-tab" data-tab="scan">Scan Profile</button>
                <button class="section-tab" data-tab="downloads">Active Downloads</button>
            </div>

            <div id="sc-progress-wrap"></div>

            <div id="sc-tab-library"></div>
            <div id="sc-tab-scan" hidden></div>
            <div id="sc-tab-downloads" hidden></div>
        </div>`;
    }

    function bindShellEvents() {
        root().querySelectorAll('.section-tab[data-tab]').forEach(btn => {
            btn.addEventListener('click', () => switchTab(btn.dataset.tab));
        });
    }

    function switchTab(tab) {
        _activeTab = tab;
        root().querySelectorAll('.section-tab[data-tab]').forEach(b => {
            b.classList.toggle('active', b.dataset.tab === tab);
        });
        ['library','scan','downloads'].forEach(t => {
            const el = document.getElementById(`sc-tab-${t}`);
            if (el) el.hidden = (t !== tab);
        });
    }

    // ── Data refresh ──────────────────────────────────────────────
    async function refreshData() {
        try {
            syncItems = await api.get('/sync/items');
        } catch(e) {
            syncItems = [];
        }
        try {
            dlStatus = await api.get('/soundcloud/downloads');
        } catch {
            dlStatus = {};
        }
        renderLibraryTab();
        renderDownloadsTab();
        _maybeStartPoll();
    }

    // ── Library tab ───────────────────────────────────────────────
    function renderLibraryTab() {
        const el = document.getElementById('sc-tab-library');
        if (!el) return;
        const scItems = syncItems.filter(s => s.item_type === 'soundcloud');

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;flex-wrap:wrap">
                <span style="font-size:.85rem;color:var(--text-dim)">${scItems.length} playlist${scItems.length !== 1 ? 's' : ''} imported</span>
                <span style="flex:1"></span>
                <button class="btn btn-sm btn-primary" id="sc-import-open-btn">+ Import URL</button>
            </div>

            <div id="sc-import-form" hidden style="background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:16px">
                <div style="font-size:.85rem;font-weight:500;margin-bottom:8px">Import a single playlist URL</div>
                <div style="display:flex;gap:8px">
                    <input id="sc-url-input" type="url" placeholder="https://soundcloud.com/artist/sets/playlist-name"
                        style="flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg-elevated);color:var(--text);font-size:.875rem;outline:none"/>
                    <button class="btn btn-primary" id="sc-import-btn">Import</button>
                    <button class="btn" id="sc-import-cancel-btn">Cancel</button>
                </div>
            </div>

            ${scItems.length === 0
                ? `<div class="empty-state" style="padding-top:40px">
                    ${SC_ICON_EMPTY}
                    <div class="empty-state-title">No playlists imported yet</div>
                    <div class="empty-state-body">Use "Scan Profile" to discover playlists, or import a direct URL above.</div>
                    <button class="btn btn-primary" onclick="SoundCloudPage._switchToScan()" style="margin-top:12px">Scan a Profile</button>
                   </div>`
                : `<table class="arr-table" style="width:100%">
                    <thead><tr>
                        <th style="width:44px"></th>
                        <th>Playlist</th>
                        <th style="min-width:160px">Status</th>
                        <th>Last Downloaded</th>
                        <th>Output Path</th>
                        <th style="width:200px">Actions</th>
                    </tr></thead>
                    <tbody id="sc-library-tbody">
                        ${scItems.map(s => buildLibraryRow(s)).join('')}
                    </tbody>
                   </table>`}`;

        document.getElementById('sc-import-open-btn')?.addEventListener('click', () => {
            const form = document.getElementById('sc-import-form');
            if (form) { form.hidden = !form.hidden; if (!form.hidden) document.getElementById('sc-url-input')?.focus(); }
        });
        document.getElementById('sc-import-cancel-btn')?.addEventListener('click', () => {
            const form = document.getElementById('sc-import-form');
            if (form) form.hidden = true;
        });
        document.getElementById('sc-import-btn')?.addEventListener('click', importUrl);
        document.getElementById('sc-url-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') importUrl(); });

        bindLibraryRowEvents();
    }

    function buildLibraryRow(s) {
        const dl = dlStatus[s.id] || null;
        const thumb = s.image_url
            ? `<img src="${esc(s.image_url)}" style="width:36px;height:36px;object-fit:cover;border-radius:3px">`
            : `<div style="width:36px;height:36px;background:var(--bg-raised);border-radius:3px;display:flex;align-items:center;justify-content:center">${SC_ICON_SM}</div>`;

        let statusCell = '';
        let actionBtns = '';

        if (dl && dl.status === 'downloading') {
            const done  = dl.done || 0;
            const total = dl.total || 0;
            const pct   = total > 0 ? Math.round(done / total * 100) : null;
            statusCell = `
                <div style="min-width:140px">
                    <div style="display:flex;justify-content:space-between;font-size:.78rem;margin-bottom:3px">
                        <span style="color:var(--accent);font-weight:500">Downloading…</span>
                        <span style="color:var(--text-muted)">${done}${total ? '/'+total : ''}</span>
                    </div>
                    <div style="height:4px;background:var(--bg-elevated);border-radius:99px;overflow:hidden">
                        ${pct != null
                            ? `<div style="height:100%;width:${pct}%;background:var(--accent);border-radius:99px;transition:width .4s"></div>`
                            : `<div class="shimmer-bar"></div>`}
                    </div>
                </div>`;
            actionBtns = `<button class="btn-xs" disabled>Downloading…</button>`;
        } else if (dl && dl.status === 'done') {
            statusCell = `<span style="color:var(--green);font-size:.82rem">✓ Complete · ${dl.done || 0} downloaded</span>`;
            actionBtns = `
                <button class="btn-xs btn-primary sc-dl-btn" data-id="${s.id}" data-name="${esc(s.name||'')}">Re-download</button>
                <button class="btn-xs btn-danger sc-rm-btn" data-id="${s.id}">Remove</button>`;
        } else if (dl && dl.status === 'error') {
            statusCell = `<span style="color:var(--red);font-size:.78rem" title="${esc(dl.error||'')}">✗ Error — ${esc((dl.error||'').substring(0,60))}</span>`;
            actionBtns = `
                <button class="btn-xs btn-primary sc-dl-btn" data-id="${s.id}" data-name="${esc(s.name||'')}">Retry</button>
                <button class="btn-xs btn-danger sc-rm-btn" data-id="${s.id}">Remove</button>`;
        } else {
            const tc = s.track_count ? `<span style="color:var(--text-muted);font-size:.78rem">${s.track_count} tracks</span>` : '';
            statusCell = tc || `<span style="color:var(--text-muted);font-size:.8rem">—</span>`;
            actionBtns = `
                <button class="btn-xs btn-primary sc-dl-btn" data-id="${s.id}" data-name="${esc(s.name||'')}">Download All</button>
                <button class="btn-xs btn-danger sc-rm-btn" data-id="${s.id}">Remove</button>`;
        }

        const lastDl = s.last_synced_at
            ? `<span style="font-size:.75rem;color:var(--text-dim)" title="${esc(s.last_synced_at)}">${timeAgo(s.last_synced_at)}</span>`
            : `<span style="font-size:.75rem;color:var(--text-muted)">Never</span>`;

        // Output path hint
        const urlHost = (() => { try { return new URL(s.spotify_id||'').pathname.split('/').filter(Boolean).join('/'); } catch { return s.spotify_id||''; } })();
        const safeName = (s.name||'').replace(/[<>:"\/\\|?*\x00-\x1f]/g,'_').trim();
        const outputHint = safeName ? `<span style="font-size:.72rem;color:var(--text-muted);font-family:monospace">SoundCloud/${safeName}/</span>` : '—';

        return `<tr class="arr-table-row" data-sc-id="${s.id}">
            <td style="width:44px;padding:6px">${thumb}</td>
            <td style="max-width:200px">
                <div style="font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(s.name||s.spotify_id)}</div>
                <a href="${esc(s.spotify_id)}" target="_blank" rel="noopener"
                   style="font-size:.72rem;color:var(--text-muted);text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;max-width:180px"
                   title="${esc(s.spotify_id)}">${esc(urlHost)}</a>
            </td>
            <td>${statusCell}</td>
            <td>${lastDl}</td>
            <td>${outputHint}</td>
            <td><div style="display:flex;gap:4px">${actionBtns}</div></td>
        </tr>`;
    }

    function bindLibraryRowEvents() {
        document.querySelectorAll('.sc-dl-btn').forEach(btn => {
            btn.addEventListener('click', () => startDownload(+btn.dataset.id, btn.dataset.name, btn));
        });
        document.querySelectorAll('.sc-rm-btn').forEach(btn => {
            btn.addEventListener('click', () => removePlaylist(+btn.dataset.id));
        });
    }

    function _updateLibraryRows() {
        const scItems = syncItems.filter(s => s.item_type === 'soundcloud');
        const tbody = document.getElementById('sc-library-tbody');
        if (!tbody) return;
        tbody.innerHTML = scItems.map(s => buildLibraryRow(s)).join('');
        bindLibraryRowEvents();
    }

    // ── Scan Profile tab ──────────────────────────────────────────
    function renderScanTab() {
        const el = document.getElementById('sc-tab-scan');
        if (!el) return;

        const importedUrls = new Set(syncItems.filter(s => s.item_type === 'soundcloud').map(s => s.spotify_id));

        el.innerHTML = `
            <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:20px">
                <div style="font-size:.9rem;font-weight:500;margin-bottom:4px">Discover public playlists from a SoundCloud profile</div>
                <div style="font-size:.8rem;color:var(--text-dim);margin-bottom:14px">Enter a profile URL — all public playlists will be listed and you can import any or all of them.</div>
                <div style="display:flex;gap:8px">
                    <input id="sc-profile-input" type="url" placeholder="https://soundcloud.com/username"
                        style="flex:1;padding:9px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg-elevated);color:var(--text);font-size:.875rem;outline:none"/>
                    <button class="btn btn-primary" id="sc-scan-btn" style="min-width:120px">Scan Profile</button>
                </div>
            </div>
            <div id="sc-scan-results"></div>`;

        document.getElementById('sc-scan-btn')?.addEventListener('click', runProfileScan);
        document.getElementById('sc-profile-input')?.addEventListener('keydown', e => {
            if (e.key === 'Enter') runProfileScan();
        });

        // Re-render results if we already have them
        if (scanResults) {
            _renderScanResults(document.getElementById('sc-scan-results'), scanResults, importedUrls);
        }
    }

    async function runProfileScan() {
        const input = document.getElementById('sc-profile-input');
        const url   = input?.value?.trim();
        if (!url) { toast('Enter a SoundCloud profile URL', 'error'); return; }

        const btn = document.getElementById('sc-scan-btn');
        const res = document.getElementById('sc-scan-results');
        if (btn) { btn.disabled = true; btn.textContent = 'Scanning…'; }
        if (res) res.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;color:var(--text-dim);font-size:.875rem;padding:20px 0">
                <div style="width:16px;height:16px;border:2px solid var(--accent);border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;flex-shrink:0"></div>
                Scanning profile for public playlists… this may take up to 30 seconds
            </div>`;

        try {
            const r = await api.post('/soundcloud/profile-scan', { url });
            scanResults = r.playlists || [];
            const importedUrls = new Set(syncItems.filter(s => s.item_type === 'soundcloud').map(s => s.spotify_id));
            _renderScanResults(document.getElementById('sc-scan-results'), scanResults, importedUrls);
        } catch(e) {
            if (res) res.innerHTML = `
                <div style="background:var(--bg-card);border:1px solid var(--red);border-radius:8px;padding:16px;color:var(--red);font-size:.875rem">
                    <strong>Scan failed:</strong> ${esc(e.message || String(e))}
                    <div style="font-size:.8rem;color:var(--text-dim);margin-top:6px">Make sure the profile URL is correct (e.g. https://soundcloud.com/username)</div>
                </div>`;
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = 'Scan Profile'; }
        }
    }

    function _renderScanResults(el, playlists, importedUrls) {
        if (!el) return;
        if (!importedUrls) importedUrls = new Set(syncItems.filter(s => s.item_type === 'soundcloud').map(s => s.spotify_id));

        if (!playlists || playlists.length === 0) {
            el.innerHTML = `
                <div class="empty-state" style="padding-top:30px">
                    <div class="empty-state-title">No public playlists found</div>
                    <div class="empty-state-body">This profile may have no public playlists, or the URL may be incorrect.</div>
                </div>`;
            return;
        }

        const notImported = playlists.filter(pl => !importedUrls.has(pl.url));
        const rows = playlists.map((pl, i) => {
            const already = importedUrls.has(pl.url);
            return `<tr class="arr-table-row">
                <td style="max-width:260px">
                    <div style="font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(pl.name)}</div>
                    <a href="${esc(pl.url)}" target="_blank" rel="noopener"
                       style="font-size:.72rem;color:var(--text-muted);text-decoration:none">${esc(pl.url)}</a>
                </td>
                <td style="color:var(--text-dim);font-size:.85rem;white-space:nowrap">${pl.track_count || '?'} tracks</td>
                <td style="white-space:nowrap">
                    ${already
                        ? `<span style="color:var(--green);font-size:.82rem">✓ Imported</span>`
                        : `<button class="btn-xs btn-primary sc-scan-add-btn" data-idx="${i}">Add</button>`}
                </td>
            </tr>`;
        });

        el.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
                <span style="font-size:.85rem;color:var(--text-dim)">
                    ${playlists.length} playlist${playlists.length !== 1 ? 's' : ''} found
                    ${notImported.length > 0 ? ` · <span style="color:var(--text)">${notImported.length} not yet imported</span>` : ' · all imported'}
                </span>
                ${notImported.length > 0
                    ? `<button class="btn btn-sm btn-primary" id="sc-add-all-btn">Import All (${notImported.length})</button>`
                    : ''}
            </div>
            <table class="arr-table" style="width:100%">
                <thead><tr>
                    <th>Playlist</th>
                    <th style="width:100px">Tracks</th>
                    <th style="width:100px"></th>
                </tr></thead>
                <tbody>${rows.join('')}</tbody>
            </table>`;

        el.querySelectorAll('.sc-scan-add-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const pl = scanResults[+btn.dataset.idx];
                if (!pl) return;
                btn.disabled = true; btn.textContent = 'Adding…';
                try {
                    await api.post('/soundcloud/import', { url: pl.url });
                    toast(`Added "${pl.name}"`, 'success');
                    syncItems = await api.get('/sync/items');
                    const newImported = new Set(syncItems.filter(s => s.item_type === 'soundcloud').map(s => s.spotify_id));
                    btn.closest('td').innerHTML = `<span style="color:var(--green);font-size:.82rem">✓ Imported</span>`;
                    _updateLibraryRows();
                    // Update Add All count
                    const remaining = (scanResults||[]).filter(p => !newImported.has(p.url));
                    const addAllBtn = document.getElementById('sc-add-all-btn');
                    if (addAllBtn) {
                        if (remaining.length === 0) addAllBtn.remove();
                        else addAllBtn.textContent = `Import All (${remaining.length})`;
                    }
                } catch(e) {
                    toast('Failed: ' + (e.message || e), 'error');
                    btn.disabled = false; btn.textContent = 'Add';
                }
            });
        });

        document.getElementById('sc-add-all-btn')?.addEventListener('click', async () => {
            const addAllBtn = document.getElementById('sc-add-all-btn');
            if (addAllBtn) { addAllBtn.disabled = true; addAllBtn.textContent = 'Importing…'; }
            const curImported = new Set(syncItems.filter(s => s.item_type === 'soundcloud').map(s => s.spotify_id));
            const toAdd = (scanResults||[]).filter(pl => !curImported.has(pl.url));
            let added = 0;
            for (const pl of toAdd) {
                try { await api.post('/soundcloud/import', { url: pl.url }); added++; } catch {}
            }
            toast(`Imported ${added} playlist${added !== 1 ? 's' : ''}`, 'success');
            syncItems = await api.get('/sync/items');
            _updateLibraryRows();
            const newImported = new Set(syncItems.filter(s => s.item_type === 'soundcloud').map(s => s.spotify_id));
            _renderScanResults(el, scanResults, newImported);
        });
    }

    // ── Downloads tab ─────────────────────────────────────────────
    function renderDownloadsTab() {
        const el = document.getElementById('sc-tab-downloads');
        if (!el) return;

        const entries = Object.values(dlStatus);

        if (entries.length === 0) {
            el.innerHTML = `
                <div class="empty-state" style="padding-top:40px">
                    ${SC_ICON_EMPTY}
                    <div class="empty-state-title">No active downloads</div>
                    <div class="empty-state-body">Start a download from the Library tab and it will appear here.</div>
                </div>`;
            return;
        }

        const rows = entries
            .sort((a,b) => (b.started_at||'').localeCompare(a.started_at||''))
            .map(dl => {
                const done  = dl.done  || 0;
                const total = dl.total || 0;
                const pct   = total > 0 ? Math.round(done / total * 100) : null;

                let statusHtml = '';
                let barHtml    = '';

                if (dl.status === 'downloading') {
                    statusHtml = `<span style="color:var(--accent);font-weight:500">Downloading</span>`;
                    barHtml = `
                        <div style="margin-top:6px">
                            <div style="display:flex;justify-content:space-between;font-size:.75rem;color:var(--text-muted);margin-bottom:3px">
                                <span>${done} of ${total || '?'} tracks</span>
                                <span>${pct != null ? pct+'%' : ''}</span>
                            </div>
                            <div style="height:5px;background:var(--bg-elevated);border-radius:99px;overflow:hidden">
                                ${pct != null
                                    ? `<div style="height:100%;width:${pct}%;background:var(--accent);border-radius:99px;transition:width .4s"></div>`
                                    : `<div class="shimmer-bar"></div>`}
                            </div>
                        </div>`;
                } else if (dl.status === 'done') {
                    statusHtml = `<span style="color:var(--green)">✓ Complete</span>`;
                    barHtml    = `<div style="font-size:.78rem;color:var(--text-dim);margin-top:4px">${done} tracks downloaded</div>`;
                } else if (dl.status === 'error') {
                    statusHtml = `<span style="color:var(--red)">✗ Error</span>`;
                    barHtml    = `<div style="font-size:.78rem;color:var(--red);margin-top:4px">${esc(dl.error||'')}</div>`;
                }

                const started = dl.started_at
                    ? `<span style="font-size:.75rem;color:var(--text-muted)">${timeAgo(dl.started_at)}</span>`
                    : '';

                return `<tr class="arr-table-row">
                    <td style="max-width:240px">
                        <div style="font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(dl.name||'Unknown')}</div>
                        ${started}
                    </td>
                    <td style="min-width:200px">${statusHtml}${barHtml}</td>
                    <td style="white-space:nowrap">
                        ${dl.status === 'downloading'
                            ? `<button class="btn-xs" disabled>In Progress</button>`
                            : `<button class="btn-xs btn-primary sc-dl-btn" data-id="${dl.sync_id}" data-name="${esc(dl.name||'')}">Re-download</button>`}
                    </td>
                </tr>`;
            });

        el.innerHTML = `
            <div style="font-size:.82rem;color:var(--text-dim);margin-bottom:12px">${entries.length} session${entries.length!==1?'s':''} tracked in memory</div>
            <table class="arr-table" style="width:100%">
                <thead><tr>
                    <th>Playlist</th>
                    <th style="min-width:200px">Progress</th>
                    <th style="width:140px"></th>
                </tr></thead>
                <tbody>${rows.join('')}</tbody>
            </table>`;

        el.querySelectorAll('.sc-dl-btn').forEach(btn => {
            btn.addEventListener('click', () => startDownload(+btn.dataset.id, btn.dataset.name, btn));
        });
    }

    // ── Polling ───────────────────────────────────────────────────
    function _maybeStartPoll() {
        const active = Object.values(dlStatus).some(d => d.status === 'downloading');
        if (active) _startPoll();
        else _stopPoll();
    }

    function _startPoll() {
        _stopPoll();
        _pollTimer = setInterval(_pollDownloads, 1000);
    }

    function _stopPoll() {
        if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    }

    async function _pollDownloads() {
        try {
            dlStatus = await api.get('/soundcloud/downloads');
        } catch { return; }

        // Update only the dynamic parts
        _updateLibraryRows();
        if (_activeTab === 'downloads') renderDownloadsTab();

        const active = Object.values(dlStatus).some(d => d.status === 'downloading');
        if (!active) {
            _stopPoll();
            // Refresh sync items so last_synced_at updates
            try { syncItems = await api.get('/sync/items'); } catch {}
            _updateLibraryRows();
        }
    }

    // ── Actions ───────────────────────────────────────────────────
    async function startDownload(syncId, name, btn) {
        if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }
        try {
            await api.post(`/soundcloud/sync/${syncId}`);
            toast(`Download started for "${name}"`, 'success');
            // Kick off polling immediately
            await new Promise(r => setTimeout(r, 400));
            dlStatus = await api.get('/soundcloud/downloads');
            _updateLibraryRows();
            renderDownloadsTab();
            _startPoll();
        } catch(e) {
            toast('Failed to start download: ' + (e.message || e), 'error');
            if (btn) { btn.disabled = false; btn.textContent = 'Download All'; }
        }
    }

    async function importUrl() {
        const input = document.getElementById('sc-url-input');
        const url   = input?.value?.trim();
        if (!url) { toast('Enter a SoundCloud playlist URL', 'error'); return; }
        const btn = document.getElementById('sc-import-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Importing…'; }
        try {
            const r = await api.post('/soundcloud/import', { url });
            toast(`Imported "${r.name}" — ${r.track_count} tracks`, 'success');
            if (input) input.value = '';
            const form = document.getElementById('sc-import-form');
            if (form) form.hidden = true;
            syncItems = await api.get('/sync/items');
            renderLibraryTab();
        } catch(e) {
            toast('Import failed: ' + (e.message || e), 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = 'Import'; }
        }
    }

    async function removePlaylist(syncId) {
        if (!confirm('Remove this playlist from imports? Downloaded files will remain in the library.')) return;
        try {
            await api.del(`/soundcloud/sync/${syncId}`);
            toast('Playlist removed', 'info');
            syncItems = await api.get('/sync/items');
            renderLibraryTab();
        } catch(e) {
            toast('Failed: ' + e.message, 'error');
        }
    }

    // ── Tab rendering on switch ───────────────────────────────────
    // Override switchTab to lazily render scan/downloads tabs
    const _origSwitchTab = switchTab;
    function switchTab(tab) {
        _activeTab = tab;
        root().querySelectorAll('.section-tab[data-tab]').forEach(b => {
            b.classList.toggle('active', b.dataset.tab === tab);
        });
        ['library','scan','downloads'].forEach(t => {
            const el = document.getElementById(`sc-tab-${t}`);
            if (el) el.hidden = (t !== tab);
        });
        if (tab === 'scan') renderScanTab();
        if (tab === 'downloads') renderDownloadsTab();
    }

    // ── Icons ─────────────────────────────────────────────────────
    const SC_ICON_LG = `<svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32" style="color:#f50;flex-shrink:0"><path d="M1.175 12.225c-.15 0-.254.097-.282.25l-.357 2.285.357 2.223c.028.148.133.245.282.245.147 0 .252-.097.283-.245l.405-2.223-.405-2.285c-.031-.153-.136-.25-.283-.25zm1.675-.69c-.172 0-.303.118-.33.285l-.303 2.94.303 2.813c.027.163.158.28.33.28.17 0 .3-.117.328-.28l.344-2.813-.344-2.94c-.028-.167-.158-.285-.328-.285zm1.73-.17c-.196 0-.354.14-.38.332L3.9 14.25l.3 2.793c.026.192.184.333.38.333.195 0 .354-.14.38-.333l.34-2.793-.34-2.553c-.026-.192-.185-.332-.38-.332zm1.78-.48c-.22 0-.4.165-.423.383l-.27 2.982.27 2.772c.023.218.203.383.422.383.22 0 .4-.165.424-.383l.307-2.772-.307-2.982c-.024-.218-.204-.383-.423-.383zm1.8-.24c-.245 0-.444.183-.465.428l-.235 3.207.235 2.753c.021.245.22.428.465.428.244 0 .443-.183.464-.428l.266-2.753-.266-3.207c-.021-.245-.22-.428-.464-.428zm1.813-.28c-.268 0-.487.2-.505.468l-.2 3.432.2 2.735c.018.268.237.467.505.467.267 0 .486-.199.504-.467l.228-2.735-.228-3.432c-.018-.268-.237-.468-.504-.468zm1.833-.26c-.292 0-.53.218-.547.51l-.164 3.66.164 2.717c.017.29.255.51.547.51.29 0 .529-.22.546-.51l.186-2.717-.186-3.66c-.017-.292-.256-.51-.546-.51zm1.856-.23c-.315 0-.572.237-.585.553l-.128 3.87.128 2.697c.013.315.27.552.585.552.314 0 .57-.237.584-.552l.146-2.697-.146-3.87c-.014-.316-.27-.553-.584-.553zm1.864-.16c-.34 0-.615.256-.625.596l-.092 4.03.092 2.677c.01.34.285.596.625.596.338 0 .614-.256.623-.596l.105-2.677-.105-4.03c-.01-.34-.285-.596-.623-.596zm2.31 1.054c-.086-.034-.18-.05-.275-.05-.17 0-.33.05-.463.14-.135-1.535-1.42-2.733-2.984-2.733-.413 0-.806.085-1.16.24-.137.055-.173.11-.175.163v10.847c.002.056.044.103.1.11h4.96c.54 0 .977-.438.977-.977V13.21c0-.48-.35-.887-.82-.993a1.49 1.49 0 00-.16-.017z"/></svg>`;

    const SC_ICON_SM = `<svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16" style="color:#f50;opacity:.6"><path d="M1.175 12.225c-.15 0-.254.097-.282.25l-.357 2.285.357 2.223c.028.148.133.245.282.245.147 0 .252-.097.283-.245l.405-2.223-.405-2.285c-.031-.153-.136-.25-.283-.25zm1.675-.69c-.172 0-.303.118-.33.285l-.303 2.94.303 2.813c.027.163.158.28.33.28.17 0 .3-.117.328-.28l.344-2.813-.344-2.94c-.028-.167-.158-.285-.328-.285zm1.73-.17c-.196 0-.354.14-.38.332L3.9 14.25l.3 2.793c.026.192.184.333.38.333.195 0 .354-.14.38-.333l.34-2.793-.34-2.553c-.026-.192-.185-.332-.38-.332zm1.78-.48c-.22 0-.4.165-.423.383l-.27 2.982.27 2.772c.023.218.203.383.422.383.22 0 .4-.165.424-.383l.307-2.772-.307-2.982c-.024-.218-.204-.383-.423-.383zm1.8-.24c-.245 0-.444.183-.465.428l-.235 3.207.235 2.753c.021.245.22.428.465.428.244 0 .443-.183.464-.428l.266-2.753-.266-3.207c-.021-.245-.22-.428-.464-.428zm1.813-.28c-.268 0-.487.2-.505.468l-.2 3.432.2 2.735c.018.268.237.467.505.467.267 0 .486-.199.504-.467l.228-2.735-.228-3.432c-.018-.268-.237-.468-.504-.468zm1.833-.26c-.292 0-.53.218-.547.51l-.164 3.66.164 2.717c.017.29.255.51.547.51.29 0 .529-.22.546-.51l.186-2.717-.186-3.66c-.017-.292-.256-.51-.546-.51zm1.856-.23c-.315 0-.572.237-.585.553l-.128 3.87.128 2.697c.013.315.27.552.585.552.314 0 .57-.237.584-.552l.146-2.697-.146-3.87c-.014-.316-.27-.553-.584-.553zm1.864-.16c-.34 0-.615.256-.625.596l-.092 4.03.092 2.677c.01.34.285.596.625.596.338 0 .614-.256.623-.596l.105-2.677-.105-4.03c-.01-.34-.285-.596-.623-.596zm2.31 1.054c-.086-.034-.18-.05-.275-.05-.17 0-.33.05-.463.14-.135-1.535-1.42-2.733-2.984-2.733-.413 0-.806.085-1.16.24-.137.055-.173.11-.175.163v10.847c.002.056.044.103.1.11h4.96c.54 0 .977-.438.977-.977V13.21c0-.48-.35-.887-.82-.993a1.49 1.49 0 00-.16-.017z"/></svg>`;

    const SC_ICON_EMPTY = `<svg viewBox="0 0 24 24" fill="currentColor" width="48" height="48" style="color:#f50;opacity:.3"><path d="M1.175 12.225c-.15 0-.254.097-.282.25l-.357 2.285.357 2.223c.028.148.133.245.282.245.147 0 .252-.097.283-.245l.405-2.223-.405-2.285c-.031-.153-.136-.25-.283-.25zm1.675-.69c-.172 0-.303.118-.33.285l-.303 2.94.303 2.813c.027.163.158.28.33.28.17 0 .3-.117.328-.28l.344-2.813-.344-2.94c-.028-.167-.158-.285-.328-.285zm1.73-.17c-.196 0-.354.14-.38.332L3.9 14.25l.3 2.793c.026.192.184.333.38.333.195 0 .354-.14.38-.333l.34-2.793-.34-2.553c-.026-.192-.185-.332-.38-.332zm1.78-.48c-.22 0-.4.165-.423.383l-.27 2.982.27 2.772c.023.218.203.383.422.383.22 0 .4-.165.424-.383l.307-2.772-.307-2.982c-.024-.218-.204-.383-.423-.383zm1.8-.24c-.245 0-.444.183-.465.428l-.235 3.207.235 2.753c.021.245.22.428.465.428.244 0 .443-.183.464-.428l.266-2.753-.266-3.207c-.021-.245-.22-.428-.464-.428zm1.813-.28c-.268 0-.487.2-.505.468l-.2 3.432.2 2.735c.018.268.237.467.505.467.267 0 .486-.199.504-.467l.228-2.735-.228-3.432c-.018-.268-.237-.468-.504-.468zm1.833-.26c-.292 0-.53.218-.547.51l-.164 3.66.164 2.717c.017.29.255.51.547.51.29 0 .529-.22.546-.51l.186-2.717-.186-3.66c-.017-.292-.256-.51-.546-.51zm1.856-.23c-.315 0-.572.237-.585.553l-.128 3.87.128 2.697c.013.315.27.552.585.552.314 0 .57-.237.584-.552l.146-2.697-.146-3.87c-.014-.316-.27-.553-.584-.553zm1.864-.16c-.34 0-.615.256-.625.596l-.092 4.03.092 2.677c.01.34.285.596.625.596.338 0 .614-.256.623-.596l.105-2.677-.105-4.03c-.01-.34-.285-.596-.623-.596zm2.31 1.054c-.086-.034-.18-.05-.275-.05-.17 0-.33.05-.463.14-.135-1.535-1.42-2.733-2.984-2.733-.413 0-.806.085-1.16.24-.137.055-.173.11-.175.163v10.847c.002.056.044.103.1.11h4.96c.54 0 .977-.438.977-.977V13.21c0-.48-.35-.887-.82-.993a1.49 1.49 0 00-.16-.017z"/></svg>`;

    // Public: allow external link from empty state
    function _switchToScan() {
        switchTab('scan');
        renderScanTab();
    }

    return { load, unload, _switchToScan };
})();
