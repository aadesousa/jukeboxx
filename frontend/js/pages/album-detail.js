// ─── Album Detail Page — Phase 4 ──────────────────────────────────
const AlbumDetailPage = (() => {
    const root = () => document.getElementById('page-root');

    let album  = null;
    let tracks = [];

    // ── Load ─────────────────────────────────────────────────────────
    async function load(params) {
        const albumId = params.id;
        if (!albumId) { navigate('/artists'); return; }

        root().innerHTML = buildSkeleton();

        try {
            album = await api.get(`/albums/${albumId}`);
            tracks = album.tracks || [];
            // If no tracks yet, fetch from Spotify
            if (tracks.length === 0 && album.spotify_id) {
                fetchTracksFromSpotify(albumId);
            }
            render();
        } catch (e) {
            root().innerHTML = `<div class="empty-state" style="padding-top:80px">
                <div class="empty-state-title">Album not found</div>
                <div class="empty-state-body">${esc(e.message)}</div>
                <a class="btn btn-primary" style="margin-top:12px" href="#/artists">Back to Artists</a>
            </div>`;
        }
    }

    function unload() { album = null; tracks = []; }

    async function fetchTracksFromSpotify(albumId) {
        try {
            await api.get(`/albums/${albumId}/tracks`);
            // Reload
            album = await api.get(`/albums/${albumId}`);
            tracks = album.tracks || [];
            renderTracklist();
        } catch {}
    }

    // ── Render ────────────────────────────────────────────────────────
    function render() {
        root().innerHTML = `
        ${buildHeader()}
        <div style="padding:0 24px 24px">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
                <h3 style="font-size:.875rem;font-weight:600;color:var(--text-dim);text-transform:uppercase;letter-spacing:.05em">Tracklist</h3>
                <div style="display:flex;gap:8px">
                    <button class="btn btn-sm btn-primary" id="download-all-btn">Download All Missing</button>
                    <button class="btn btn-sm" id="add-track-btn">+ Add Track</button>
                    <button class="btn btn-sm" id="fetch-tracks-btn">Fetch from Spotify</button>
                </div>
            </div>
            <div id="tracklist-wrap"></div>
        </div>`;

        renderTracklist();
        bindEvents();
    }

    function renderTracklist() {
        const wrap = document.getElementById('tracklist-wrap');
        if (!wrap) return;
        if (tracks.length === 0) {
            wrap.innerHTML = `<div class="empty-state" style="padding:32px 0">
                <div class="empty-state-title">No tracks loaded</div>
                <div class="empty-state-body">Click <strong>Fetch from Spotify</strong> to load the tracklist.</div>
            </div>`;
            return;
        }

        const have    = tracks.filter(t => t.status === 'have').length;
        const total   = tracks.length;
        const pct     = total > 0 ? Math.round((have / total) * 100) : 0;

        wrap.innerHTML = `
        <div style="margin-bottom:12px">
            <div style="display:flex;justify-content:space-between;font-size:.8rem;color:var(--text-dim);margin-bottom:4px">
                <span>${have} of ${total} tracks</span>
                <span>${pct}%</span>
            </div>
            <div style="height:4px;background:var(--border);border-radius:2px">
                <div style="height:100%;width:${pct}%;background:var(--accent);border-radius:2px;transition:width .3s"></div>
            </div>
        </div>
        <table class="arr-table" style="width:100%">
            <thead>
                <tr>
                    <th style="width:32px">#</th>
                    <th>Title</th>
                    <th style="width:80px;text-align:right">Duration</th>
                    <th style="width:120px">Status</th>
                    <th style="width:100px;text-align:right">Actions</th>
                </tr>
            </thead>
            <tbody>
                ${tracks.map(buildTrackRow).join('')}
            </tbody>
        </table>`;

        bindTrackEvents();
    }

    function buildTrackRow(t) {
        const status = t.status || 'wanted';
        const statusBadge = {
            have:        `<span class="status-badge have">✓ Local</span>`,
            downloading: `<span class="status-badge downloading">⬇ Downloading</span>`,
            wanted:      `<span class="status-badge missing">○ Wanted</span>`,
            ignored:     `<span class="status-badge ignored">— Ignored</span>`,
        }[status] || `<span class="status-badge">${esc(status)}</span>`;

        const dur = t.duration_ms ? formatDuration(Math.round(t.duration_ms / 1000)) : '—';
        const monitored = t.monitored !== 0;

        return `
        <tr class="arr-table-row" data-track-id="${t.id}">
            <td style="color:var(--text-muted)">${t.track_number || '—'}</td>
            <td>
                <div style="display:flex;align-items:center;gap:8px">
                    <label style="display:flex;align-items:center;gap:4px;cursor:pointer;flex-shrink:0" title="${monitored ? 'Monitored — click to unmonitor' : 'Unmonitored — click to monitor'}">
                        <input type="checkbox" class="track-monitor-cb" data-id="${t.id}" ${monitored ? 'checked' : ''} style="width:14px;height:14px;accent-color:var(--accent)">
                    </label>
                    <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.name)}</span>
                </div>
            </td>
            <td style="text-align:right;color:var(--text-dim)">${dur}</td>
            <td>${statusBadge}</td>
            <td style="text-align:right">
                <div style="display:flex;gap:4px;justify-content:flex-end">
                    ${status !== 'have' ? `<button class="btn btn-sm" data-action="download" data-id="${t.id}" title="Download">⬇</button>` : ''}
                    ${status !== 'ignored' ? `<button class="btn btn-sm" data-action="ignore" data-id="${t.id}" title="Ignore" style="color:var(--text-muted)">✕</button>` : ''}
                </div>
            </td>
        </tr>`;
    }

    // ── Header ────────────────────────────────────────────────────────
    function buildHeader() {
        const a = album;
        const year = a.release_date ? a.release_date.slice(0, 4) : '';
        const statusColors = { have:'var(--green)', partial:'var(--orange)', wanted:'var(--red)', downloading:'var(--accent)', ignored:'var(--text-muted)' };
        const statusColor = statusColors[a.status] || 'var(--text-muted)';
        const artistHref = a.artist_id ? `#/artists/${a.artist_id}` : '#/artists';

        return `
        <div style="padding:24px;display:flex;gap:24px;align-items:flex-start;background:var(--bg-card);border-bottom:1px solid var(--border)">
            <div style="width:160px;height:160px;flex-shrink:0;border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow-lg)">
                ${a.image_url
                    ? `<img src="${esc(a.image_url)}" style="width:100%;height:100%;object-fit:cover">`
                    : `<div style="width:100%;height:100%;background:var(--bg-raised);display:flex;align-items:center;justify-content:center;color:var(--text-muted)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" width="64" height="64"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg></div>`}
            </div>
            <div style="flex:1;min-width:0">
                <div class="breadcrumb" style="margin-bottom:8px">
                    <a class="breadcrumb-item" href="#/artists">Artists</a>
                    <span class="breadcrumb-sep">›</span>
                    <a class="breadcrumb-item" href="${artistHref}">${esc(a.artist_name || 'Artist')}</a>
                    <span class="breadcrumb-sep">›</span>
                    <span class="breadcrumb-item active">${esc(a.name)}</span>
                </div>
                <h1 style="font-size:1.6rem;font-weight:300;margin-bottom:4px">${esc(a.name)}</h1>
                <div style="font-size:.9rem;color:var(--text-dim);margin-bottom:12px">
                    <a href="${artistHref}" style="color:var(--text)">${esc(a.artist_name || '')}</a>
                    ${year ? ` · ${year}` : ''}
                    ${a.album_type ? ` · ${a.album_type.charAt(0).toUpperCase() + a.album_type.slice(1)}` : ''}
                    ${a.label ? ` · ${esc(a.label)}` : ''}
                </div>
                <div style="display:flex;align-items:center;gap:8px">
                    <span style="color:${statusColor};font-size:.85rem">● ${(a.status || 'wanted').charAt(0).toUpperCase() + (a.status || 'wanted').slice(1)}</span>
                    <span style="color:var(--text-muted)">|</span>
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:.85rem">
                        <input type="checkbox" id="album-monitor-cb" ${a.monitored ? 'checked' : ''} style="accent-color:var(--accent)">
                        Monitored
                    </label>
                </div>
            </div>
        </div>`;
    }

    function buildSkeleton() {
        return `<div style="padding:24px;display:flex;gap:24px;background:var(--bg-card);border-bottom:1px solid var(--border)">
            <div class="skeleton" style="width:160px;height:160px;border-radius:var(--radius);flex-shrink:0"></div>
            <div style="flex:1">
                <div class="skeleton" style="height:12px;width:160px;margin-bottom:10px;border-radius:3px"></div>
                <div class="skeleton" style="height:32px;width:280px;margin-bottom:8px;border-radius:3px"></div>
                <div class="skeleton" style="height:12px;width:200px;border-radius:3px"></div>
            </div>
        </div>
        <div style="padding:24px"><div class="skeleton" style="height:200px;border-radius:var(--radius)"></div></div>`;
    }

    // ── Events ────────────────────────────────────────────────────────
    function bindEvents() {
        document.getElementById('album-monitor-cb')?.addEventListener('change', async e => {
            try {
                await api.patch(`/albums/${album.id}`, { monitored: e.target.checked ? 1 : 0 });
                album.monitored = e.target.checked;
                toast(e.target.checked ? 'Album monitored' : 'Album unmonitored', 'success');
            } catch (err) { toast('Failed: ' + err.message, 'error'); e.target.checked = !e.target.checked; }
        });

        document.getElementById('add-track-btn')?.addEventListener('click', () => openAddTrackModal());

        document.getElementById('download-all-btn')?.addEventListener('click', async () => {
            const albumId = album.id;
            const btn = document.getElementById('download-all-btn');
            if (btn) btn.disabled = true;
            if (btn) btn.textContent = 'Queuing…';
            try {
                let r = await api.post(`/albums/${albumId}/command`, { command: 'search-missing' });
                if (r.queued === 0) {
                    await api.post(`/albums/${albumId}/command`, { command: 'mark-wanted' });
                    r = await api.post(`/albums/${albumId}/command`, { command: 'search-missing' });
                }
                toast(r.queued > 0 ? `Queued ${r.queued} track${r.queued !== 1 ? 's' : ''} for download` : 'All tracks already have files or are queued', r.queued > 0 ? 'success' : 'info');
                album = await api.get(`/albums/${albumId}`);
                tracks = album.tracks || [];
                renderTracklist();
            } catch (e) {
                toast('Failed to queue download', 'error');
            } finally {
                if (btn) { btn.disabled = false; btn.textContent = 'Download All Missing'; }
            }
        });

        document.getElementById('fetch-tracks-btn')?.addEventListener('click', async () => {
            const btn = document.getElementById('fetch-tracks-btn');
            btn.disabled = true; btn.textContent = 'Fetching…';
            try {
                const result = await api.get(`/albums/${album.id}/tracks`);
                toast(`Loaded ${result.total} tracks`, 'success');
                album = await api.get(`/albums/${album.id}`);
                tracks = album.tracks || [];
                renderTracklist();
            } catch (e) { toast('Failed: ' + e.message, 'error'); }
            btn.disabled = false; btn.textContent = 'Fetch from Spotify';
        });
    }

    function bindTrackEvents() {
        // Monitor toggles
        document.querySelectorAll('.track-monitor-cb').forEach(cb => {
            cb.addEventListener('change', async e => {
                const id = parseInt(e.target.dataset.id);
                try {
                    await api.patch(`/monitored-tracks/${id}`, { monitored: e.target.checked ? 1 : 0 });
                    const t = tracks.find(x => x.id === id);
                    if (t) t.monitored = e.target.checked ? 1 : 0;
                } catch (err) {
                    toast('Failed: ' + err.message, 'error');
                    e.target.checked = !e.target.checked;
                }
            });
        });

        // Action buttons
        document.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', async e => {
                const id   = parseInt(btn.dataset.id);
                const action = btn.dataset.action;
                if (action === 'download') {
                    const trackId = btn.closest('[data-id]')?.dataset.id || btn.dataset.id;
                    if (!trackId) return;
                    try {
                        await api.patch(`/monitored-tracks/${trackId}`, { status: 'wanted' });
                        await api.post(`/albums/${album.id}/command`, { command: 'search-missing' });
                        toast('Track queued for download', 'success');
                        album = await api.get(`/albums/${album.id}`);
                        tracks = album.tracks || [];
                        renderTracklist();
                    } catch (err) {
                        toast('Failed to queue track', 'error');
                    }
                } else if (action === 'ignore') {
                    try {
                        await api.patch(`/monitored-tracks/${id}`, { status: 'ignored', monitored: 0 });
                        const t = tracks.find(x => x.id === id);
                        if (t) { t.status = 'ignored'; t.monitored = 0; }
                        renderTracklist();
                    } catch (err) { toast('Failed: ' + err.message, 'error'); }
                }
            });
        });
    }

    // ── Add Track Manually ────────────────────────────────────────────
    function openAddTrackModal() {
        const existing = document.getElementById('add-track-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.className = 'modal-backdrop';
        modal.id = 'add-track-modal';
        modal.innerHTML = `
        <div class="modal-box" style="width:440px;max-width:95vw">
            <div class="modal-header">
                <span class="modal-title">Add Track</span>
                <button class="modal-close" id="modal-close-btn">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
                        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            </div>
            <div class="modal-body">
                <div class="form-row">
                    <div class="form-label">Track Name <span style="color:var(--red)">*</span></div>
                    <div class="form-control">
                        <input class="input" id="track-name-input" placeholder="e.g. Come Together" autocomplete="off" style="width:100%">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Track #</div>
                    <div class="form-control">
                        <input class="input" id="track-number-input" type="number" min="1" placeholder="optional" style="width:100px">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Duration</div>
                    <div class="form-control" style="display:flex;align-items:center;gap:8px">
                        <input class="input" id="track-duration-input" type="number" min="0" placeholder="seconds (optional)" style="width:140px">
                        <span style="font-size:.8rem;color:var(--text-dim)">seconds</span>
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn" id="modal-cancel-btn">Cancel</button>
                <button class="btn btn-primary" id="modal-confirm-btn">Add Track</button>
            </div>
        </div>`;

        document.body.appendChild(modal);
        setTimeout(() => modal.querySelector('#track-name-input')?.focus(), 50);

        modal.querySelector('#modal-close-btn').addEventListener('click', () => modal.remove());
        modal.querySelector('#modal-cancel-btn').addEventListener('click', () => modal.remove());
        modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });

        modal.querySelector('#modal-confirm-btn').addEventListener('click', async () => {
            const name = modal.querySelector('#track-name-input').value.trim();
            if (!name) { toast('Track name is required', 'error'); return; }

            const btn = modal.querySelector('#modal-confirm-btn');
            btn.disabled = true; btn.textContent = 'Adding…';
            try {
                const secs = parseInt(modal.querySelector('#track-duration-input').value) || null;
                const trackNum = parseInt(modal.querySelector('#track-number-input').value) || null;
                await api.post('/monitored-tracks/manual', {
                    name,
                    album_id: album.id,
                    artist_name: album.artist_name || '',
                    album_name: album.name || '',
                    track_number: trackNum,
                    duration_ms: secs ? secs * 1000 : null,
                });
                toast(`Added ${name}`, 'success');
                modal.remove();
                album = await api.get(`/albums/${album.id}`);
                tracks = album.tracks || [];
                renderTracklist();
            } catch (e) {
                toast('Failed to add track: ' + e.message, 'error');
                btn.disabled = false; btn.textContent = 'Add Track';
            }
        });

        modal.querySelector('#track-name-input').addEventListener('keydown', e => {
            if (e.key === 'Enter') modal.querySelector('#modal-confirm-btn').click();
        });
    }

    return { load, unload };
})();
