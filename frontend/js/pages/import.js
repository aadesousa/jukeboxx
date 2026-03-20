// ─── Import Page — Phase 5 ─────────────────────────────────────────
const ImportPage = (() => {
    const root = () => document.getElementById('page-root');

    // State
    let activeSource = 'liked';   // liked | albums | artists | playlists
    let items     = [];
    let selected  = new Set();    // spotify_ids of selected items
    let loading   = false;
    let offset    = 0;
    let total     = 0;
    let hasMore   = false;
    let nextCursor = null;        // for followed-artists pagination
    let activePlaylistId   = null;
    let activePlaylistName = '';
    let filterMode = 'not-monitored';  // all | not-local | not-monitored

    const SOURCES = [
        { id: 'liked',    label: '♥ Liked Songs',       icon: heartIcon() },
        { id: 'albums',   label: '💿 Saved Albums',     icon: albumIcon() },
        { id: 'artists',  label: '👤 Followed Artists', icon: artistIcon() },
        { id: 'playlists',label: '▶ Playlists',         icon: playlistIcon() },
    ];

    // ── Load ─────────────────────────────────────────────────────────
    async function load(params) {
        items = []; selected = new Set(); offset = 0; total = 0;
        hasMore = false; nextCursor = null; activePlaylistId = null;
        filterMode = 'not-monitored';

        root().innerHTML = buildShell();
        bindShellEvents();

        // Check Spotify connection first
        try {
            const status = await api.get('/spotify/status');
            if (!status.connected) {
                showDisconnected();
                return;
            }
        } catch { showDisconnected(); return; }

        loadSource();
    }

    function unload() {
        items = []; selected = new Set();
    }

    // ── Shell ─────────────────────────────────────────────────────────
    function buildShell() {
        return `
        <div class="page-header">
            <div class="page-header-left">
                <h1 class="page-title">Import</h1>
                <div class="page-subtitle" id="import-subtitle">Showing unmonitored items</div>
            </div>
        </div>

        <div class="section-tabs" id="import-source-tabs" style="margin:0 24px 0;flex-shrink:0">
            ${SOURCES.map(s => `
                <button class="section-tab ${s.id === activeSource ? 'active' : ''}" data-source="${s.id}">
                    ${s.label}
                </button>`).join('')}
        </div>

        <div style="padding:12px 24px 6px;display:flex;align-items:center;gap:8px;flex-wrap:wrap" id="import-filter-bar">
            <div class="filter-group" id="import-filter-btns">
                <button class="filter-btn" data-filter="all">All</button>
                <button class="filter-btn active" data-filter="not-monitored">Unmonitored</button>
                <button class="filter-btn" data-filter="not-local">Not Local</button>
            </div>
        </div>

        <div id="import-content" style="flex:1;overflow-y:auto;padding:0 0 80px"></div>

        <div class="mass-edit-bar" id="import-action-bar" hidden style="z-index:50">
            <span id="import-action-label">0 selected</span>
            <button class="btn btn-primary" id="import-confirm-btn">Import Selected</button>
        </div>`;
    }

    function showDisconnected() {
        document.getElementById('import-content').innerHTML = `
        <div class="empty-state" style="padding-top:60px">
            <svg viewBox="0 0 24 24" fill="currentColor" width="48" height="48" style="color:var(--teal);opacity:.5">
                <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/>
            </svg>
            <div class="empty-state-title">Spotify Not Connected</div>
            <div class="empty-state-body">Connect your Spotify account in Settings to use the import wizard.</div>
            <a class="btn btn-primary" href="#/settings/spotify" style="margin-top:12px">Go to Settings</a>
        </div>`;
        document.getElementById('import-filter-bar').hidden = true;
        document.getElementById('import-source-tabs').style.display = 'none';
    }

    // ── Source loading ────────────────────────────────────────────────
    async function loadSource() {
        items = []; selected = new Set(); offset = 0; total = 0;
        hasMore = false; nextCursor = null; activePlaylistId = null;
        filterMode = 'not-monitored';

        // Reset filter buttons to 'not-monitored'
        document.querySelectorAll('#import-filter-btns .filter-btn').forEach(b =>
            b.classList.toggle('active', b.dataset.filter === 'not-monitored')
        );

        updateActionBar();
        updateSubtitle();

        const content = document.getElementById('import-content');
        content.innerHTML = buildLoadingState();

        try {
            if (activeSource === 'liked')     await loadLikedSongs();
            if (activeSource === 'albums')    await loadSavedAlbums();
            if (activeSource === 'artists')   await loadFollowedArtists();
            if (activeSource === 'playlists') await loadPlaylists();
        } catch (e) {
            content.innerHTML = `<div class="empty-state" style="padding-top:40px">
                <div class="empty-state-title">Failed to load</div>
                <div class="empty-state-body">${esc(e.message)}</div>
                <button class="btn" onclick="ImportPage.reload()" style="margin-top:12px">Retry</button>
            </div>`;
        }
    }

    // ── Subtitle ──────────────────────────────────────────────────────
    function updateSubtitle() {
        const el = document.getElementById('import-subtitle');
        if (!el) return;
        let filterLabel = filterMode === 'not-monitored' ? 'unmonitored'
                        : filterMode === 'not-local' ? 'not local'
                        : 'all';
        const count = activeSource === 'playlists' && !activePlaylistId
            ? `${items.length} total`
            : `${total || items.length} total`;
        el.textContent = `Showing ${filterLabel} items · ${count}`;
    }

    // ── Liked Songs ───────────────────────────────────────────────────
    async function loadLikedSongs() {
        const data = await api.get(`/spotify/liked-songs?offset=0&limit=50`);
        items  = data.items || [];
        total  = data.total || 0;
        hasMore = items.length < total;
        offset  = items.length;

        // Auto-select items that aren't already local/monitored
        items.forEach(t => {
            if (!t.monitored_status) selected.add(t.spotify_id);
        });

        renderLikedSongs();
    }

    async function loadMoreLikedSongs() {
        if (loading || !hasMore) return;
        loading = true;
        const btn = document.getElementById('load-more-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
        try {
            const data = await api.get(`/spotify/liked-songs?offset=${offset}&limit=50`);
            const newItems = data.items || [];
            newItems.forEach(t => { if (!t.monitored_status) selected.add(t.spotify_id); });
            items = items.concat(newItems);
            offset += newItems.length;
            hasMore = offset < (data.total || 0);
            renderLikedSongs();
        } catch (e) { toast('Failed to load more: ' + e.message, 'error'); }
        loading = false;
    }

    function renderLikedSongs() {
        const visible = applyFilter(items);
        const content = document.getElementById('import-content');
        if (!content) return;

        const rows = visible.map(buildTrackRow).join('');

        content.innerHTML = `
        <div style="font-size:.8rem;color:var(--text-dim);padding:8px 24px 4px">
            ${total} songs · ${selected.size} selected
        </div>
        <table class="arr-table" style="width:100%">
            <thead>
                <tr>
                    <th style="width:36px"><input type="checkbox" id="select-all-visible" style="accent-color:var(--accent)"></th>
                    <th></th>
                    <th>Title</th>
                    <th>Artist</th>
                    <th>Album</th>
                    <th style="width:70px;text-align:right">Duration</th>
                    <th style="width:100px">Status</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
        ${hasMore ? `<div style="text-align:center;padding:16px">
            <button class="btn" id="load-more-btn">Load More (${total - offset} remaining)</button>
        </div>` : ''}`;

        bindTrackRowEvents();
        document.getElementById('load-more-btn')?.addEventListener('click', loadMoreLikedSongs);
        document.getElementById('select-all-visible')?.addEventListener('change', e => {
            const checked = e.target.checked;
            visible.forEach(t => { if (checked) selected.add(t.spotify_id); else selected.delete(t.spotify_id); });
            renderLikedSongs();
            updateActionBar();
        });

        updateActionBar();
        updateSubtitle();
    }

    function buildTrackRow(t) {
        const isSelected = selected.has(t.spotify_id);
        const statusBadge = buildStatusBadge(t.monitored_status);
        const dur = t.duration_ms ? formatDuration(Math.round(t.duration_ms / 1000)) : '—';
        const thumb = t.image_url || t.album_image
            ? `<img src="${esc(t.image_url || t.album_image)}" style="width:36px;height:36px;object-fit:cover;border-radius:2px">`
            : `<div style="width:36px;height:36px;background:var(--bg-raised);border-radius:2px"></div>`;

        return `
        <tr class="arr-table-row import-track-row ${t.monitored_status === 'have' ? 'row-dimmed' : ''}" data-id="${esc(t.spotify_id)}">
            <td><input type="checkbox" class="import-cb" data-id="${esc(t.spotify_id)}" ${isSelected ? 'checked' : ''} style="accent-color:var(--accent)"></td>
            <td style="width:44px;padding:6px 4px">${thumb}</td>
            <td style="max-width:220px"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.name)}</div></td>
            <td style="max-width:160px;color:var(--text-dim)"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.artist_name || '')}</div></td>
            <td style="max-width:160px;color:var(--text-muted)"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.album_name || '')}</div></td>
            <td style="text-align:right;color:var(--text-muted)">${dur}</td>
            <td>${statusBadge}</td>
        </tr>`;
    }

    function bindTrackRowEvents() {
        document.querySelectorAll('.import-cb').forEach(cb => {
            cb.addEventListener('change', e => {
                const id = e.target.dataset.id;
                if (e.target.checked) selected.add(id);
                else selected.delete(id);
                updateActionBar();
            });
        });
    }

    // ── Saved Albums ──────────────────────────────────────────────────
    async function loadSavedAlbums() {
        const data = await api.get(`/spotify/saved-albums?offset=0&limit=50`);
        items  = data.items || [];
        total  = data.total || 0;
        hasMore = items.length < total;
        offset  = items.length;

        items.forEach(a => { if (!a.monitored_status) selected.add(a.spotify_id); });
        renderSavedAlbums();
    }

    async function loadMoreSavedAlbums() {
        if (loading || !hasMore) return;
        loading = true;
        const btn = document.getElementById('load-more-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
        try {
            const data = await api.get(`/spotify/saved-albums?offset=${offset}&limit=50`);
            const newItems = data.items || [];
            newItems.forEach(a => { if (!a.monitored_status) selected.add(a.spotify_id); });
            items = items.concat(newItems);
            offset += newItems.length;
            hasMore = offset < (data.total || 0);
            renderSavedAlbums();
        } catch (e) { toast('Failed: ' + e.message, 'error'); }
        loading = false;
    }

    function renderSavedAlbums() {
        const visible = applyFilter(items);
        const content = document.getElementById('import-content');
        if (!content) return;

        content.innerHTML = `
        <div style="font-size:.8rem;color:var(--text-dim);padding:8px 24px 4px">
            ${total} albums · ${selected.size} selected
        </div>
        <div class="card-grid" style="padding:12px 24px">
            ${visible.map(buildAlbumCard).join('')}
        </div>
        ${hasMore ? `<div style="text-align:center;padding:16px">
            <button class="btn" id="load-more-btn">Load More (${total - offset} remaining)</button>
        </div>` : ''}`;

        document.querySelectorAll('.import-album-cb').forEach(cb => {
            cb.addEventListener('change', e => {
                e.stopPropagation();
                const id = e.target.dataset.id;
                const card = e.target.closest('.arr-card');
                if (e.target.checked) { selected.add(id); card?.classList.add('selected'); }
                else { selected.delete(id); card?.classList.remove('selected'); }
                updateActionBar();
            });
        });
        document.getElementById('load-more-btn')?.addEventListener('click', loadMoreSavedAlbums);
        updateActionBar();
        updateSubtitle();
    }

    function buildAlbumCard(a) {
        const isSelected = selected.has(a.spotify_id);
        const year = a.release_date ? a.release_date.slice(0, 4) : '';
        const status = buildStatusBadge(a.monitored_status);
        return `
        <div class="arr-card ${isSelected ? 'selected' : ''}">
            <input type="checkbox" class="import-album-cb card-checkbox" data-id="${esc(a.spotify_id)}" ${isSelected ? 'checked' : ''}>
            <div class="card-poster">
                ${a.image_url
                    ? `<img src="${esc(a.image_url)}" loading="lazy">`
                    : `<div class="card-poster-placeholder"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" width="48" height="48"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg></div>`}
            </div>
            <div class="card-overlay">
                <div class="card-title">${esc(a.name)}</div>
                <div class="card-subtitle">${esc(a.artist_name)} ${year ? `· ${year}` : ''}</div>
            </div>
            <div class="card-body" style="padding:6px 8px;display:flex;align-items:center;justify-content:space-between">
                <span style="font-size:.75rem;color:var(--text-muted)">${a.track_count} tracks</span>
                ${status}
            </div>
        </div>`;
    }

    // ── Followed Artists ──────────────────────────────────────────────
    async function loadFollowedArtists() {
        const data = await api.get(`/spotify/followed-artists?limit=50`);
        items  = data.items || [];
        total  = data.total || items.length;
        nextCursor = data.next_cursor || null;
        hasMore = !!nextCursor;

        items.forEach(a => { if (!a.monitored_status) selected.add(a.spotify_id); });
        renderFollowedArtists();
    }

    async function loadMoreFollowedArtists() {
        if (loading || !hasMore || !nextCursor) return;
        loading = true;
        const btn = document.getElementById('load-more-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
        try {
            const data = await api.get(`/spotify/followed-artists?limit=50&after=${nextCursor}`);
            const newItems = data.items || [];
            newItems.forEach(a => { if (!a.monitored_status) selected.add(a.spotify_id); });
            items = items.concat(newItems);
            nextCursor = data.next_cursor || null;
            hasMore = !!nextCursor;
            renderFollowedArtists();
        } catch (e) { toast('Failed: ' + e.message, 'error'); }
        loading = false;
    }

    function renderFollowedArtists() {
        const visible = applyFilter(items);
        const content = document.getElementById('import-content');
        if (!content) return;

        content.innerHTML = `
        <div style="font-size:.8rem;color:var(--text-dim);padding:8px 24px 4px">
            ${items.length}${hasMore ? '+' : ''} followed artists · ${selected.size} selected
        </div>
        <div class="card-grid card-grid-lg" style="padding:12px 24px">
            ${visible.map(buildArtistCard).join('')}
        </div>
        ${hasMore ? `<div style="text-align:center;padding:16px">
            <button class="btn" id="load-more-btn">Load More</button>
        </div>` : ''}`;

        document.querySelectorAll('.import-artist-cb').forEach(cb => {
            cb.addEventListener('change', e => {
                e.stopPropagation();
                const id = e.target.dataset.id;
                const card = e.target.closest('.arr-card');
                if (e.target.checked) { selected.add(id); card?.classList.add('selected'); }
                else { selected.delete(id); card?.classList.remove('selected'); }
                updateActionBar();
            });
        });
        document.getElementById('load-more-btn')?.addEventListener('click', loadMoreFollowedArtists);
        updateActionBar();
        updateSubtitle();
    }

    function buildArtistCard(a) {
        const isSelected = selected.has(a.spotify_id);
        const status = buildStatusBadge(a.monitored_status);
        return `
        <div class="arr-card ${isSelected ? 'selected' : ''}">
            <input type="checkbox" class="import-artist-cb card-checkbox" data-id="${esc(a.spotify_id)}" ${isSelected ? 'checked' : ''}>
            <div class="card-poster">
                ${a.image_url
                    ? `<img src="${esc(a.image_url)}" loading="lazy">`
                    : `<div class="card-poster-placeholder"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" width="48" height="48"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg></div>`}
            </div>
            <div class="card-overlay">
                <div class="card-title">${esc(a.name)}</div>
                <div class="card-subtitle">${(a.genres || []).slice(0,2).join(', ') || 'Artist'}</div>
            </div>
            <div class="card-body" style="padding:6px 8px;display:flex;align-items:center;justify-content:space-between">
                <span style="font-size:.75rem;color:var(--text-muted)">${(a.followers||0).toLocaleString()} followers</span>
                ${status}
            </div>
        </div>`;
    }

    // ── Playlists ─────────────────────────────────────────────────────
    async function loadPlaylists() {
        const data = await api.get('/spotify/playlists');
        items = data.items || [];
        renderPlaylists();
    }

    function renderPlaylists() {
        const content = document.getElementById('import-content');
        if (!content) return;

        if (items.length === 0) {
            content.innerHTML = `<div class="empty-state" style="padding-top:40px">
                <div class="empty-state-title">No Playlists Found</div>
            </div>`;
            updateSubtitle();
            return;
        }

        content.innerHTML = `
        <div style="padding:8px 24px 4px;font-size:.8rem;color:var(--text-dim)">${items.length} playlists · ${selected.size} selected</div>
        <table class="arr-table" style="width:100%">
            <thead><tr>
                <th style="width:36px"><input type="checkbox" id="playlist-select-all" style="accent-color:var(--accent)"></th>
                <th></th><th>Name</th><th>Tracks</th><th>Owner</th>
            </tr></thead>
            <tbody>${items.map(pl => `
                <tr class="arr-table-row" style="cursor:pointer" data-playlist-id="${esc(pl.id)}" data-playlist-name="${esc(pl.name)}">
                    <td><input type="checkbox" class="playlist-cb" data-id="${esc(pl.id)}" data-name="${esc(pl.name)}" ${selected.has(pl.id) ? 'checked' : ''} style="accent-color:var(--accent)"></td>
                    <td style="width:44px;padding:6px">
                        ${(pl.images||[])[0]?.url
                            ? `<img src="${esc(pl.images[0].url)}" style="width:36px;height:36px;object-fit:cover;border-radius:2px">`
                            : `<div style="width:36px;height:36px;background:var(--bg-raised);border-radius:2px"></div>`}
                    </td>
                    <td><strong>${esc(pl.name)}</strong></td>
                    <td style="color:var(--text-dim)">${pl.tracks?.total || 0}</td>
                    <td style="color:var(--text-muted)">${esc(pl.owner?.display_name || '')}</td>
                </tr>`).join('')}
            </tbody>
        </table>`;

        // Select-all header checkbox
        document.getElementById('playlist-select-all')?.addEventListener('change', e => {
            const checked = e.target.checked;
            items.forEach(pl => { if (checked) selected.add(pl.id); else selected.delete(pl.id); });
            renderPlaylists();
            updateActionBar();
        });

        // Per-row checkbox events
        document.querySelectorAll('.playlist-cb').forEach(cb => {
            cb.addEventListener('change', e => {
                e.stopPropagation();
                const id = e.target.dataset.id;
                if (e.target.checked) selected.add(id); else selected.delete(id);
                updateActionBar();
                updateSubtitle();
            });
        });

        // Row click → view tracks (but not if clicking checkbox)
        content.querySelectorAll('[data-playlist-id]').forEach(row => {
            row.addEventListener('click', e => {
                if (e.target.type === 'checkbox') return;
                activePlaylistId   = row.dataset.playlistId;
                activePlaylistName = row.dataset.playlistName;
                loadPlaylistTracks(activePlaylistId);
            });
        });

        updateActionBar();
        updateSubtitle();
    }

    async function loadPlaylistTracks(playlistId) {
        // Reset filter when entering a playlist
        filterMode = 'all';
        document.querySelectorAll('#import-filter-btns .filter-btn').forEach(b =>
            b.classList.toggle('active', b.dataset.filter === 'all')
        );

        const content = document.getElementById('import-content');
        content.innerHTML = `
        <div id="pl-header" style="padding:8px 24px;display:flex;align-items:center;gap:8px">
            <button class="btn btn-sm" id="back-to-playlists">← Back</button>
            <span style="font-weight:600">${esc(activePlaylistName)}</span>
        </div>
        <div id="pl-track-list">${buildLoadingState()}</div>`;

        document.getElementById('back-to-playlists')?.addEventListener('click', () => {
            items = []; selected = new Set(); activePlaylistId = null;
            updateActionBar();
            loadPlaylists();
        });

        try {
            const data = await api.get(`/spotify/playlists/${playlistId}/tracks?offset=0&limit=100`);
            items = (data.items || []).map(item => {
                // item IS the track object; item.track is a boolean flag from Spotify (not a nested object)
                return {
                    spotify_id:       item.id || item.spotify_id,
                    name:             item.name || item.title || '',
                    artist_name:      item.artist || (item.artists?.[0]?.name) || '',
                    album_name:       item.album?.name || '',
                    image_url:        item.album?.images?.[0]?.url || null,
                    album_image:      item.album?.images?.[0]?.url || null,
                    duration_ms:      item.duration_ms,
                    monitored_status: item.local_status === 'local' ? 'have' : (item.local_status || null),
                };
            }).filter(t => t.spotify_id);

            items.forEach(t => { if (!t.monitored_status) selected.add(t.spotify_id); });
            renderPlaylistTrackTable();
        } catch (e) {
            const list = document.getElementById('pl-track-list');
            if (list) list.innerHTML = `<div style="padding:16px;color:var(--red)">Failed: ${esc(e.message)}</div>`;
            toast('Failed to load playlist: ' + e.message, 'error');
        }
    }

    function renderPlaylistTrackTable() {
        const list = document.getElementById('pl-track-list');
        if (!list) return;
        const visible = applyFilter(items);
        list.innerHTML = `
        <div style="font-size:.8rem;color:var(--text-dim);padding:4px 24px 4px">
            ${items.length} tracks · ${selected.size} selected
        </div>
        <table class="arr-table" style="width:100%">
            <thead><tr>
                <th style="width:36px"><input type="checkbox" id="pl-select-all" style="accent-color:var(--accent)"></th>
                <th></th><th>Title</th><th>Artist</th><th>Album</th>
                <th style="width:70px;text-align:right">Duration</th>
                <th style="width:100px">Status</th>
            </tr></thead>
            <tbody>${visible.map(buildTrackRow).join('')}</tbody>
        </table>`;

        list.querySelector('#pl-select-all')?.addEventListener('change', e => {
            visible.forEach(t => { if (e.target.checked) selected.add(t.spotify_id); else selected.delete(t.spotify_id); });
            renderPlaylistTrackTable();
            updateActionBar();
        });
        bindTrackRowEvents();
        updateActionBar();
        updateSubtitle();
    }

    // ── Filter ────────────────────────────────────────────────────────
    function applyFilter(list) {
        if (filterMode === 'not-local') {
            return list.filter(i => i.monitored_status !== 'have');
        }
        if (filterMode === 'not-monitored') {
            return list.filter(i => !i.monitored_status);
        }
        return list;
    }

    // ── Import action ─────────────────────────────────────────────────
    async function doImport() {
        if (selected.size === 0) return;

        const btn = document.getElementById('import-confirm-btn');
        btn.disabled = true; btn.textContent = 'Importing…';

        try {
            if (activeSource === 'liked' || (activeSource === 'playlists' && activePlaylistId)) {
                const tracks = items.filter(t => selected.has(t.spotify_id));
                const result = await api.post('/import/tracks', { tracks });
                toast(`Imported ${result.added} track${result.added !== 1 ? 's' : ''}${result.already_monitored > 0 ? ` · ${result.already_monitored} already monitored` : ''}`, 'success');
                // Refresh items to show updated monitored_status
                selected = new Set();
                loadSource();

            } else if (activeSource === 'albums') {
                const albums = items.filter(a => selected.has(a.spotify_id));
                const result = await api.post('/import/albums', { albums });
                toast(`Imported ${result.added} album${result.added !== 1 ? 's' : ''}${result.already_monitored > 0 ? ` · ${result.already_monitored} already monitored` : ''}`, 'success');
                selected = new Set();
                loadSource();

            } else if (activeSource === 'artists') {
                const artists = items.filter(a => selected.has(a.spotify_id));
                const result = await api.post('/import/artists', { artists });
                toast(`Added ${result.added} artist${result.added !== 1 ? 's' : ''}${result.already_monitored > 0 ? ` · ${result.already_monitored} already monitored` : ''}`, 'success');

                // Kick off discography refresh for newly added artists in background
                if (result.artist_ids?.length > 0) {
                    result.artist_ids.slice(0, result.added).forEach(id => {
                        api.post(`/artists/${id}/refresh`).catch(() => {});
                    });
                }
                selected = new Set();
                loadSource();

            } else if (activeSource === 'playlists' && !activePlaylistId) {
                // Multi-playlist import: fetch tracks from each selected playlist
                const playlistIds = [...selected];
                btn.textContent = `Fetching tracks from ${playlistIds.length} playlist${playlistIds.length !== 1 ? 's' : ''}…`;

                const allTracks = [];
                for (const playlistId of playlistIds) {
                    try {
                        const data = await api.get(`/spotify/playlists/${playlistId}/tracks?offset=0&limit=200`);
                        const tracks = (data.items || []).map(item => {
                            // item IS the track object; item.track is a boolean flag, not a nested object
                            return {
                                spotify_id:       item.id || item.spotify_id,
                                name:             item.name || item.title || '',
                                artist_name:      item.artist || (item.artists?.[0]?.name) || '',
                                artist_spotify_id:item.artists?.[0]?.id || '',
                                album_name:       item.album?.name || '',
                                album_spotify_id: item.album?.id || '',
                                image_url:        item.album?.images?.[0]?.url || null,
                                album_image:      item.album?.images?.[0]?.url || null,
                                duration_ms:      item.duration_ms,
                            };
                        }).filter(t => t.spotify_id);
                        allTracks.push(...tracks);
                    } catch (e) {
                        toast(`Failed to fetch playlist ${playlistId}: ${e.message}`, 'error');
                    }
                }

                // Deduplicate by spotify_id
                const seen = new Set();
                const uniqueTracks = allTracks.filter(t => {
                    if (seen.has(t.spotify_id)) return false;
                    seen.add(t.spotify_id);
                    return true;
                });

                btn.textContent = 'Importing…';
                const result = await api.post('/import/tracks', { tracks: uniqueTracks });
                toast(`Imported ${result.added} track${result.added !== 1 ? 's' : ''} from ${playlistIds.length} playlist${playlistIds.length !== 1 ? 's' : ''}${result.already_monitored > 0 ? ` · ${result.already_monitored} already monitored` : ''}`, 'success');
                selected = new Set();
                loadSource();
            }
        } catch (e) {
            toast('Import failed: ' + e.message, 'error');
        }

        btn.disabled = false;
        btn.textContent = activeSource === 'playlists' && !activePlaylistId ? 'Import Selected Playlists' : 'Import Selected';
        updateActionBar();
    }

    // ── UI helpers ────────────────────────────────────────────────────
    function buildStatusBadge(status) {
        if (status === 'have')        return `<span class="status-badge have" style="font-size:.7rem">✓ Local</span>`;
        if (status === 'wanted')      return `<span class="status-badge missing" style="font-size:.7rem">Wanted</span>`;
        if (status === 'monitored')   return `<span class="status-badge monitored" style="font-size:.7rem">Monitored</span>`;
        if (status === 'downloading') return `<span class="status-badge downloading" style="font-size:.7rem">⬇</span>`;
        return '';
    }

    function buildLoadingState() {
        return `<div style="padding:24px">` +
            Array.from({length:8}, () => `
            <div style="display:flex;gap:12px;padding:8px 0;border-top:1px solid var(--border)">
                <div class="skeleton" style="width:36px;height:36px;border-radius:2px;flex-shrink:0"></div>
                <div style="flex:1">
                    <div class="skeleton" style="height:12px;width:60%;border-radius:3px;margin-bottom:6px"></div>
                    <div class="skeleton" style="height:10px;width:40%;border-radius:3px"></div>
                </div>
            </div>`).join('') + `</div>`;
    }

    function updateActionBar() {
        const bar   = document.getElementById('import-action-bar');
        const label = document.getElementById('import-action-label');
        const btn   = document.getElementById('import-confirm-btn');
        const n = selected.size;
        if (bar) bar.hidden = n === 0;
        if (label) {
            const noun = activeSource === 'artists' ? 'artist'
                       : activeSource === 'albums' ? 'album'
                       : activeSource === 'playlists' && !activePlaylistId ? 'playlist'
                       : 'track';
            label.textContent = `${n} ${noun}${n !== 1 ? 's' : ''} selected`;
        }
        if (btn) {
            btn.textContent = activeSource === 'playlists' && !activePlaylistId
                ? 'Import Selected Playlists'
                : 'Import Selected';
        }
    }

    function reRenderCurrent() {
        if (activePlaylistId) renderPlaylistTrackTable();
        else if (activeSource === 'liked') renderLikedSongs();
        else if (activeSource === 'albums') renderSavedAlbums();
        else if (activeSource === 'artists') renderFollowedArtists();
        else if (activeSource === 'playlists') renderPlaylists();
    }

    // ── Shell event bindings ──────────────────────────────────────────
    function bindShellEvents() {
        document.querySelectorAll('#import-source-tabs .section-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                activeSource = btn.dataset.source;
                document.querySelectorAll('#import-source-tabs .section-tab').forEach(b =>
                    b.classList.toggle('active', b.dataset.source === activeSource)
                );
                selected = new Set();
                loadSource();
            });
        });

        document.querySelectorAll('#import-filter-btns .filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                filterMode = btn.dataset.filter;
                document.querySelectorAll('#import-filter-btns .filter-btn').forEach(b =>
                    b.classList.toggle('active', b.dataset.filter === filterMode)
                );
                // Re-render current source with new filter
                reRenderCurrent();
            });
        });

        document.getElementById('import-confirm-btn')?.addEventListener('click', doImport);
    }

    // ── SVG icons ─────────────────────────────────────────────────────
    function heartIcon() { return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>`; }
    function albumIcon()  { return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>`; }
    function artistIcon() { return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>`; }
    function playlistIcon(){ return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>`; }

    // Public reload for retry button
    function reload() { loadSource(); }

    return { load, unload, reload };
})();
