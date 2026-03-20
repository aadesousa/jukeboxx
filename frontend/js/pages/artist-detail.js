// ─── Artist Detail Page — Phase 4 ─────────────────────────────────
const ArtistDetailPage = (() => {
    const root = () => document.getElementById('page-root');

    let artist  = null;
    let activeTab = 'album';

    const TABS = [
        { id: 'album',       label: 'Albums' },
        { id: 'single',      label: 'Singles & EPs' },
        { id: 'compilation', label: 'Compilations' },
    ];

    function tabMatch(album, tabId) {
        if (tabId === 'album')       return album.album_type === 'album';
        if (tabId === 'single')      return album.album_type === 'single' || album.album_type === 'ep';
        if (tabId === 'compilation') return album.album_type === 'compilation' || album.album_type === 'live';
        return false;
    }

    // ── Load ─────────────────────────────────────────────────────────
    async function load(params) {
        const artistId = params.id;
        if (!artistId) { navigate('/artists'); return; }

        root().innerHTML = buildSkeleton();

        try {
            artist = await api.get(`/artists/${artistId}`);
            render();
        } catch (e) {
            root().innerHTML = `<div class="empty-state" style="padding-top:80px">
                <div class="empty-state-title">Artist not found</div>
                <div class="empty-state-body">${esc(e.message)}</div>
                <a class="btn btn-primary" style="margin-top:12px" href="#/artists">Back to Artists</a>
            </div>`;
        }
    }

    function unload() { artist = null; activeTab = 'album'; }

    // ── Render ────────────────────────────────────────────────────────
    function render() {
        const albums = artist.albums || [];
        const stats  = artist.stats  || {};

        root().innerHTML = `
        ${buildHero(stats)}
        <div class="section-tabs" id="artist-tabs" style="margin:0 24px">
            ${TABS.map(t => {
                const count = albums.filter(a => tabMatch(a, t.id)).length;
                return `<button class="section-tab ${t.id === activeTab ? 'active' : ''}" data-tab="${t.id}">
                    ${t.label}${count > 0 ? ` <span style="opacity:.5;font-size:.8em">${count}</span>` : ''}
                </button>`;
            }).join('')}
        </div>
        <div id="artist-albums-grid" class="card-grid" style="padding-top:16px"></div>`;

        renderAlbums();
        bindEvents();
    }

    function renderAlbums() {
        const grid = document.getElementById('artist-albums-grid');
        if (!grid) return;
        const albums = (artist.albums || []).filter(a => tabMatch(a, activeTab));
        const tab = TABS.find(t => t.id === activeTab);
        if (albums.length === 0) {
            grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
                <div class="empty-state-title">No ${tab?.label || 'items'}</div>
                <div class="empty-state-body">Click <strong>Refresh Discography</strong> to fetch from Spotify.</div>
            </div>`;
            return;
        }
        grid.innerHTML = albums.map(buildAlbumCard).join('');
        grid.querySelectorAll('.arr-card[data-album-id]').forEach(card => {
            card.addEventListener('click', () => navigate(`/albums/${card.dataset.albumId}`));
        });
    }

    function buildAlbumCard(a) {
        const img = a.image_url
            ? `<img src="${esc(a.image_url)}" alt="${esc(a.name)}" loading="lazy">`
            : `<div class="card-poster-placeholder"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" width="48" height="48"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg></div>`;

        const statusDot = { have:'var(--green)', partial:'var(--orange)', wanted:'var(--red)', downloading:'var(--accent)', ignored:'var(--text-muted)' }[a.status] || 'var(--text-muted)';
        const year = a.release_date ? a.release_date.slice(0, 4) : '';

        return `
        <div class="arr-card" data-album-id="${a.id}">
            <div class="card-poster">${img}</div>
            <div class="card-overlay">
                <div class="card-title">${esc(a.name)}</div>
                <div class="card-subtitle" style="display:flex;align-items:center;gap:4px">
                    <span style="color:${statusDot}">●</span>
                    ${year ? `<span>${year}</span><span>·</span>` : ''}
                    <span>${a.track_count || 0} tracks</span>
                </div>
            </div>
        </div>`;
    }

    // ── Hero ──────────────────────────────────────────────────────────
    function buildHero(stats) {
        const monitored = artist.monitored;
        const genres = (artist.genres || []).slice(0, 3).join(', ');
        const heroBg = artist.image_url
            ? `background-image:linear-gradient(to bottom, rgba(0,0,0,.7) 0%, rgba(0,0,0,.9) 100%), url('${esc(artist.image_url)}'); background-size:cover; background-position:center top;`
            : '';

        return `
        <div class="artist-hero" style="${heroBg}">
            <div class="artist-hero-content">
                <div class="artist-hero-poster">
                    ${artist.image_url
                        ? `<img src="${esc(artist.image_url)}" alt="${esc(artist.name)}" style="width:100%;height:100%;object-fit:cover;border-radius:50%">`
                        : `<div style="width:100%;height:100%;border-radius:50%;background:var(--bg-raised);display:flex;align-items:center;justify-content:center;color:var(--text-muted)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" width="64" height="64"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg></div>`}
                </div>
                <div class="artist-hero-info">
                    <div class="breadcrumb" style="margin-bottom:8px">
                        <a class="breadcrumb-item" href="#/artists">Artists</a>
                        <span class="breadcrumb-sep">›</span>
                        <span class="breadcrumb-item active">${esc(artist.name)}</span>
                    </div>
                    <h1 class="artist-hero-name">${esc(artist.name)}</h1>
                    ${genres ? `<div style="font-size:.85rem;color:rgba(255,255,255,.55);margin-top:4px">${esc(genres)}</div>` : ''}
                    <div class="artist-hero-stats">
                        <span>${(artist.albums || []).length} albums</span>
                        <span>·</span>
                        <span>${stats.have || 0} / ${stats.total || 0} tracks</span>
                        ${(stats.missing || 0) > 0 ? `<span>·</span><span style="color:var(--orange)">${stats.missing} missing</span>` : ''}
                    </div>
                    <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap">
                        <button class="btn btn-sm ${monitored ? 'btn-primary' : ''}" id="hero-monitor-btn">
                            ${monitored ? '● Monitored' : '○ Unmonitored'}
                        </button>
                        <button class="btn btn-sm" id="hero-refresh-btn">Refresh Discography</button>
                        <button class="btn btn-sm btn-primary" id="search-missing-btn">Search Missing</button>
                        <a class="btn btn-sm" href="#/import">Import Liked Songs</a>
                        <button class="btn btn-sm" id="hero-delete-btn" style="margin-left:auto;color:var(--red);border-color:transparent;background:transparent">Remove Artist</button>
                    </div>
                </div>
            </div>
        </div>`;
    }

    function buildSkeleton() {
        return `<div class="artist-hero" style="min-height:260px">
            <div class="artist-hero-content">
                <div class="artist-hero-poster"><div class="skeleton" style="width:100%;height:100%;border-radius:50%"></div></div>
                <div class="artist-hero-info" style="flex:1">
                    <div class="skeleton" style="height:12px;width:100px;margin-bottom:10px;border-radius:3px"></div>
                    <div class="skeleton" style="height:36px;width:260px;margin-bottom:8px;border-radius:3px"></div>
                    <div class="skeleton" style="height:12px;width:180px;border-radius:3px"></div>
                </div>
            </div>
        </div>
        <div class="card-grid" style="padding-top:16px">${Array.from({length:6},()=>`
            <div class="arr-card"><div class="card-poster"><div class="skeleton" style="width:100%;height:100%"></div></div></div>`).join('')}
        </div>`;
    }

    // ── Events ────────────────────────────────────────────────────────
    function bindEvents() {
        document.getElementById('artist-tabs')?.querySelectorAll('.section-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                activeTab = btn.dataset.tab;
                document.querySelectorAll('#artist-tabs .section-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === activeTab));
                renderAlbums();
            });
        });

        document.getElementById('hero-monitor-btn')?.addEventListener('click', async () => {
            const newVal = !artist.monitored;
            try {
                await api.patch(`/artists/${artist.id}`, { monitored: newVal ? 1 : 0 });
                artist.monitored = newVal;
                render();
                toast(newVal ? 'Monitoring enabled' : 'Monitoring disabled', 'success');
            } catch (e) { toast('Failed: ' + e.message, 'error'); }
        });

        document.getElementById('hero-refresh-btn')?.addEventListener('click', async () => {
            const btn = document.getElementById('hero-refresh-btn');
            btn.disabled = true; btn.textContent = 'Refreshing…';
            try {
                const result = await api.post(`/artists/${artist.id}/refresh`);
                toast(`Added ${result.added} new release${result.added !== 1 ? 's' : ''}`, 'success');
                artist = await api.get(`/artists/${artist.id}`);
                render();
            } catch (e) {
                toast('Refresh failed: ' + e.message, 'error');
                btn.disabled = false; btn.textContent = 'Refresh Discography';
            }
        });

        document.getElementById('hero-delete-btn')?.addEventListener('click', async () => {
            if (!confirm(`Remove ${artist.name}? All tracked albums and tracks will be unmonitored.`)) return;
            try {
                await api.del(`/artists/${artist.id}`);
                toast(`${artist.name} removed`, 'info');
                navigate('/artists');
            } catch (e) { toast('Failed: ' + e.message, 'error'); }
        });

        document.getElementById('search-missing-btn')?.addEventListener('click', async () => {
            const btn = document.getElementById('search-missing-btn');
            btn.disabled = true;
            btn.textContent = 'Queuing…';
            try {
                const r = await api.post(`/artists/${artist.id}/command`, { command: 'download-missing' });
                toast(r.queued > 0 ? `Queued ${r.queued} tracks for download` : 'Nothing new to queue', r.queued > 0 ? 'success' : 'info');
            } catch (e) {
                toast('Failed to queue downloads', 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = 'Search Missing';
            }
        });
    }

    return { load, unload };
})();
