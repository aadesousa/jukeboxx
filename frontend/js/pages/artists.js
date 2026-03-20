// ─── Artists Page — Phase 3 ────────────────────────────────────────
const ArtistsPage = (() => {
    const root = () => document.getElementById('page-root');

    // State
    let allArtists  = [];
    let filtered    = [];
    let activeFilter = 'all';   // all | monitored | missing
    let activeSort   = 'name';  // name | added | missing
    let searchQuery  = '';
    let selectedIds  = new Set();
    let qualityProfiles = [];

    // ── Load ────────────────────────────────────────────────────────
    async function load(params) {
        root().innerHTML = buildShell();
        bindShellEvents();
        await Promise.all([fetchArtists(), fetchQualityProfiles()]);
    }

    function unload() {
        allArtists = []; filtered = []; selectedIds = new Set();
        activeFilter = 'all'; activeSort = 'name'; searchQuery = '';
    }

    function onSearch(q) {
        searchQuery = q.toLowerCase();
        applyFilter();
    }

    // ── Shell HTML ──────────────────────────────────────────────────
    function buildShell() {
        return `
        <div class="page-header">
            <div class="page-header-left">
                <h1 class="page-title">Artists</h1>
                <div class="page-subtitle" id="artists-count"></div>
            </div>
            <div class="page-header-right">
                <button class="btn btn-primary" id="add-artist-btn">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                    </svg>
                    Add Artist
                </button>
            </div>
        </div>

        <div class="filter-bar" id="artists-filter-bar">
            <div class="filter-group">
                <button class="filter-btn active" data-filter="all">All</button>
                <button class="filter-btn" data-filter="monitored">Monitored</button>
                <button class="filter-btn" data-filter="missing">Missing</button>
            </div>
            <div class="filter-group">
                <span style="font-size:.75rem;color:var(--text-muted);align-self:center;margin-right:4px">Sort</span>
                <button class="filter-btn active" data-sort="name">Name</button>
                <button class="filter-btn" data-sort="added">Date Added</button>
                <button class="filter-btn" data-sort="missing">Missing</button>
            </div>
        </div>

        <div id="artists-grid-wrap">
            <div class="card-grid card-grid-lg" id="artists-grid">
                ${buildSkeletons(12)}
            </div>
        </div>

        <div class="mass-edit-bar" id="mass-edit-bar" hidden>
            <span id="mass-edit-count">0 selected</span>
            <div style="display:flex;gap:6px">
                <button class="btn btn-sm" id="mass-monitor-btn">Set Monitored</button>
                <button class="btn btn-sm" id="mass-unmonitor-btn">Set Unmonitored</button>
                <button class="btn btn-danger btn-sm" id="mass-delete-btn">Delete</button>
            </div>
            <button class="btn btn-sm" id="mass-clear-btn">Clear</button>
        </div>`;
    }

    function buildSkeletons(n) {
        return Array.from({length: n}, () => `
            <div class="arr-card skeleton-card">
                <div class="card-poster"><div class="skeleton" style="width:100%;height:100%"></div></div>
                <div class="card-body" style="padding:8px">
                    <div class="skeleton" style="height:12px;border-radius:3px;margin-bottom:4px"></div>
                    <div class="skeleton" style="height:10px;border-radius:3px;width:60%"></div>
                </div>
            </div>`).join('');
    }

    // ── Data fetch ──────────────────────────────────────────────────
    async function fetchArtists() {
        try {
            allArtists = await api.get('/artists');
            applyFilter();
        } catch (e) {
            document.getElementById('artists-grid').innerHTML = `
                <div class="empty-state" style="grid-column:1/-1">
                    <div class="empty-state-title">Failed to load artists</div>
                    <div class="empty-state-body">${esc(e.message)}</div>
                </div>`;
        }
    }

    async function fetchQualityProfiles() {
        try { qualityProfiles = await api.get('/quality-profiles'); } catch {}
    }

    // ── Filter / Sort / Render ──────────────────────────────────────
    function applyFilter() {
        filtered = allArtists.filter(a => {
            if (activeFilter === 'monitored' && !a.monitored) return false;
            if (activeFilter === 'missing' && !a.missing_count) return false;
            if (searchQuery && !a.name.toLowerCase().includes(searchQuery)) return false;
            return true;
        });

        // Sort
        if (activeSort === 'name') {
            filtered.sort((a, b) => a.name.localeCompare(b.name));
        } else if (activeSort === 'added') {
            filtered.sort((a, b) => new Date(b.added_at) - new Date(a.added_at));
        } else if (activeSort === 'missing') {
            filtered.sort((a, b) => (b.missing_count || 0) - (a.missing_count || 0) || a.name.localeCompare(b.name));
        }

        renderGrid();
        updateCount();
    }

    function renderGrid() {
        const grid = document.getElementById('artists-grid');
        if (!grid) return;
        if (filtered.length === 0) {
            grid.innerHTML = buildEmptyState();
            return;
        }
        grid.innerHTML = filtered.map(a => buildCard(a)).join('');
        bindCardEvents();
        updateMassEditBar();
    }

    function buildCard(a) {
        const img = a.image_url
            ? `<img src="${esc(a.image_url)}" alt="${esc(a.name)}" loading="lazy">`
            : `<div class="card-poster-placeholder"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" width="48" height="48"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>`;

        const missing = a.missing_count || 0;
        const missingBadge = missing > 0
            ? `<span class="card-missing-badge">${missing} missing</span>`
            : (a.track_count > 0 ? `<span class="card-missing-badge zero">✓</span>` : '');

        const monitored = a.monitored;
        const monitoredIcon = monitored
            ? `<svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/></svg>`
            : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12"><circle cx="12" cy="12" r="10"/></svg>`;

        const isSelected = selectedIds.has(a.id);

        return `
        <div class="arr-card ${isSelected ? 'selected' : ''}" data-id="${a.id}" data-spotify="${esc(a.spotify_id)}">
            <input type="checkbox" class="card-checkbox" ${isSelected ? 'checked' : ''} data-id="${a.id}">
            <div class="card-poster">${img}</div>
            <div class="card-overlay">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:4px">
                    <div class="card-title">${esc(a.name)}</div>
                    ${missingBadge}
                </div>
                <div class="card-subtitle" style="margin-top:4px;display:flex;align-items:center;gap:4px">
                    <span class="monitored-toggle ${monitored ? 'monitored' : 'unmonitored'}" data-id="${a.id}" title="${monitored ? 'Monitored' : 'Unmonitored'}" style="width:16px;height:16px;border-radius:50%;background:rgba(0,0,0,.5);border:1px solid rgba(255,255,255,.3);display:inline-flex;align-items:center;justify-content:center;cursor:pointer;color:${monitored ? 'var(--accent)' : 'rgba(255,255,255,.4)'}">${monitoredIcon}</span>
                    <span>${a.album_count || 0} album${a.album_count !== 1 ? 's' : ''}</span>
                </div>
            </div>
        </div>`;
    }

    function buildEmptyState() {
        if (allArtists.length === 0) {
            return `<div class="empty-state" style="grid-column:1/-1;padding-top:40px">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" width="64" height="64">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                    <circle cx="9" cy="7" r="4"/>
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                </svg>
                <div class="empty-state-title">No Artists Yet</div>
                <div class="empty-state-body">Add artists to monitor their discographies, or import from your Spotify library.</div>
                <div style="display:flex;gap:8px;margin-top:8px;justify-content:center">
                    <button class="btn btn-primary" id="es-add-btn">Add Artist</button>
                    <a class="btn" href="#/import">Import from Spotify</a>
                </div>
            </div>`;
        }
        return `<div class="empty-state" style="grid-column:1/-1">
            <div class="empty-state-title">No matches</div>
            <div class="empty-state-body">Try a different filter or search term.</div>
        </div>`;
    }

    function updateCount() {
        const el = document.getElementById('artists-count');
        if (el) {
            const total = allArtists.length;
            const showing = filtered.length;
            el.textContent = total === showing
                ? `${total} artist${total !== 1 ? 's' : ''}`
                : `${showing} of ${total} artists`;
        }
    }

    // ── Card Events ─────────────────────────────────────────────────
    function bindCardEvents() {
        const grid = document.getElementById('artists-grid');
        if (!grid) return;

        // Empty state buttons
        grid.querySelector('#es-add-btn')?.addEventListener('click', openAddModal);

        // Card clicks → navigate to artist detail
        grid.querySelectorAll('.arr-card').forEach(card => {
            card.addEventListener('click', e => {
                if (e.target.closest('.card-checkbox') || e.target.closest('.monitored-toggle')) return;
                const id = card.dataset.id;
                navigate(`/artists/${id}`);
            });
        });

        // Checkboxes → mass edit
        grid.querySelectorAll('.card-checkbox').forEach(cb => {
            cb.addEventListener('change', e => {
                const id = parseInt(e.target.dataset.id);
                if (e.target.checked) selectedIds.add(id);
                else selectedIds.delete(id);
                e.target.closest('.arr-card').classList.toggle('selected', e.target.checked);
                updateMassEditBar();
            });
            // Prevent card click propagation
            cb.addEventListener('click', e => e.stopPropagation());
        });

        // Monitored toggle
        grid.querySelectorAll('.monitored-toggle').forEach(btn => {
            btn.addEventListener('click', async e => {
                e.stopPropagation();
                const id = parseInt(btn.dataset.id);
                const artist = allArtists.find(a => a.id === id);
                if (!artist) return;
                const newVal = !artist.monitored;
                try {
                    await api.patch(`/artists/${id}`, { monitored: newVal ? 1 : 0 });
                    artist.monitored = newVal;
                    applyFilter();
                } catch (err) {
                    toast('Failed to update: ' + err.message, 'error');
                }
            });
        });
    }

    // ── Mass Edit ───────────────────────────────────────────────────
    function updateMassEditBar() {
        const bar = document.getElementById('mass-edit-bar');
        if (!bar) return;
        const count = selectedIds.size;
        bar.hidden = count === 0;
        const el = document.getElementById('mass-edit-count');
        if (el) el.textContent = `${count} selected`;
    }

    function bindMassEditEvents() {
        document.getElementById('mass-monitor-btn')?.addEventListener('click', () => bulkSetMonitored(true));
        document.getElementById('mass-unmonitor-btn')?.addEventListener('click', () => bulkSetMonitored(false));
        document.getElementById('mass-delete-btn')?.addEventListener('click', bulkDelete);
        document.getElementById('mass-clear-btn')?.addEventListener('click', () => {
            selectedIds.clear();
            document.querySelectorAll('.card-checkbox').forEach(cb => { cb.checked = false; });
            document.querySelectorAll('.arr-card.selected').forEach(c => c.classList.remove('selected'));
            updateMassEditBar();
        });
    }

    async function bulkSetMonitored(monitored) {
        const ids = [...selectedIds];
        let ok = 0;
        for (const id of ids) {
            try {
                await api.patch(`/artists/${id}`, { monitored: monitored ? 1 : 0 });
                const a = allArtists.find(x => x.id === id);
                if (a) a.monitored = monitored;
                ok++;
            } catch {}
        }
        toast(`Updated ${ok} artist${ok !== 1 ? 's' : ''}`, 'success');
        selectedIds.clear();
        applyFilter();
    }

    async function bulkDelete() {
        const ids = [...selectedIds];
        if (!confirm(`Delete ${ids.length} artist${ids.length !== 1 ? 's' : ''}? This will remove all their albums and tracks from monitoring.`)) return;
        let ok = 0;
        for (const id of ids) {
            try {
                await api.del(`/artists/${id}`);
                allArtists = allArtists.filter(a => a.id !== id);
                ok++;
            } catch {}
        }
        toast(`Deleted ${ok} artist${ok !== 1 ? 's' : ''}`, 'success');
        selectedIds.clear();
        applyFilter();
    }

    // ── Shell Event Bindings ────────────────────────────────────────
    function bindShellEvents() {
        // Filter buttons
        document.querySelectorAll('[data-filter]').forEach(btn => {
            btn.addEventListener('click', () => {
                activeFilter = btn.dataset.filter;
                document.querySelectorAll('[data-filter]').forEach(b => b.classList.toggle('active', b.dataset.filter === activeFilter));
                applyFilter();
            });
        });

        // Sort buttons
        document.querySelectorAll('[data-sort]').forEach(btn => {
            btn.addEventListener('click', () => {
                activeSort = btn.dataset.sort;
                document.querySelectorAll('[data-sort]').forEach(b => b.classList.toggle('active', b.dataset.sort === activeSort));
                applyFilter();
            });
        });

        // Add Artist button
        document.getElementById('add-artist-btn')?.addEventListener('click', openAddModal);

        // Mass edit
        bindMassEditEvents();
    }

    // ── Add Artist Modal ────────────────────────────────────────────
    function openAddModal() {
        const existing = document.getElementById('add-artist-modal');
        if (existing) existing.remove();

        const profileOptions = qualityProfiles.map(p =>
            `<option value="${p.id}" ${p.is_default ? 'selected' : ''}>${esc(p.name)}</option>`
        ).join('');

        const modal = document.createElement('div');
        modal.className = 'modal-backdrop';
        modal.id = 'add-artist-modal';
        modal.innerHTML = `
        <div class="modal-box" style="width:560px;max-width:95vw">
            <div class="modal-header">
                <span class="modal-title">Add Artist</span>
                <button class="modal-close" id="modal-close-btn">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
                        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            </div>
            <div class="modal-body">
                <div style="display:flex;gap:8px;margin-bottom:16px">
                    <input class="input" id="artist-search-input" placeholder="Search Spotify for an artist…" autocomplete="off" style="flex:1">
                    <button class="btn" id="artist-search-btn">Search</button>
                </div>
                <div id="artist-search-results" style="max-height:260px;overflow-y:auto"></div>
                <div id="artist-add-options" hidden style="border-top:1px solid var(--border);padding-top:16px;margin-top:16px">
                    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
                        <div class="selected-artist-img" id="selected-artist-img" style="width:56px;height:56px;border-radius:50%;overflow:hidden;background:var(--bg-raised);flex-shrink:0"></div>
                        <div>
                            <div id="selected-artist-name" style="font-weight:600;font-size:1rem"></div>
                            <div id="selected-artist-meta" style="font-size:.8rem;color:var(--text-dim);margin-top:2px"></div>
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-label">Monitor</div>
                        <div class="form-control">
                            <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                                <input type="checkbox" id="opt-monitored" checked style="width:16px;height:16px">
                                <span>Monitor this artist's discography</span>
                            </label>
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-label">New Releases</div>
                        <div class="form-control">
                            <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                                <input type="checkbox" id="opt-monitor-new" checked style="width:16px;height:16px">
                                <span>Auto-add new albums when released</span>
                            </label>
                        </div>
                    </div>
                    ${qualityProfiles.length > 0 ? `
                    <div class="form-row">
                        <div class="form-label">Quality Profile</div>
                        <div class="form-control">
                            <select class="input" id="opt-quality" style="width:auto">${profileOptions}</select>
                        </div>
                    </div>` : ''}
                </div>
            </div>
            <div class="modal-footer" id="modal-footer" hidden>
                <button class="btn" id="modal-cancel-btn">Cancel</button>
                <button class="btn btn-primary" id="modal-confirm-btn">Add Artist</button>
            </div>
        </div>`;

        document.body.appendChild(modal);

        let selectedArtist = null;

        // Close
        modal.querySelector('#modal-close-btn').addEventListener('click', () => modal.remove());
        modal.querySelector('#modal-cancel-btn')?.addEventListener('click', () => modal.remove());
        modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });

        // Search
        const searchInput = modal.querySelector('#artist-search-input');
        const searchBtn   = modal.querySelector('#artist-search-btn');
        const resultsEl   = modal.querySelector('#artist-search-results');

        const doSearch = async () => {
            const q = searchInput.value.trim();
            if (!q) return;
            searchBtn.disabled = true;
            searchBtn.textContent = 'Searching…';
            resultsEl.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:.85rem">Searching Spotify…</div>';
            try {
                const artists = await api.get(`/artists/search?q=${encodeURIComponent(q)}`);
                if (artists.length === 0) {
                    resultsEl.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:.85rem">No artists found.</div>';
                } else {
                    resultsEl.innerHTML = artists.map(a => `
                        <div class="search-result-item" data-spotify="${esc(a.spotify_id)}"
                             style="display:flex;align-items:center;gap:10px;padding:10px;border-radius:var(--radius);cursor:pointer;transition:background var(--transition)">
                            <div style="width:40px;height:40px;border-radius:50%;overflow:hidden;background:var(--bg-raised);flex-shrink:0">
                                ${a.image_url ? `<img src="${esc(a.image_url)}" style="width:100%;height:100%;object-fit:cover">` : ''}
                            </div>
                            <div style="flex:1;min-width:0">
                                <div style="font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(a.name)}</div>
                                <div style="font-size:.75rem;color:var(--text-dim)">${(a.genres || []).slice(0, 2).join(', ') || 'Artist'} · ${(a.followers || 0).toLocaleString()} followers</div>
                            </div>
                            <div class="status-badge" style="flex-shrink:0;font-size:.7rem">${allArtists.some(x => x.spotify_id === a.spotify_id) ? 'Added' : ''}</div>
                        </div>`).join('');

                    resultsEl.querySelectorAll('.search-result-item').forEach((item, i) => {
                        item.addEventListener('mouseenter', () => item.style.background = 'var(--bg-hover)');
                        item.addEventListener('mouseleave', () => item.style.background = '');
                        item.addEventListener('click', () => {
                            selectedArtist = artists[i];
                            resultsEl.querySelectorAll('.search-result-item').forEach(el => el.style.outline = '');
                            item.style.outline = '2px solid var(--accent)';
                            item.style.outlineOffset = '-2px';
                            showSelectedArtist(selectedArtist);
                        });
                    });
                }
            } catch (e) {
                resultsEl.innerHTML = `<div style="padding:12px;color:var(--red);font-size:.85rem">${esc(e.message)}</div>`;
            }
            searchBtn.disabled = false;
            searchBtn.textContent = 'Search';
        };

        searchBtn.addEventListener('click', doSearch);
        searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
        setTimeout(() => searchInput.focus(), 50);

        function showSelectedArtist(a) {
            const optionsEl = modal.querySelector('#artist-add-options');
            const footerEl  = modal.querySelector('#modal-footer');
            const nameEl    = modal.querySelector('#selected-artist-name');
            const metaEl    = modal.querySelector('#selected-artist-meta');
            const imgEl     = modal.querySelector('#selected-artist-img');

            nameEl.textContent = a.name;
            metaEl.textContent = `${(a.genres || []).slice(0, 3).join(', ') || 'Artist'} · ${(a.followers || 0).toLocaleString()} followers`;
            imgEl.innerHTML = a.image_url ? `<img src="${esc(a.image_url)}" style="width:100%;height:100%;object-fit:cover">` : '';
            optionsEl.hidden = false;
            footerEl.hidden = false;
        }

        // Confirm add
        modal.querySelector('#modal-confirm-btn')?.addEventListener('click', async () => {
            if (!selectedArtist) return;
            if (allArtists.some(x => x.spotify_id === selectedArtist.spotify_id)) {
                toast('Artist already added', 'info');
                modal.remove();
                return;
            }
            const btn = modal.querySelector('#modal-confirm-btn');
            btn.disabled = true; btn.textContent = 'Adding…';
            try {
                const quality_profile_id = parseInt(modal.querySelector('#opt-quality')?.value) || null;
                const result = await api.post('/artists', {
                    spotify_id:          selectedArtist.spotify_id,
                    monitored:           modal.querySelector('#opt-monitored').checked,
                    monitor_new_releases:modal.querySelector('#opt-monitor-new').checked,
                    quality_profile_id,
                });
                toast(`Added ${selectedArtist.name}`, 'success');
                modal.remove();
                // Refresh and kick off discography fetch in background
                await fetchArtists();
                // Trigger refresh of discography
                api.post(`/artists/${result.id}/refresh`).catch(() => {});
            } catch (e) {
                toast('Failed to add artist: ' + e.message, 'error');
                btn.disabled = false; btn.textContent = 'Add Artist';
            }
        });
    }

    return { load, unload, onSearch };
})();
