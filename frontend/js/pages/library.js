// ─── Library Page ─────────────────────────────────────────────────
const LibraryPage = (() => {
    const root = () => document.getElementById('page-root');

    let activeTab = 'overview';
    let browseOffset = 0;
    let browseLetter = '';
    let browseQuery = '';
    let browseTotal = 0;
    let browseItems = [];
    let expandedArtist = null;
    let expandedAlbums = null;
    let expandedAlbum = null;
    let expandedTracks = null;
    let unmatchedOffset = 0;
    let unmatchedTotal = 0;
    let unmatchedQuery = '';
    let stats = null;
    let matchPopoverTrackId = null;
    let browseDebounce = null;
    let unmatchedDebounce = null;

    // ── Load ─────────────────────────────────────────────────────────
    async function load(params) {
        browseOffset = 0; browseLetter = ''; browseQuery = ''; browseTotal = 0;
        browseItems = []; expandedArtist = null; expandedAlbums = null;
        expandedAlbum = null; expandedTracks = null;
        unmatchedOffset = 0; unmatchedTotal = 0; unmatchedQuery = '';
        stats = null; matchPopoverTrackId = null;
        activeTab = 'overview';

        root().innerHTML = buildShell();
        bindShellEvents();
        await loadOverview();
    }

    function unload() {
        browseItems = []; stats = null;
        const popover = document.getElementById('match-popover');
        if (popover) popover.remove();
    }

    // ── Shell ─────────────────────────────────────────────────────────
    function buildShell() {
        return `
        <div class="page-header">
            <div class="page-header-left">
                <h1 class="page-title">Library</h1>
                <div class="page-subtitle">Your local music collection</div>
            </div>
        </div>

        <div class="section-tabs" id="library-tabs" style="margin:0 24px 0">
            <button class="section-tab ${activeTab === 'overview' ? 'active' : ''}" data-tab="overview">Overview</button>
            <button class="section-tab ${activeTab === 'browse' ? 'active' : ''}" data-tab="browse">Browse</button>
            <button class="section-tab ${activeTab === 'unmatched' ? 'active' : ''}" data-tab="unmatched">
                Unmapped Files <span class="tab-count" id="unmatched-tab-count"></span>
            </button>
        </div>

        <div id="library-content" style="flex:1;overflow-y:auto;padding-bottom:60px">
            ${buildSkeleton()}
        </div>`;
    }

    function buildSkeleton() {
        return `<div style="padding:24px;display:flex;gap:16px;flex-wrap:wrap">
            ${[1,2,3].map(() => `<div class="skeleton" style="height:100px;flex:1;min-width:140px;border-radius:8px"></div>`).join('')}
        </div>`;
    }

    function bindShellEvents() {
        document.getElementById('library-tabs')?.querySelectorAll('.section-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                activeTab = btn.dataset.tab;
                document.querySelectorAll('#library-tabs .section-tab').forEach(b =>
                    b.classList.toggle('active', b.dataset.tab === activeTab)
                );
                switchTab(activeTab);
            });
        });
    }

    async function switchTab(tab) {
        const content = document.getElementById('library-content');
        if (!content) return;
        content.innerHTML = buildSkeleton();
        if (tab === 'overview') await loadOverview();
        else if (tab === 'browse') await loadBrowse();
        else if (tab === 'unmatched') await loadUnmatched();
    }

    // ── Overview Tab ──────────────────────────────────────────────────
    async function loadOverview() {
        const content = document.getElementById('library-content');
        if (!content) return;
        try {
            stats = await api.get('/library/stats');

            const unmatched = stats.unmatched_tracks || 0;
            const countEl = document.getElementById('unmatched-tab-count');
            if (countEl) countEl.textContent = unmatched > 0 ? unmatched : '';

            const size = formatBytes(stats.total_size || 0);
            const lastScan = stats.last_scan;
            const scanInfo = lastScan
                ? `Last scan: ${timeAgo(lastScan.completed_at || lastScan.started_at)} · ${(lastScan.tracks_found || 0).toLocaleString()} files`
                : 'No scans yet';

            content.innerHTML = `
            <div style="padding:24px">
                <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px">
                    ${statCard((stats.total_artists || 0).toLocaleString(), 'Artists', 'var(--accent)')}
                    ${statCard((stats.total_albums || 0).toLocaleString(), 'Albums', 'var(--teal)')}
                    ${statCard((stats.total_tracks || 0).toLocaleString(), 'Tracks', 'var(--text)')}
                </div>

                <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px">
                    <div style="flex:1;min-width:200px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:16px">
                        <div style="font-size:.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Total Size</div>
                        <div style="font-size:1.4rem;font-weight:600;color:var(--text)">${esc(size)}</div>
                    </div>
                    <div style="flex:1;min-width:200px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:16px">
                        <div style="font-size:.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Unmapped Files</div>
                        <div style="font-size:1.4rem;font-weight:600;color:${unmatched > 0 ? 'var(--orange)' : 'var(--text)'}">
                            ${unmatched.toLocaleString()}
                        </div>
                        ${unmatched > 0 ? `<button class="btn btn-sm" style="margin-top:8px" id="go-unmatched">View Unmapped</button>` : ''}
                    </div>
                    <div style="flex:2;min-width:200px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:16px">
                        <div style="font-size:.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Last Scan</div>
                        <div style="font-size:.9rem;color:var(--text-dim)">${esc(scanInfo)}</div>
                        ${lastScan && lastScan.status ? `<span class="status-badge ${lastScan.status === 'completed' ? 'have' : 'missing'}" style="margin-top:8px;font-size:.7rem">${esc(lastScan.status)}</span>` : ''}
                        <div style="margin-top:10px">
                            <button class="btn btn-sm" id="lib-scan-btn">Scan Now</button>
                        </div>
                    </div>
                </div>
            </div>`;

            document.getElementById('go-unmatched')?.addEventListener('click', () => {
                activeTab = 'unmatched';
                document.querySelectorAll('#library-tabs .section-tab').forEach(b =>
                    b.classList.toggle('active', b.dataset.tab === 'unmatched')
                );
                switchTab('unmatched');
            });

            document.getElementById('lib-scan-btn')?.addEventListener('click', async () => {
                const btn = document.getElementById('lib-scan-btn');
                btn.disabled = true; btn.textContent = 'Starting…';
                try {
                    await api.post('/library/scan', {});
                    toast('Library scan started', 'success');
                    btn.textContent = 'Scanning…';
                } catch (e) {
                    toast('Failed: ' + e.message, 'error');
                    btn.disabled = false; btn.textContent = 'Scan Now';
                }
            });

        } catch (e) {
            content.innerHTML = `<div class="empty-state" style="padding-top:60px">
                <div class="empty-state-title">Failed to load library stats</div>
                <div class="empty-state-body">${esc(e.message)}</div>
            </div>`;
        }
    }

    function statCard(value, label, color) {
        return `
        <div style="flex:1;min-width:140px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:20px 20px 16px">
            <div style="font-size:2.5rem;font-weight:700;color:${color};line-height:1.1">${esc(value)}</div>
            <div style="font-size:.8rem;color:var(--text-muted);margin-top:6px">${esc(label)}</div>
        </div>`;
    }

    function formatBytes(bytes) {
        if (!bytes) return '0 B';
        if (bytes >= 1099511627776) return (bytes / 1099511627776).toFixed(1) + ' TB';
        if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + ' GB';
        if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
        return (bytes / 1024).toFixed(0) + ' KB';
    }

    // ── Browse Tab ────────────────────────────────────────────────────
    async function loadBrowse(reset = true) {
        const content = document.getElementById('library-content');
        if (!content) return;

        if (reset) {
            browseOffset = 0; browseItems = []; browseTotal = 0;
            expandedArtist = null; expandedAlbums = null; expandedAlbum = null; expandedTracks = null;
            content.innerHTML = buildBrowseShell();
            bindBrowseEvents();
        }

        await fetchBrowseArtists(reset);
    }

    function buildBrowseShell() {
        const letters = ['#', 'A','B','C','D','E','F','G','H','I','J','K','L','M','N','O','P','Q','R','S','T','U','V','W','X','Y','Z'];
        return `
        <div style="padding:16px 24px 0">
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px">
                <input class="input" id="browse-search" type="text" placeholder="Search artists…" style="flex:1;max-width:340px" value="${esc(browseQuery)}">
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px">
                <button class="filter-btn ${browseLetter === '' ? 'active' : ''}" data-letter="">All</button>
                ${letters.map(l => `<button class="filter-btn ${browseLetter === l ? 'active' : ''}" data-letter="${l}" style="min-width:28px;text-align:center">${l}</button>`).join('')}
            </div>
        </div>
        <div id="browse-artist-list" style="padding:0 24px 16px"></div>
        <div id="browse-load-more" style="text-align:center;padding:12px 24px" hidden>
            <button class="btn" id="browse-more-btn">Load More</button>
        </div>`;
    }

    function bindBrowseEvents() {
        const searchInput = document.getElementById('browse-search');
        searchInput?.addEventListener('input', () => {
            clearTimeout(browseDebounce);
            browseDebounce = setTimeout(() => {
                browseQuery = searchInput.value.trim();
                browseLetter = '';
                document.querySelectorAll('[data-letter]').forEach(b =>
                    b.classList.toggle('active', b.dataset.letter === '')
                );
                loadBrowse(true);
            }, 300);
        });

        document.querySelectorAll('[data-letter]').forEach(btn => {
            btn.addEventListener('click', () => {
                browseLetter = btn.dataset.letter;
                browseQuery = '';
                const si = document.getElementById('browse-search');
                if (si) si.value = '';
                document.querySelectorAll('[data-letter]').forEach(b =>
                    b.classList.toggle('active', b.dataset.letter === browseLetter)
                );
                loadBrowse(true);
            });
        });

        document.getElementById('browse-more-btn')?.addEventListener('click', () => fetchBrowseArtists(false));
    }

    async function fetchBrowseArtists(reset = false) {
        try {
            const params = new URLSearchParams({ offset: browseOffset, limit: 50 });
            if (browseQuery) params.set('q', browseQuery);
            if (browseLetter) params.set('letter', browseLetter);
            const data = await api.get(`/library/browse/artists?${params}`);

            if (reset) browseItems = data.artists || [];
            else browseItems = browseItems.concat(data.artists || []);
            browseTotal = data.total || 0;
            browseOffset = browseItems.length;

            renderBrowseArtists();
        } catch (e) {
            const list = document.getElementById('browse-artist-list');
            if (list) list.innerHTML = `<div style="color:var(--red);padding:16px">Failed to load: ${esc(e.message)}</div>`;
        }
    }

    function renderBrowseArtists() {
        const list = document.getElementById('browse-artist-list');
        if (!list) return;

        if (browseItems.length === 0) {
            list.innerHTML = `<div class="empty-state" style="padding:40px 0">
                <div class="empty-state-title">No Artists Found</div>
                <div class="empty-state-body">Try a different search or letter filter.</div>
            </div>`;
            const lm = document.getElementById('browse-load-more');
            if (lm) lm.hidden = true;
            return;
        }

        list.innerHTML = browseItems.map((a, i) => `
        <div class="arr-table-row browse-artist-row" data-artist="${esc(a.artist_name)}" data-idx="${i}"
             style="display:flex;align-items:center;gap:12px;padding:10px 8px;border-top:1px solid var(--border);cursor:pointer;border-radius:4px">
            <div style="width:32px;height:32px;background:var(--accent);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.85rem;font-weight:600;color:#fff;flex-shrink:0">
                ${esc((a.artist_name || '?')[0].toUpperCase())}
            </div>
            <div style="flex:1;min-width:0">
                <div style="font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(a.artist_name)}</div>
                <div style="font-size:.75rem;color:var(--text-muted)">${a.track_count} tracks · ${a.album_count} album${a.album_count !== 1 ? 's' : ''}</div>
            </div>
            <svg class="browse-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" style="color:var(--text-muted);flex-shrink:0;transition:transform .2s">
                <polyline points="9 18 15 12 9 6"/>
            </svg>
        </div>
        <div class="browse-artist-expand" data-for="${esc(a.artist_name)}" hidden style="padding:0 0 8px 52px;background:var(--bg-raised);border-radius:4px;margin-bottom:2px"></div>
        `).join('');

        list.querySelectorAll('.browse-artist-row').forEach(row => {
            row.addEventListener('click', () => toggleArtistExpand(row.dataset.artist, row));
        });

        const lm = document.getElementById('browse-load-more');
        if (lm) {
            lm.hidden = browseOffset >= browseTotal;
            const btn = document.getElementById('browse-more-btn');
            if (btn) btn.textContent = `Load More (${browseTotal - browseOffset} more)`;
        }
    }

    async function toggleArtistExpand(artistName, row) {
        const expandDiv = document.querySelector(`.browse-artist-expand[data-for="${CSS.escape(artistName)}"]`);
        const chevron = row.querySelector('.browse-chevron');

        if (expandedArtist === artistName) {
            // Collapse
            expandedArtist = null; expandedAlbums = null; expandedAlbum = null; expandedTracks = null;
            if (expandDiv) expandDiv.hidden = true;
            if (chevron) chevron.style.transform = '';
            return;
        }

        expandedArtist = artistName;
        expandedAlbum = null; expandedTracks = null;

        // Collapse any other expanded
        document.querySelectorAll('.browse-artist-expand').forEach(d => d.hidden = true);
        document.querySelectorAll('.browse-chevron').forEach(c => c.style.transform = '');

        if (expandDiv) {
            expandDiv.hidden = false;
            expandDiv.innerHTML = `<div style="padding:10px;color:var(--text-muted)">Loading albums…</div>`;
        }
        if (chevron) chevron.style.transform = 'rotate(90deg)';

        try {
            const data = await api.get(`/library/browse/albums?artist=${encodeURIComponent(artistName)}`);
            expandedAlbums = data.albums || [];
            renderExpandedAlbums(expandDiv, artistName);
        } catch (e) {
            if (expandDiv) expandDiv.innerHTML = `<div style="padding:10px;color:var(--red)">Failed: ${esc(e.message)}</div>`;
        }
    }

    function renderExpandedAlbums(container, artistName) {
        if (!container) return;
        if (expandedAlbums.length === 0) {
            container.innerHTML = `<div style="padding:10px;color:var(--text-muted)">No albums found.</div>`;
            return;
        }
        container.innerHTML = expandedAlbums.map((alb, i) => `
        <div class="browse-album-row" data-album="${esc(alb.album_name)}" data-artist="${esc(artistName)}"
             style="display:flex;align-items:center;gap:8px;padding:7px 8px;cursor:pointer;border-top:1px solid var(--border);margin-top:2px">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" style="color:var(--text-muted);flex-shrink:0"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
            <div style="flex:1;min-width:0">
                <span style="font-weight:500">${esc(alb.album_name)}</span>
                <span style="color:var(--text-muted);font-size:.75rem;margin-left:8px">${alb.year || ''} · ${alb.track_count} tracks · ${esc(alb.format || '')}</span>
            </div>
            <svg class="album-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12" style="color:var(--text-muted);transition:transform .2s">
                <polyline points="9 18 15 12 9 6"/>
            </svg>
        </div>
        <div class="browse-track-expand" data-album="${esc(alb.album_name)}" data-artist="${esc(artistName)}" hidden style="padding:4px 8px 8px 28px"></div>
        `).join('');

        container.querySelectorAll('.browse-album-row').forEach(row => {
            row.addEventListener('click', () => toggleAlbumExpand(row.dataset.artist, row.dataset.album, row, container));
        });
    }

    async function toggleAlbumExpand(artistName, albumName, row, container) {
        const trackDiv = container.querySelector(`.browse-track-expand[data-album="${CSS.escape(albumName)}"][data-artist="${CSS.escape(artistName)}"]`);
        const chevron = row.querySelector('.album-chevron');

        if (expandedAlbum === albumName) {
            expandedAlbum = null; expandedTracks = null;
            if (trackDiv) trackDiv.hidden = true;
            if (chevron) chevron.style.transform = '';
            return;
        }

        expandedAlbum = albumName;

        container.querySelectorAll('.browse-track-expand').forEach(d => d.hidden = true);
        container.querySelectorAll('.album-chevron').forEach(c => c.style.transform = '');

        if (trackDiv) {
            trackDiv.hidden = false;
            trackDiv.innerHTML = `<div style="padding:8px;color:var(--text-muted)">Loading tracks…</div>`;
        }
        if (chevron) chevron.style.transform = 'rotate(90deg)';

        try {
            const data = await api.get(`/library/browse/tracks?artist=${encodeURIComponent(artistName)}&album=${encodeURIComponent(albumName)}`);
            expandedTracks = data.tracks || [];
            if (trackDiv) {
                if (expandedTracks.length === 0) {
                    trackDiv.innerHTML = `<div style="padding:8px;color:var(--text-muted)">No tracks.</div>`;
                } else {
                    trackDiv.innerHTML = expandedTracks.map(t => `
                    <div style="display:flex;align-items:center;gap:8px;padding:4px 4px;border-top:1px solid var(--border)">
                        <span style="color:var(--text-muted);font-size:.75rem;min-width:24px;text-align:right">${t.track_number || ''}</span>
                        <span style="flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:.85rem">${esc(t.title || t.path.split('/').pop())}</span>
                        <span style="color:var(--text-muted);font-size:.75rem">${t.duration ? fmtSecs(t.duration) : ''}</span>
                        <span style="color:var(--text-muted);font-size:.7rem">${esc(t.format || '')}</span>
                        ${t.spotify_id && t.spotify_id !== 'IGNORED' ? `<span style="color:var(--teal);font-size:.7rem" title="Matched">✓</span>` : `<span style="color:var(--text-muted);font-size:.7rem" title="Unmatched">○</span>`}
                    </div>`).join('');
                }
            }
        } catch (e) {
            if (trackDiv) trackDiv.innerHTML = `<div style="padding:8px;color:var(--red)">Failed: ${esc(e.message)}</div>`;
        }
    }

    function fmtSecs(s) {
        if (!s) return '';
        const m = Math.floor(s / 60);
        return `${m}:${String(s % 60).padStart(2, '0')}`;
    }

    // ── Unmatched Tab ─────────────────────────────────────────────────
    async function loadUnmatched(reset = true) {
        const content = document.getElementById('library-content');
        if (!content) return;

        if (reset) {
            unmatchedOffset = 0;
            unmatchedTotal = 0;
            content.innerHTML = buildUnmatchedShell();
            bindUnmatchedEvents();
        }

        await fetchUnmatched(reset);
    }

    function buildUnmatchedShell() {
        return `
        <div style="padding:16px 24px 0">
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px">
                <input class="input" id="unmatched-search" type="text" placeholder="Filter by path, artist, title…" style="flex:1;max-width:400px" value="${esc(unmatchedQuery)}">
                <button class="btn btn-sm btn-primary" id="auto-match-btn">Auto-Match</button>
                <button class="btn btn-sm" id="mb-identify-btn" title="Search MusicBrainz to identify tracks (1 req/s — runs in background)">MB Identify</button>
            </div>
            <div id="auto-match-panel" hidden style="margin-bottom:8px;background:var(--bg-raised);border:1px solid var(--border);border-radius:8px;padding:12px 14px">
                <div style="display:flex;justify-content:space-between;font-size:.8rem;color:var(--text-dim);margin-bottom:6px">
                    <span id="amp-label">Starting…</span>
                    <span id="amp-counts"></span>
                </div>
                <div style="background:var(--bg-card);border-radius:4px;height:6px;overflow:hidden">
                    <div id="amp-bar" style="height:100%;background:var(--accent);width:0%;transition:width .3s ease"></div>
                </div>
                <div style="font-size:.72rem;color:var(--text-muted);margin-top:5px" id="amp-current"></div>
            </div>
            <div id="mb-identify-panel" hidden style="margin-bottom:8px;background:var(--bg-raised);border:1px solid var(--border);border-radius:8px;padding:12px 14px">
                <div style="display:flex;justify-content:space-between;font-size:.8rem;color:var(--text-dim);margin-bottom:6px">
                    <span id="mbp-label">Starting…</span>
                    <span id="mbp-counts"></span>
                </div>
                <div style="background:var(--bg-card);border-radius:4px;height:6px;overflow:hidden">
                    <div id="mbp-bar" style="height:100%;background:var(--teal);width:0%;transition:width .3s ease"></div>
                </div>
                <div style="font-size:.72rem;color:var(--text-muted);margin-top:5px" id="mbp-current"></div>
            </div>
        </div>
        <div style="padding:0 24px 4px;font-size:.8rem;color:var(--text-dim)" id="unmatched-count"></div>
        <div id="unmatched-list" style="padding:0 24px 16px"></div>
        <div id="unmatched-load-more" style="text-align:center;padding:12px 24px" hidden>
            <button class="btn" id="unmatched-more-btn">Load More</button>
        </div>`;
    }

    function bindUnmatchedEvents() {
        const searchInput = document.getElementById('unmatched-search');
        searchInput?.addEventListener('input', () => {
            clearTimeout(unmatchedDebounce);
            unmatchedDebounce = setTimeout(() => {
                unmatchedQuery = searchInput.value.trim();
                unmatchedOffset = 0;
                fetchUnmatched(true);
            }, 300);
        });

        document.getElementById('unmatched-more-btn')?.addEventListener('click', () => fetchUnmatched(false));

        // ── MB Identify ──────────────────────────────────────────────
        let _mbIdentifyPollTimer = null;
        document.getElementById('mb-identify-btn')?.addEventListener('click', async () => {
            if (_mbIdentifyPollTimer) return;

            const btn    = document.getElementById('mb-identify-btn');
            const panel  = document.getElementById('mb-identify-panel');
            const bar    = document.getElementById('mbp-bar');
            const label  = document.getElementById('mbp-label');
            const counts = document.getElementById('mbp-counts');
            const curr   = document.getElementById('mbp-current');

            btn.disabled = true;
            btn.textContent = 'Running…';
            if (panel) panel.hidden = false;
            if (label) label.textContent = 'Starting MusicBrainz lookup…';
            if (counts) counts.textContent = '';
            if (bar) bar.style.width = '0%';
            if (curr) curr.textContent = '';

            try {
                const startResp = await api.post('/library/mb-identify/start', {});
                if (!startResp.started && startResp.reason !== 'already running') {
                    throw new Error(startResp.reason || 'failed to start');
                }
            } catch (e) {
                btn.disabled = false; btn.textContent = 'MB Identify';
                if (panel) panel.hidden = true;
                toast('MB Identify failed to start: ' + e.message, 'error');
                return;
            }

            const stopPolling = (err) => {
                clearInterval(_mbIdentifyPollTimer);
                _mbIdentifyPollTimer = null;
                btn.disabled = false;
                btn.textContent = 'MB Identify';
                if (panel) panel.hidden = true;
                if (err) toast('MB Identify error: ' + err, 'error');
            };

            _mbIdentifyPollTimer = setInterval(async () => {
                try {
                    const d = await api.get('/library/mb-identify/progress');
                    const pct = d.pct || 0;
                    if (bar) bar.style.width = pct + '%';
                    if (d.total > 0) {
                        if (label) label.textContent = `${pct}% · ${d.identified || 0} identified`;
                        if (counts) counts.textContent = `${(d.processed || 0).toLocaleString()} / ${(d.total || 0).toLocaleString()}`;
                    } else {
                        if (label) label.textContent = 'Scanning…';
                    }
                    if (curr && d.current) curr.textContent = d.current;
                    if (d.error) {
                        stopPolling(d.error);
                    } else if (d.done) {
                        stopPolling(null);
                        const msg = d.identified > 0
                            ? `Identified ${d.identified} track${d.identified !== 1 ? 's' : ''} via MusicBrainz`
                            : 'No new tracks identified via MusicBrainz';
                        toast(msg, d.identified > 0 ? 'success' : 'info');
                        unmatchedOffset = 0;
                        fetchUnmatched(true);
                    }
                } catch (e) {
                    stopPolling(e.message);
                }
            }, 2000);
        });

        // ── Auto-Match ───────────────────────────────────────────────
        let _autoMatchPollTimer = null;
        document.getElementById('auto-match-btn')?.addEventListener('click', async () => {
            if (_autoMatchPollTimer) return;

            const btn    = document.getElementById('auto-match-btn');
            const panel  = document.getElementById('auto-match-panel');
            const bar    = document.getElementById('amp-bar');
            const label  = document.getElementById('amp-label');
            const counts = document.getElementById('amp-counts');
            const curr   = document.getElementById('amp-current');

            btn.disabled = true;
            btn.textContent = 'Running…';
            if (panel) panel.hidden = false;
            if (label) label.textContent = 'Starting…';
            if (counts) counts.textContent = '';
            if (bar) bar.style.width = '0%';
            if (curr) curr.textContent = '';

            try {
                const startResp = await api.post('/library/auto-match/start', {});
                if (!startResp.started && startResp.reason !== 'already running') {
                    throw new Error(startResp.reason || 'failed to start');
                }
            } catch (e) {
                btn.disabled = false; btn.textContent = 'Auto-Match';
                if (panel) panel.hidden = true;
                toast('Auto-match failed to start: ' + e.message, 'error');
                return;
            }

            const stopPolling = (err) => {
                clearInterval(_autoMatchPollTimer);
                _autoMatchPollTimer = null;
                btn.disabled = false;
                btn.textContent = 'Auto-Match';
                if (panel) panel.hidden = true;
                if (err) toast('Auto-match error: ' + err, 'error');
            };

            _autoMatchPollTimer = setInterval(async () => {
                try {
                    const d = await api.get('/library/auto-match/progress');
                    const pct = d.pct || 0;

                    if (bar) bar.style.width = pct + '%';
                    if (d.total > 0) {
                        if (label) label.textContent = `${pct}% · ${d.matched || 0} matched`;
                        if (counts) counts.textContent = `${(d.processed || 0).toLocaleString()} / ${(d.total || 0).toLocaleString()}`;
                    } else {
                        if (label) label.textContent = 'Scanning…';
                    }
                    if (curr && d.current) curr.textContent = d.current;

                    if (d.error) {
                        stopPolling(d.error);
                    } else if (d.done) {
                        stopPolling(null);
                        const msg = d.matched > 0
                            ? `Matched ${d.matched} track${d.matched !== 1 ? 's' : ''} of ${(d.processed || 0).toLocaleString()} scanned`
                            : `No new matches found`;
                        toast(msg, d.matched > 0 ? 'success' : 'info');
                        unmatchedOffset = 0;
                        fetchUnmatched(true);
                    }
                } catch (e) {
                    stopPolling(e.message);
                }
            }, 1500);
        });
    }

    async function fetchUnmatched(reset = false) {
        const params = new URLSearchParams({ offset: unmatchedOffset, limit: 50 });
        if (unmatchedQuery) params.set('q', unmatchedQuery);

        try {
            const data = await api.get(`/library/unmatched/search?${params}`);
            unmatchedTotal = data.total || 0;
            unmatchedOffset += (data.items || []).length;

            const countEl = document.getElementById('unmatched-count');
            if (countEl) countEl.textContent = `${unmatchedTotal} unmapped file${unmatchedTotal !== 1 ? 's' : ''}`;

            const tabCount = document.getElementById('unmatched-tab-count');
            if (tabCount) tabCount.textContent = unmatchedTotal > 0 ? unmatchedTotal : '';

            renderUnmatched(data.items || [], reset);
        } catch (e) {
            const list = document.getElementById('unmatched-list');
            if (list) list.innerHTML = `<div style="color:var(--red)">Failed: ${esc(e.message)}</div>`;
        }
    }

    let unmatchedRows = [];

    function renderUnmatched(items, reset = false) {
        const list = document.getElementById('unmatched-list');
        if (!list) return;

        if (reset) unmatchedRows = [];
        unmatchedRows = unmatchedRows.concat(items);

        if (unmatchedRows.length === 0) {
            list.innerHTML = `<div class="empty-state" style="padding:40px 0">
                <div class="empty-state-title">No Unmapped Files</div>
                <div class="empty-state-body">All your local tracks have been matched to Spotify.</div>
            </div>`;
            const lm = document.getElementById('unmatched-load-more');
            if (lm) lm.hidden = true;
            return;
        }

        list.innerHTML = `
        <table class="arr-table" style="width:100%">
            <thead>
                <tr>
                    <th>Path</th>
                    <th style="width:120px">Artist Tag</th>
                    <th style="width:160px">Title Tag</th>
                    <th style="width:60px">Format</th>
                    <th style="width:70px">Size</th>
                    <th style="width:100px;text-align:right">Actions</th>
                </tr>
            </thead>
            <tbody>${unmatchedRows.map(t => buildUnmatchedRow(t)).join('')}</tbody>
        </table>`;

        list.querySelectorAll('.unmatched-match-btn').forEach(btn => {
            btn.addEventListener('click', () => openMatchPopover(parseInt(btn.dataset.id), btn));
        });
        list.querySelectorAll('.unmatched-ignore-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const id = parseInt(btn.dataset.id);
                try {
                    await api.post(`/library/unmatched/${id}/ignore`, {});
                    unmatchedRows = unmatchedRows.filter(r => r.id !== id);
                    unmatchedTotal = Math.max(0, unmatchedTotal - 1);
                    renderUnmatched([], false);
                    toast('Track ignored', 'info');
                } catch (e) { toast('Failed: ' + e.message, 'error'); }
            });
        });

        const lm = document.getElementById('unmatched-load-more');
        if (lm) {
            lm.hidden = unmatchedOffset >= unmatchedTotal;
            const btn = document.getElementById('unmatched-more-btn');
            if (btn) btn.textContent = `Load More (${unmatchedTotal - unmatchedOffset} more)`;
        }
    }

    function buildUnmatchedRow(t) {
        const filename = (t.path || '').split('/').pop();
        const size = t.size ? formatBytes(t.size) : '—';
        return `
        <tr class="arr-table-row" data-track-id="${t.id}">
            <td style="max-width:280px">
                <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:.83rem" title="${esc(t.path)}">${esc(filename)}</div>
                <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:.7rem;color:var(--text-muted)" title="${esc(t.path)}">${esc(t.path)}</div>
            </td>
            <td style="color:var(--text-dim);max-width:120px"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.artist || '')}</div></td>
            <td style="max-width:160px"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.title || '')}</div></td>
            <td style="color:var(--text-muted)">${esc(t.format || '')}</td>
            <td style="color:var(--text-muted)">${size}</td>
            <td style="text-align:right">
                <div style="display:flex;gap:4px;justify-content:flex-end">
                    <button class="btn btn-sm btn-primary unmatched-match-btn" data-id="${t.id}" data-artist="${esc(t.artist||'')}" data-title="${esc(t.title||'')}" data-duration="${t.duration||0}">Match</button>
                    <button class="btn btn-sm unmatched-ignore-btn" data-id="${t.id}" style="color:var(--text-muted)">Ignore</button>
                </div>
            </td>
        </tr>`;
    }

    async function openMatchPopover(trackId, btn) {
        // Close existing popover
        const existing = document.getElementById('match-popover');
        if (existing) existing.remove();
        if (matchPopoverTrackId === trackId) { matchPopoverTrackId = null; return; }
        matchPopoverTrackId = trackId;

        const artist = btn.dataset.artist || '';
        const title = btn.dataset.title || '';
        const durationMs = (parseInt(btn.dataset.duration) || 0) * 1000;

        // Create popover
        const popover = document.createElement('div');
        popover.id = 'match-popover';
        popover.style.cssText = 'position:fixed;z-index:1000;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:12px;min-width:340px;max-width:480px;box-shadow:0 4px 24px rgba(0,0,0,.4)';
        popover.innerHTML = `<div style="font-size:.8rem;color:var(--text-muted);margin-bottom:8px">Finding matches for: <strong>${esc(title)}</strong></div>
        <div id="mp-results"><div style="padding:12px 0;text-align:center;color:var(--text-muted)">Searching…</div></div>`;
        document.body.appendChild(popover);

        // Position below button
        const rect = btn.getBoundingClientRect();
        popover.style.top = (rect.bottom + 6) + 'px';
        popover.style.left = Math.max(8, rect.left - 200) + 'px';

        // Close on outside click
        setTimeout(() => {
            document.addEventListener('click', function closePopover(e) {
                if (!popover.contains(e.target) && e.target !== btn) {
                    popover.remove();
                    matchPopoverTrackId = null;
                    document.removeEventListener('click', closePopover);
                }
            });
        }, 10);

        try {
            const data = await api.get(`/library/match/candidates?title=${encodeURIComponent(title)}&artist=${encodeURIComponent(artist)}&duration_ms=${durationMs}`);
            const candidates = data.candidates || [];
            const mbResults  = data.mb_results || [];
            const mpResults = document.getElementById('mp-results');
            if (!mpResults) return;

            const allResults = [
                ...candidates.map(c => ({ ...c, _source: 'monitored' })),
                ...mbResults.map(c => ({ ...c, _source: 'mb' })),
            ];

            if (allResults.length === 0) {
                mpResults.innerHTML = `<div style="padding:8px 0;color:var(--text-muted)">No candidates found in monitored tracks or MusicBrainz.</div>`;
                return;
            }

            // Auto-apply if top candidate is 100% confidence
            const top = allResults[0];
            if (top.confidence >= 100) {
                try {
                    const body = top.spotify_id ? { spotify_id: top.spotify_id } : { mbid: top.mbid };
                    await api.post(`/library/unmatched/${trackId}/match`, body);
                    const tag = top._source === 'mb' ? '[MB]' : '';
                    toast(`Auto-matched ${tag}: ${top.title} — ${top.artist}`, 'success');
                    popover.remove();
                    matchPopoverTrackId = null;
                    unmatchedRows = unmatchedRows.filter(r => r.id !== trackId);
                    unmatchedTotal = Math.max(0, unmatchedTotal - 1);
                    renderUnmatched([], false);
                } catch (e) { toast('Auto-match failed: ' + e.message, 'error'); }
                return;
            }

            function renderSection(items, heading) {
                if (!items.length) return '';
                return `<div style="font-size:.68rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;padding:6px 4px 2px">${heading}</div>` +
                items.map(c => `
                <div class="arr-table-row mp-candidate"
                     data-spotify-id="${esc(c.spotify_id || '')}"
                     data-mbid="${esc(c.mbid || '')}"
                     style="display:flex;gap:10px;align-items:center;padding:8px 4px;cursor:pointer;border-top:1px solid var(--border);border-radius:4px">
                    <div style="width:36px;height:36px;background:var(--bg-raised);border-radius:2px;flex-shrink:0;display:flex;align-items:center;justify-content:center">
                        ${c._source === 'mb' ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M9 19V6l12-3v13"/><circle cx="6" cy="19" r="3"/><circle cx="18" cy="16" r="3"/></svg>` : ''}
                    </div>
                    <div style="flex:1;min-width:0">
                        <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:500;font-size:.85rem">${esc(c.title)}</div>
                        <div style="font-size:.75rem;color:var(--text-muted)">${esc(c.artist)}${c.album ? ' · ' + esc(c.album) : ''}</div>
                        <div style="font-size:.7rem;color:var(--text-muted)">Δ${c.duration_delta_s}s${c._source === 'mb' ? ' · MusicBrainz' : ''}</div>
                    </div>
                    <div style="flex-shrink:0;text-align:center">
                        <div style="font-size:1rem;font-weight:700;color:${c.confidence >= 80 ? 'var(--teal)' : c.confidence >= 60 ? 'var(--orange)' : 'var(--red)'}">${c.confidence}%</div>
                        <div style="font-size:.65rem;color:var(--text-muted)">conf</div>
                    </div>
                </div>`).join('');
            }

            mpResults.innerHTML =
                renderSection(candidates.map(c => ({ ...c, _source: 'monitored' })), 'Monitored Tracks') +
                renderSection(mbResults.map(c => ({ ...c, _source: 'mb' })), 'MusicBrainz');

            mpResults.querySelectorAll('.mp-candidate').forEach(row => {
                row.addEventListener('click', async () => {
                    const spotifyId = row.dataset.spotifyId;
                    const mbid = row.dataset.mbid;
                    try {
                        const body = spotifyId ? { spotify_id: spotifyId } : { mbid };
                        await api.post(`/library/unmatched/${trackId}/match`, body);
                        toast('Track identified successfully', 'success');
                        popover.remove();
                        matchPopoverTrackId = null;
                        unmatchedRows = unmatchedRows.filter(r => r.id !== trackId);
                        unmatchedTotal = Math.max(0, unmatchedTotal - 1);
                        renderUnmatched([], false);
                    } catch (e) { toast('Match failed: ' + e.message, 'error'); }
                });
            });

        } catch (e) {
            const mpResults = document.getElementById('mp-results');
            if (mpResults) mpResults.innerHTML = `<div style="padding:8px 0;color:var(--red)">Error: ${esc(e.message)}</div>`;
        }
    }

    return { load, unload };
})();
