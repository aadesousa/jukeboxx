// ─── Playlist Sync Page ──────────────────────────────────────────────────────
const PlaylistsPage = (() => {
    const root = () => document.getElementById('page-root');

    let spotifyPlaylists = [];
    let syncItems        = [];
    let dlStatus         = {};
    let _scLocalCounts   = {};
    let _pollTimer       = null;
    let _scPollTimer     = null;

    // ── Load ─────────────────────────────────────────────────────────────
    async function load() {
        spotifyPlaylists = [];
        syncItems = [];
        dlStatus  = {};
        root().innerHTML = buildShell();
        await loadData();
    }

    function unload() {
        spotifyPlaylists = [];
        syncItems        = [];
        dlStatus         = {};
        _scLocalCounts   = {};
        _stopPoll();
        _stopScPoll();
    }

    async function loadData() {
        const content = document.getElementById('pl-content');
        if (!content) return;
        content.innerHTML = buildSkeleton();

        let spotifyConnected = false;
        try {
            const status = await api.get('/spotify/status');
            spotifyConnected = !!status.connected;
        } catch {}

        try {
            const itemsPromise   = api.get('/sync/items');
            const lcPromise      = api.get('/soundcloud/local-counts').catch(() => ({}));
            const spotifyPromise = spotifyConnected
                ? api.get('/spotify/playlists').then(d => d.items || d || []).catch(() => [])
                : Promise.resolve([]);

            let localCounts = {};
            [spotifyPlaylists, syncItems, localCounts] = await Promise.all([
                spotifyPromise, itemsPromise, lcPromise,
            ]);
            // Store on module state for SC section rebuilds
            _scLocalCounts = localCounts;
        } catch(e) {
            content.innerHTML = `<div class="empty-state" style="padding-top:40px">
                <div class="empty-state-title">Failed to load</div>
                <div class="empty-state-body">${esc(e.message)}</div>
                <button class="btn" onclick="PlaylistsPage.reload()" style="margin-top:12px">Retry</button>
            </div>`;
            return;
        }

        renderAll(spotifyConnected);
        // no SC download polling needed here — playlists page doesn't show download progress
    }

    // ── Render ────────────────────────────────────────────────────────────
    function renderAll(spotifyConnected) {
        const content = document.getElementById('pl-content');
        if (!content) return;
        content.innerHTML = '';

        // — Spotify section —
        const spotifySection = document.createElement('div');
        spotifySection.id = 'pl-spotify-section';
        content.appendChild(spotifySection);
        if (spotifyConnected) {
            renderSpotifyTable(spotifySection);
        } else {
            renderSpotifyDisconnected(spotifySection);
        }

        // — SoundCloud section —
        const scSection = document.createElement('div');
        scSection.id = 'pl-sc-section';
        scSection.style.cssText = 'margin-top:40px';
        content.appendChild(scSection);
        renderScSection(scSection);
    }

    // ── Spotify table ─────────────────────────────────────────────────────
    function renderSpotifyTable(container) {
        const syncedMap = {};
        syncItems.filter(s => s.item_type === 'playlist').forEach(s => {
            syncedMap[s.spotify_id] = s;
        });
        const syncCount = Object.keys(syncedMap).length;

        const rows = spotifyPlaylists.map(pl => {
            const synced = syncedMap[pl.id];
            const thumb  = (pl.images || [])[0]?.url;
            const spotifyTotal = pl.tracks?.total || 0;

            let coverageCell  = `<span style="color:var(--text-muted);font-size:.8rem">—</span>`;
            let lastSyncedCell = `<span style="color:var(--text-muted);font-size:.75rem">Never</span>`;
            let statusCell    = `<span style="color:var(--text-muted);font-size:.8rem">Not synced</span>`;

            if (synced) {
                const local  = synced.local_count   || 0;
                const total  = synced.track_count   || spotifyTotal || 0;
                const unavail = synced.unavailable_count || 0;
                const pct    = total > 0 ? Math.round(local / total * 100) : 0;
                const pctColor = pct >= 80 ? 'var(--green)' : pct >= 40 ? 'var(--orange)' : 'var(--red)';

                coverageCell = total > 0
                    ? `<div style="min-width:100px">
                        <div style="display:flex;justify-content:space-between;font-size:.78rem;margin-bottom:3px">
                            <span style="color:${pctColor};font-weight:500">${local}/${total}</span>
                            <span style="color:var(--text-muted)">${unavail > 0 ? `${unavail} unavail` : ''}</span>
                        </div>
                        <div style="height:3px;background:var(--bg-elevated);border-radius:99px;overflow:hidden">
                            <div style="height:100%;width:${pct}%;background:${pctColor};border-radius:99px;transition:width .3s"></div>
                        </div>
                       </div>`
                    : `<span style="color:var(--text-muted);font-size:.8rem">Not synced yet</span>`;

                lastSyncedCell = synced.last_synced_at
                    ? `<span style="font-size:.75rem;color:var(--text-dim)" title="${esc(synced.last_synced_at)}">${timeAgo(synced.last_synced_at)}</span>`
                    : `<span style="color:var(--text-muted);font-size:.75rem">Never</span>`;

                statusCell = `<span style="color:var(--green);font-size:.8rem">● Active</span>`;
            }

            return `
            <tr class="arr-table-row">
                <td style="width:44px;padding:6px">
                    ${thumb
                        ? `<img src="${esc(thumb)}" style="width:36px;height:36px;object-fit:cover;border-radius:3px">`
                        : `<div style="width:36px;height:36px;background:var(--bg-raised);border-radius:3px"></div>`}
                </td>
                <td style="font-weight:500;max-width:180px">
                    <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(pl.name)}</div>
                    <div style="font-size:.72rem;color:var(--text-muted)">${spotifyTotal} on Spotify</div>
                </td>
                <td style="min-width:120px">${coverageCell}</td>
                <td>${lastSyncedCell}</td>
                <td>${statusCell}</td>
                <td style="white-space:nowrap">
                    ${synced
                        ? `<div style="display:flex;gap:4px">
                               <button class="btn-xs btn-primary pl-sync-now" data-sync-id="${synced.id}" data-name="${esc(pl.name)}">Sync Now</button>
                               <button class="btn-xs btn-danger pl-remove" data-sync-id="${synced.id}">Remove</button>
                           </div>`
                        : `<button class="btn-xs btn-primary pl-add" data-playlist-id="${esc(pl.id)}" data-name="${esc(pl.name)}">Add to Sync</button>`}
                </td>
            </tr>`;
        });

        container.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;padding:8px 0 16px;flex-wrap:wrap">
            <span style="font-size:.85rem;color:var(--text-dim)">${spotifyPlaylists.length} playlists · ${syncCount} synced</span>
            <span style="flex:1"></span>
            <button class="btn btn-sm btn-primary" id="pl-sync-now-btn">Sync Now</button>
            <button class="btn btn-sm" id="pl-sync-all-btn" ${syncCount === 0 ? 'disabled' : ''}>
                Sync All (${syncCount})
            </button>
        </div>
        ${rows.length === 0
            ? `<div class="empty-state" style="padding-top:40px"><div class="empty-state-title">No Playlists Found</div></div>`
            : `<table class="arr-table" style="width:100%">
                <thead><tr>
                    <th style="width:44px"></th>
                    <th>Name</th>
                    <th style="min-width:120px">Library Coverage</th>
                    <th>Last Synced</th>
                    <th>Status</th>
                    <th style="width:160px">Actions</th>
                </tr></thead>
                <tbody>${rows.join('')}</tbody>
               </table>`}`;

        document.getElementById('pl-sync-all-btn')?.addEventListener('click', syncAll);

        const syncNowBtn = document.getElementById('pl-sync-now-btn');
        syncNowBtn?.addEventListener('click', async () => {
            syncNowBtn.disabled = true;
            syncNowBtn.textContent = 'Syncing…';
            try {
                await api.post('/sync/run-now', {});
                toast('Sync started', 'info');
                // Poll progress
                const poll = setInterval(async () => {
                    try {
                        const prog = await api.get('/sync/progress');
                        if (prog && prog.playlist_total > 0) {
                            syncNowBtn.textContent = `Syncing ${prog.playlist_index}/${prog.playlist_total}…`;
                        }
                        if (!prog || !prog.running) {
                            clearInterval(poll);
                            syncNowBtn.disabled = false;
                            syncNowBtn.textContent = 'Sync Now';
                            toast('Sync complete', 'success');
                            await loadData();
                        }
                    } catch (_e) {
                        clearInterval(poll);
                        syncNowBtn.disabled = false;
                        syncNowBtn.textContent = 'Sync Now';
                    }
                }, 2000);
                // Safety timeout after 120s
                setTimeout(() => {
                    clearInterval(poll);
                    syncNowBtn.disabled = false;
                    syncNowBtn.textContent = 'Sync Now';
                }, 120000);
            } catch (e) {
                toast('Failed to start sync: ' + e.message, 'error');
                syncNowBtn.disabled = false;
                syncNowBtn.textContent = 'Sync Now';
            }
        });
        container.querySelectorAll('.pl-add').forEach(btn => {
            btn.addEventListener('click', () => addToSync(btn.dataset.playlistId, btn.dataset.name));
        });
        container.querySelectorAll('.pl-remove').forEach(btn => {
            btn.addEventListener('click', () => removeSync(btn.dataset.syncId));
        });
        container.querySelectorAll('.pl-sync-now').forEach(btn => {
            btn.addEventListener('click', () => syncNow(btn.dataset.syncId, btn.dataset.name, btn));
        });
    }

    function renderSpotifyDisconnected(container) {
        container.innerHTML = `
        <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:20px;display:flex;align-items:center;gap:14px">
            <svg viewBox="0 0 24 24" fill="currentColor" width="28" height="28" style="color:var(--teal);opacity:.5;flex-shrink:0">
                <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/>
            </svg>
            <div>
                <div style="font-weight:500;margin-bottom:2px">Spotify not connected</div>
                <div style="font-size:.8rem;color:var(--text-dim)">Connect Spotify in Settings to sync playlists to Jellyfin M3U files.</div>
            </div>
            <a class="btn btn-sm btn-primary" href="#/settings/spotify" style="margin-left:auto;flex-shrink:0">Connect Spotify</a>
        </div>`;
    }

    // ── SoundCloud section ────────────────────────────────────────────────
    const SC_ICON = `<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18" style="color:#f50;flex-shrink:0"><path d="M1.175 12.225c-.15 0-.254.097-.282.25l-.357 2.285.357 2.223c.028.148.133.245.282.245.147 0 .252-.097.283-.245l.405-2.223-.405-2.285c-.031-.153-.136-.25-.283-.25zm1.675-.69c-.172 0-.303.118-.33.285l-.303 2.94.303 2.813c.027.163.158.28.33.28.17 0 .3-.117.328-.28l.344-2.813-.344-2.94c-.028-.167-.158-.285-.328-.285zm1.73-.17c-.196 0-.354.14-.38.332L3.9 14.25l.3 2.793c.026.192.184.333.38.333.195 0 .354-.14.38-.333l.34-2.793-.34-2.553c-.026-.192-.185-.332-.38-.332zm1.78-.48c-.22 0-.4.165-.423.383l-.27 2.982.27 2.772c.023.218.203.383.422.383.22 0 .4-.165.424-.383l.307-2.772-.307-2.982c-.024-.218-.204-.383-.423-.383zm1.8-.24c-.245 0-.444.183-.465.428l-.235 3.207.235 2.753c.021.245.22.428.465.428.244 0 .443-.183.464-.428l.266-2.753-.266-3.207c-.021-.245-.22-.428-.464-.428zm1.813-.28c-.268 0-.487.2-.505.468l-.2 3.432.2 2.735c.018.268.237.467.505.467.267 0 .486-.199.504-.467l.228-2.735-.228-3.432c-.018-.268-.237-.468-.504-.468zm1.833-.26c-.292 0-.53.218-.547.51l-.164 3.66.164 2.717c.017.29.255.51.547.51.29 0 .529-.22.546-.51l.186-2.717-.186-3.66c-.017-.292-.256-.51-.546-.51zm1.856-.23c-.315 0-.572.237-.585.553l-.128 3.87.128 2.697c.013.315.27.552.585.552.314 0 .57-.237.584-.552l.146-2.697-.146-3.87c-.014-.316-.27-.553-.584-.553zm1.864-.16c-.34 0-.615.256-.625.596l-.092 4.03.092 2.677c.01.34.285.596.625.596.338 0 .614-.256.623-.596l.105-2.677-.105-4.03c-.01-.34-.285-.596-.623-.596zm2.31 1.054c-.086-.034-.18-.05-.275-.05-.17 0-.33.05-.463.14-.135-1.535-1.42-2.733-2.984-2.733-.413 0-.806.085-1.16.24-.137.055-.173.11-.175.163v10.847c.002.056.044.103.1.11h4.96c.54 0 .977-.438.977-.977V13.21c0-.48-.35-.887-.82-.993a1.49 1.49 0 00-.16-.017z"/></svg>`;

    function renderScSection(container) {
        const scItems = syncItems.filter(s => s.item_type === 'soundcloud');

        container.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">
            ${SC_ICON}
            <h2 style="margin:0;font-size:1rem;font-weight:600">SoundCloud Playlists</h2>
            <span style="font-size:.8rem;color:var(--text-dim)" id="sc-count-label">${scItems.length} imported</span>
            <span style="flex:1"></span>
            <a href="#/soundcloud" class="btn btn-sm">Download / Manage →</a>
        </div>
        <div id="pl-sc-list">
            ${buildScRows(scItems)}
        </div>`;

        bindScSyncEvents(container);
    }

    function buildScRows(scItems) {
        if (scItems.length === 0) {
            return `<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:16px;display:flex;align-items:center;gap:12px">
                <span style="font-size:.85rem;color:var(--text-dim)">No SoundCloud playlists imported yet.</span>
                <a href="#/soundcloud" class="btn btn-sm btn-primary" style="margin-left:auto">Add Playlists →</a>
            </div>`;
        }

        const rows = scItems.map(s => {
            const thumb = s.image_url
                ? `<img src="${esc(s.image_url)}" style="width:36px;height:36px;object-fit:cover;border-radius:3px">`
                : `<div style="width:36px;height:36px;background:var(--bg-raised);border-radius:3px;display:flex;align-items:center;justify-content:center">${SC_ICON}</div>`;

            const localCount = _scLocalCounts[String(s.id)];
            const notDownloaded = localCount === undefined || localCount === -1;
            const trackTotal = s.track_count || 0;

            // Coverage cell
            let coverageCell;
            if (notDownloaded) {
                coverageCell = `<span style="color:var(--text-muted);font-size:.8rem">Not downloaded</span>`;
            } else {
                const pct = trackTotal > 0 ? Math.round(localCount / trackTotal * 100) : 100;
                const pctColor = pct >= 80 ? 'var(--green)' : pct >= 40 ? 'var(--orange)' : 'var(--red)';
                coverageCell = `<div style="min-width:100px">
                    <div style="display:flex;justify-content:space-between;font-size:.78rem;margin-bottom:3px">
                        <span style="color:${pctColor};font-weight:500">${localCount}${trackTotal ? '/'+trackTotal : ''} files</span>
                    </div>
                    <div style="height:3px;background:var(--bg-elevated);border-radius:99px;overflow:hidden">
                        <div style="height:100%;width:${Math.min(pct,100)}%;background:${pctColor};border-radius:99px;transition:width .3s"></div>
                    </div>
                </div>`;
            }

            // Last synced cell
            const lastSyncedCell = s.last_synced_at
                ? `<span style="font-size:.75rem;color:var(--text-dim)" title="${esc(s.last_synced_at)}">${timeAgo(s.last_synced_at)}</span>`
                : `<span style="font-size:.75rem;color:var(--text-muted)">Never</span>`;

            // Action cell — Sync Now only if downloaded, otherwise link to SoundCloud page
            const actionCell = notDownloaded
                ? `<a href="#/soundcloud" class="btn-xs">Download first →</a>`
                : `<button class="btn-xs btn-primary sc-sync-now" data-id="${s.id}" data-name="${esc(s.name||'')}">Sync Now</button>`;

            return `<tr class="arr-table-row">
                <td style="width:44px;padding:6px">${thumb}</td>
                <td style="font-weight:500;max-width:180px">
                    <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(s.name||s.spotify_id)}</div>
                    <div style="font-size:.72rem;color:var(--text-muted)">${trackTotal || '?'} tracks</div>
                </td>
                <td style="min-width:120px">${coverageCell}</td>
                <td>${lastSyncedCell}</td>
                <td><span style="color:${notDownloaded ? 'var(--text-muted)' : 'var(--green)'};font-size:.8rem">${notDownloaded ? '○ Not downloaded' : '● Ready'}</span></td>
                <td style="white-space:nowrap">${actionCell}</td>
            </tr>`;
        });

        return `<table class="arr-table" style="width:100%">
            <thead><tr>
                <th style="width:44px"></th>
                <th>Playlist</th>
                <th style="min-width:120px">Local Files</th>
                <th>Last Synced</th>
                <th>Status</th>
                <th style="width:140px">Actions</th>
            </tr></thead>
            <tbody>${rows.join('')}</tbody>
        </table>`;
    }

    function bindScSyncEvents(container) {
        container.querySelectorAll('.sc-sync-now').forEach(btn => {
            btn.addEventListener('click', () => scSyncNow(+btn.dataset.id, btn.dataset.name, btn));
        });
    }

    function _rebuildScRows() {
        const scItems = syncItems.filter(s => s.item_type === 'soundcloud');
        const listEl  = document.getElementById('pl-sc-list');
        if (!listEl) return;
        listEl.innerHTML = buildScRows(scItems);
        const scSection = document.getElementById('pl-sc-section');
        if (scSection) bindScSyncEvents(scSection);
        const countEl = document.getElementById('sc-count-label');
        if (countEl) countEl.textContent = `${scItems.length} imported`;
    }

    function _stopScPoll() {
        if (_scPollTimer) { clearInterval(_scPollTimer); _scPollTimer = null; }
    }

    // ── SC sync action ────────────────────────────────────────────────────
    async function scSyncNow(syncId, name, btn) {
        if (btn) { btn.disabled = true; btn.textContent = 'Syncing…'; }
        showProgressBar(`Generating M3U for "${name}"…`, null, null);
        try {
            const r = await api.post(`/sync/items/${syncId}/sync`);
            if (r.status === 'ok') {
                finishProgressBar(`"${name}" — ${r.matched} tracks synced to Jellyfin M3U`);
            } else {
                finishProgressBar(r.detail || `No audio files found for "${name}" — download it first on the SoundCloud page.`, true);
            }
            syncItems = await api.get('/sync/items');
            _rebuildScRows();
        } catch(e) {
            finishProgressBar(`Sync failed: ${e.message}`, true);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = 'Sync Now'; }
        }
    }

    // ── Spotify actions ───────────────────────────────────────────────────
    async function addToSync(playlistId, name) {
        try {
            await api.post('/sync/items', { spotify_id: playlistId, item_type: 'playlist', name });
            toast(`Added "${name}" to sync`, 'success');
            await loadData();
        } catch(e) {
            toast('Failed: ' + e.message, 'error');
        }
    }

    async function removeSync(syncId) {
        if (!confirm('Remove this playlist from sync? The M3U file will remain.')) return;
        try {
            await api.del(`/sync/items/${syncId}`);
            toast('Removed from sync', 'success');
            await loadData();
        } catch(e) {
            toast('Failed: ' + e.message, 'error');
        }
    }

    async function syncNow(syncId, name, btn) {
        btn.disabled = true;
        btn.textContent = 'Syncing…';
        showProgressBar(`Generating M3U for "${name}"…`, null, null);
        try {
            const r = await api.post(`/sync/items/${syncId}/sync`);
            const pct = r.total > 0 ? Math.round(r.matched / r.total * 100) : 0;
            if (r.status === 'ok') {
                finishProgressBar(`"${name}" — ${r.matched}/${r.total} tracks matched (${pct}%)`);
            } else {
                finishProgressBar(`No tracks matched for "${name}" (0/${r.total || '?'})`, true);
            }
            await loadData();
        } catch(e) {
            finishProgressBar(`Sync failed: ${e.message}`, true);
            btn.disabled = false;
            btn.textContent = 'Sync Now';
        }
    }

    async function syncAll() {
        const btn = document.getElementById('pl-sync-all-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Syncing…'; }
        try {
            await api.post('/sync/run');
        } catch(e) {
            toast('Failed to start sync: ' + e.message, 'error');
            if (btn) { btn.disabled = false; btn.textContent = 'Sync All'; }
            return;
        }
        _startPoll();
    }

    // ── Progress bar (Spotify sync) ───────────────────────────────────────
    function _progressBarEl() { return document.getElementById('pl-progress-wrap'); }

    function showProgressBar(label, pct, sub) {
        let wrap = _progressBarEl();
        if (!wrap) {
            const content = document.getElementById('pl-content');
            if (!content) return;
            wrap = document.createElement('div');
            wrap.id = 'pl-progress-wrap';
            wrap.style.cssText = 'margin-bottom:18px;';
            content.insertAdjacentElement('afterbegin', wrap);
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

    function finishProgressBar(msg, isError = false) {
        _stopPoll();
        const wrap = _progressBarEl();
        if (!wrap) return;
        const color = isError ? '#ef4444' : 'var(--green)';
        wrap.innerHTML = `
            <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:10px;padding:12px 16px;display:flex;align-items:center;gap:10px">
                <span style="font-size:1rem">${isError ? '✗' : '✓'}</span>
                <span style="font-size:.85rem;color:${color}">${esc(msg)}</span>
                <button onclick="this.closest('#pl-progress-wrap').remove()" style="margin-left:auto;background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:.85rem">✕</button>
            </div>`;
    }

    function _startPoll() {
        _stopPoll();
        _pollTimer = setInterval(_pollProgress, 300);
        _pollProgress();
    }

    function _stopPoll() {
        if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    }

    async function _pollProgress() {
        let p;
        try { p = await api.get('/sync/progress'); } catch { return; }

        const phase   = p.phase || '';
        const pi      = p.playlist_index || 0;
        const pt      = p.playlist_total || 0;
        const ti      = p.track_index    || 0;
        const tt      = p.track_total    || 0;
        const matched = p.matched        || 0;
        const name    = p.playlist_name  || '';

        const overallPct = pt > 0
            ? Math.round(((pi - 1 + (tt > 0 ? ti / tt : 0)) / pt) * 100)
            : null;

        let label = 'Syncing…';
        let sub   = '';

        if (phase === 'fetching_tracks') {
            label = `Fetching tracks for "${name}" (${pi}/${pt})`;
            sub   = 'Pulling track list from Spotify…';
        } else if (phase === 'matching') {
            const pct = tt > 0 ? Math.round(matched / tt * 100) : 0;
            label = `Matching "${name}" — playlist ${pi} of ${pt}`;
            sub   = `${matched} of ${tt} tracks found in library (${pct}%)${ti < tt ? ` · checking track ${ti}/${tt}` : ''}`;
        } else if (phase === 'generating_m3u') {
            label = 'Writing M3U playlist files…';
            sub   = 'All playlists matched · saving files for Jellyfin';
        } else if (phase === 'refreshing_account') {
            label = 'Refreshing playlist list from Spotify…';
        } else if (phase === 'done') {
            const results      = p.results || [];
            const totalMatched = results.reduce((s, r) => s + (r.matched || 0), 0);
            const totalTracks  = results.reduce((s, r) => s + (r.total   || 0), 0);
            const pct          = totalTracks > 0 ? Math.round(totalMatched / totalTracks * 100) : 0;
            _stopPoll();
            finishProgressBar(`Sync complete — ${results.length} playlist${results.length !== 1 ? 's' : ''} · ${totalMatched}/${totalTracks} tracks matched (${pct}%)`);
            const btn = document.getElementById('pl-sync-all-btn');
            if (btn) { btn.disabled = false; btn.textContent = `Sync All (${pt || results.length})`; }
            await loadData();
            return;
        } else if (phase === 'error' || phase === 'aborted') {
            _stopPoll();
            finishProgressBar(p.error || 'Sync failed', true);
            const btn = document.getElementById('pl-sync-all-btn');
            if (btn) { btn.disabled = false; btn.textContent = 'Sync All'; }
            return;
        } else if (!p.running && phase !== 'starting') {
            _stopPoll();
            return;
        }

        if (p.running) showProgressBar(label, overallPct, sub);
    }

    // ── Shell / skeleton ──────────────────────────────────────────────────
    function buildShell() {
        return `
        <div class="page-header">
            <div class="page-header-left">
                <h1 class="page-title">Playlist Sync</h1>
                <div class="page-subtitle">Sync Spotify playlists · Download SoundCloud playlists</div>
            </div>
        </div>
        <div id="pl-content" style="padding:0 24px 80px"></div>`;
    }

    function buildSkeleton() {
        return `<div style="padding:16px 0">` +
            Array.from({length: 6}, () => `
            <div style="display:flex;gap:12px;padding:10px 0;border-top:1px solid var(--border)">
                <div class="skeleton" style="width:36px;height:36px;border-radius:3px;flex-shrink:0"></div>
                <div style="flex:1">
                    <div class="skeleton" style="height:13px;width:40%;border-radius:3px;margin-bottom:6px"></div>
                    <div class="skeleton" style="height:10px;width:20%;border-radius:3px"></div>
                </div>
            </div>`).join('') + `</div>`;
    }

    function esc(s) {
        return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function toast(msg, type) {
        if (typeof window.toast === 'function') window.toast(msg, type);
    }

    function reload() { loadData(); }

    return { load, unload, reload };
})();
