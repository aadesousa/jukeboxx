// ─── Library Tab ─────────────────────────────────────────────────
const Library = (() => {
    let currentView = 'playlists';
    let offset = 0;
    const limit = 30;
    let forceRefresh = false;

    function init() {
        document.querySelectorAll('.view-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentView = btn.dataset.view;
                offset = 0;
                forceRefresh = false;
                updateFilterVisibility();
                load();
            });
        });

        const refreshBtn = document.getElementById('library-refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                forceRefresh = true;
                offset = 0;
                load();
            });
        }

        const searchInput = document.getElementById('library-search');
        if (searchInput) {
            searchInput.addEventListener('input', debounce(() => {
                offset = 0;
                load();
            }, 300));
        }

        updateFilterVisibility();
    }

    function updateFilterVisibility() {
        const filterBox = document.getElementById('library-filter-box');
        if (filterBox) {
            filterBox.style.display = currentView === 'local' ? '' : 'none';
        }
    }

    async function load() {
        const content = document.getElementById('library-content');
        const pagination = document.getElementById('library-pagination');
        showSkeleton(content, 6);
        pagination.innerHTML = '';

        try {
            if (currentView === 'local') {
                await loadLocal(content, pagination);
            } else if (currentView === 'playlists') {
                await loadPlaylists(content, pagination);
            }
        } catch (err) {
            content.innerHTML = `<div class="empty-state">${err.message}</div>`;
        }
        forceRefresh = false;
    }

    async function loadPlaylists(content, pagination) {
        const refreshParam = forceRefresh ? '&refresh=true' : '';
        const data = await api.get(`/spotify/playlists?offset=${offset}&limit=${limit}${refreshParam}`);
        const items = data.items || [];
        if (!items.length) {
            content.innerHTML = '<div class="empty-state">No playlists found</div>';
            return;
        }
        content.innerHTML = items.map(pl => playlistCard(pl)).join('');
        attachCardHandlers(content, 'playlist');
        renderPagination(pagination, data.total, data.offset);
    }

    async function loadLocal(content, pagination) {
        const q = document.getElementById('library-search')?.value?.trim() || '';
        const data = await api.get(`/library/tracks?offset=${offset}&limit=${limit}&q=${encodeURIComponent(q)}`);
        const tracks = data.tracks || [];
        if (!tracks.length) {
            content.innerHTML = '<div class="empty-state">No local tracks found. Run a scan from the Dashboard.</div>';
            return;
        }
        content.innerHTML = '<div class="download-list" style="grid-column:1/-1">' +
            tracks.map(t => localTrackRow(t)).join('') + '</div>';
        renderPagination(pagination, data.total, data.offset);
    }

    // ─── Card Renderers ──────────────────────────────────────────
    function playlistCard(pl) {
        const img = imgUrl(pl.images);
        const imgHtml = img ? `<img class="lib-card-img" src="${img}" alt="">` : '<div class="lib-card-img"></div>';
        const trackCount = pl.tracks?.total || 0;
        return `<div class="lib-card" data-type="playlist" data-id="${pl.id}" data-name="${pl.name || ''}">
            <div class="lib-card-header">
                ${imgHtml}
                <div class="lib-card-info">
                    <div class="lib-card-title">${pl.name || 'Untitled'}</div>
                    <div class="lib-card-sub">${trackCount} tracks</div>
                </div>
                <div class="lib-card-actions">
                    <button class="btn btn-sm btn-green dl-all-btn" title="Download all missing">
                        <svg class="icon" viewBox="0 0 16 16" width="14" height="14"><path d="M7.47 10.78a.75.75 0 0 0 1.06 0l3.75-3.75a.75.75 0 0 0-1.06-1.06L8.75 8.44V1.75a.75.75 0 0 0-1.5 0v6.69L4.78 5.97a.75.75 0 0 0-1.06 1.06l3.75 3.75ZM3.75 13a.75.75 0 0 0 0 1.5h8.5a.75.75 0 0 0 0-1.5h-8.5Z"/></svg>
                    </button>
                    <button class="btn btn-sm sync-btn" title="Toggle auto-sync">
                        <svg class="icon" viewBox="0 0 16 16" width="14" height="14"><path d="M1.705 8.005a.75.75 0 0 1 .834.656 5.5 5.5 0 0 0 9.592 2.97l-1.204-1.204a.25.25 0 0 1 .177-.427h3.646a.25.25 0 0 1 .25.25v3.646a.25.25 0 0 1-.427.177l-1.38-1.38A7.002 7.002 0 0 1 1.05 8.84a.75.75 0 0 1 .656-.834ZM8 2.5a5.487 5.487 0 0 0-4.131 1.869l1.204 1.204A.25.25 0 0 1 4.896 6H1.25A.25.25 0 0 1 1 5.75V2.104a.25.25 0 0 1 .427-.177l1.38 1.38A7.002 7.002 0 0 1 14.95 7.16a.75.75 0 0 1-1.49.178A5.5 5.5 0 0 0 8 2.5Z"/></svg>
                    </button>
                </div>
            </div>
            <div class="lib-card-tracks"></div>
        </div>`;
    }

    function localTrackRow(t) {
        return `<div class="dl-item">
            <div class="dl-info">
                <div class="dl-title">${t.title || 'Unknown'}</div>
                <div class="dl-artist">${t.artist || 'Unknown'} — ${t.album || ''}</div>
            </div>
            <span style="color:var(--text-dim);font-size:.8rem">${t.format || ''} ${t.bitrate ? t.bitrate + 'k' : ''}</span>
            <span style="color:var(--text-muted);font-size:.75rem">${formatSize(t.size)}</span>
            <button class="btn-icon btn-del-track" data-id="${t.id}" title="Delete">
                <svg class="icon" viewBox="0 0 16 16" width="14" height="14"><path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z"/></svg>
            </button>
        </div>`;
    }

    // ─── Handlers ────────────────────────────────────────────────
    function attachCardHandlers(container, viewType) {
        container.querySelectorAll('.lib-card').forEach(card => {
            card.querySelector('.lib-card-header .lib-card-info')?.addEventListener('click', async () => {
                if (card.classList.contains('expanded')) {
                    card.classList.remove('expanded');
                    return;
                }
                const type = card.dataset.type;
                const id = card.dataset.id;
                const trackContainer = card.querySelector('.lib-card-tracks');
                if (!trackContainer) return;
                trackContainer.innerHTML = '<div style="padding:8px;text-align:center"><span class="spinner"></span></div>';
                card.classList.add('expanded');

                try {
                    let tracks = [];
                    if (type === 'playlist') {
                        const refreshParam = forceRefresh ? '?refresh=true' : '';
                        const data = await api.get(`/spotify/playlists/${id}/tracks${refreshParam}`);
                        tracks = data.items || [];
                        // Update the track count on the card with the actual count
                        const subEl = card.querySelector('.lib-card-sub');
                        if (subEl) subEl.textContent = `${data.total || tracks.length} tracks`;
                    }

                    trackContainer.innerHTML = tracks.map((t, i) => {
                        const artist = t.artists?.map(a => a.name).join(', ') || '';
                        const isUnavailable = t.unavailable || t.local_status === 'unavailable';
                        return `<div class="track-row ${isUnavailable ? 'track-unavailable' : ''}">
                            <span class="track-num">${i + 1}</span>
                            <span class="track-name">${t.name || 'Unknown'}</span>
                            <span class="track-artist">${artist}</span>
                            <span class="track-status">${isUnavailable ? statusIcon('unavailable') : statusIcon(t.local_status)}</span>
                            ${!isUnavailable && t.local_status !== 'local' && t.id ? `<button class="btn-icon dl-track-btn" data-id="${t.id}" title="Download"><svg class="icon" viewBox="0 0 16 16" width="14" height="14"><path d="M7.47 10.78a.75.75 0 0 0 1.06 0l3.75-3.75a.75.75 0 0 0-1.06-1.06L8.75 8.44V1.75a.75.75 0 0 0-1.5 0v6.69L4.78 5.97a.75.75 0 0 0-1.06 1.06l3.75 3.75ZM3.75 13a.75.75 0 0 0 0 1.5h8.5a.75.75 0 0 0 0-1.5h-8.5Z"/></svg></button>` : ''}
                        </div>`;
                    }).join('') || '<div style="padding:8px;color:var(--text-muted)">No tracks</div>';

                    trackContainer.querySelectorAll('.dl-track-btn').forEach(btn => {
                        btn.addEventListener('click', async (e) => {
                            e.stopPropagation();
                            const originalHtml = btn.innerHTML;
                            btn.disabled = true;
                            btn.innerHTML = '<span class="spinner"></span>';
                            try {
                                const result = await api.post(`/downloads/track/${btn.dataset.id}`);
                                if (result && result.status === 'skipped') {
                                    toast(`Already in library or queue`, 'info');
                                    btn.innerHTML = '✓';
                                    btn.title = result.reason || 'Already handled';
                                } else {
                                    toast('Download queued', 'success');
                                    btn.innerHTML = '✓';
                                    btn.title = 'Queued';
                                }
                            } catch (err) {
                                toast(err.message, 'error');
                                btn.innerHTML = originalHtml;
                                btn.disabled = false;
                            }
                        });
                    });
                } catch (err) {
                    trackContainer.innerHTML = `<div style="padding:8px;color:var(--red)">${err.message}</div>`;
                }
            });
        });

        // Download all button
        container.querySelectorAll('.dl-all-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const card = btn.closest('.lib-card');
                const type = card.dataset.type;
                const id = card.dataset.id;
                try {
                    if (type === 'track') {
                        await api.post(`/downloads/track/${id}`);
                    } else if (type === 'playlist') {
                        await api.post(`/downloads/playlist/${id}`);
                    }
                    toast('Download queued', 'success');
                } catch (err) { toast(err.message, 'error'); }
            });
        });

        // Sync toggle button
        container.querySelectorAll('.sync-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const card = btn.closest('.lib-card');
                const type = card.dataset.type;
                const id = card.dataset.id;
                const name = card.dataset.name;
                try {
                    await api.post('/sync/items', { spotify_id: id, item_type: type, name: name });
                    btn.style.color = 'var(--green)';
                    toast(`Auto-sync enabled for "${name}"`, 'success');
                } catch (err) { toast(err.message, 'error'); }
            });
        });

        // Delete track button (local view)
        container.querySelectorAll('.btn-del-track').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (!confirm('Delete this track from library?')) return;
                try {
                    await api.del(`/library/tracks/${btn.dataset.id}`);
                    btn.closest('.dl-item')?.remove();
                    toast('Track deleted', 'success');
                } catch (err) { toast(err.message, 'error'); }
            });
        });
    }

    function renderPagination(container, total, currentOffset) {
        if (!total || total <= limit) return;
        const pages = Math.ceil(total / limit);
        const current = Math.floor(currentOffset / limit);
        let html = '';
        if (current > 0) html += `<button class="btn btn-sm page-btn" data-offset="${(current - 1) * limit}">&larr;</button>`;
        html += `<span class="page-info">${current + 1} / ${pages}</span>`;
        if (current < pages - 1) html += `<button class="btn btn-sm page-btn" data-offset="${(current + 1) * limit}">&rarr;</button>`;
        container.innerHTML = html;
        container.querySelectorAll('.page-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                offset = parseInt(btn.dataset.offset);
                load();
            });
        });
    }

    return { init, load };
})();
