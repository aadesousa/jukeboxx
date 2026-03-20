// ─── Sync Tab ────────────────────────────────────────────────────
const Sync = (() => {
    let items = [];
    let searchQuery = '';
    let syncPollInterval = null;

    // Frontend cache to avoid API calls on every tab switch
    let cachedItems = null;
    let cacheTime = 0;
    const CACHE_TTL = 30000; // 30 seconds

    function init() {
        document.getElementById('sync-now-btn').addEventListener('click', triggerSync);
        document.getElementById('download-all-missing-btn').addEventListener('click', downloadAllMissing);

        document.getElementById('sync-search').addEventListener('input', debounce((e) => {
            searchQuery = e.target.value.trim().toLowerCase();
            renderItems();
        }, 200));

        document.getElementById('sync-toggle-all').addEventListener('click', toggleAll);
    }

    async function load() {
        const listEl = document.getElementById('sync-items-list');
        const now = Date.now();

        // Use cached data if fresh enough
        if (cachedItems && now - cacheTime < CACHE_TTL) {
            items = cachedItems;
            renderStats();
            renderItems();
            // Still fetch status (lightweight)
            try {
                const syncStatus = await api.get('/sync/status');
                renderStatus(syncStatus);
                if (syncStatus.running) startPolling();
            } catch { /* ignore */ }
            return;
        }

        listEl.innerHTML = '<div class="loading-overlay"><span class="spinner"></span></div>';

        try {
            const [syncItems, syncStatus] = await Promise.all([
                api.get('/sync/items'),
                api.get('/sync/status'),
            ]);
            items = syncItems;
            cachedItems = syncItems;
            cacheTime = Date.now();
            renderStatus(syncStatus);
            renderStats();
            renderItems();

            if (syncStatus.running) startPolling();
        } catch (err) {
            listEl.innerHTML = `<div class="empty-state">${err.message}</div>`;
        }
    }

    function invalidateCache() {
        cachedItems = null;
        cacheTime = 0;
    }

    function renderStatus(status) {
        const pill = document.getElementById('sync-status-pill');
        const text = pill.querySelector('.sync-status-text');
        const nextEl = document.getElementById('sync-next-run');
        const btn = document.getElementById('sync-now-btn');

        if (status.running) {
            pill.className = 'sync-status-pill running';
            text.textContent = 'Syncing...';
            btn.disabled = true;
            btn.textContent = 'Syncing...';
        } else {
            pill.className = 'sync-status-pill idle';
            text.textContent = 'Idle';
            btn.disabled = false;
            btn.textContent = 'Scan Library';
        }

        if (status.next_run) {
            const next = new Date(status.next_run);
            const diff = Math.max(0, Math.round((next - Date.now()) / 60000));
            nextEl.innerHTML = `Next scan in <strong>${diff} min</strong>`;
        } else {
            nextEl.textContent = '';
        }
    }

    function renderStats() {
        const bar = document.getElementById('sync-stats-bar');
        if (!items.length) {
            bar.innerHTML = '';
            return;
        }

        const totalTracks = items.reduce((s, i) => s + (i.track_count || 0), 0);
        const totalLocal = items.reduce((s, i) => s + (i.local_count || 0), 0);
        const totalUnavailable = items.reduce((s, i) => s + (i.unavailable_count || 0), 0);
        const enabledCount = items.filter(i => i.enabled).length;
        const downloadable = totalTracks - totalLocal - totalUnavailable;
        const pct = totalTracks > 0 ? Math.round(totalLocal / totalTracks * 100) : 0;

        bar.innerHTML = `
            <div class="sync-stat">
                <span class="sync-stat-value">${items.length}</span>
                <span class="sync-stat-label">Playlists</span>
            </div>
            <div class="sync-stat">
                <span class="sync-stat-value">${enabledCount}</span>
                <span class="sync-stat-label">Enabled</span>
            </div>
            <div class="sync-stat">
                <span class="sync-stat-value">${totalLocal.toLocaleString()}</span>
                <span class="sync-stat-label">Matched</span>
            </div>
            <div class="sync-stat">
                <span class="sync-stat-value">${totalTracks.toLocaleString()}</span>
                <span class="sync-stat-label">Total</span>
            </div>
            ${totalUnavailable > 0 ? `<div class="sync-stat">
                <span class="sync-stat-value" style="color:var(--text-muted)">${totalUnavailable.toLocaleString()}</span>
                <span class="sync-stat-label">Unavailable</span>
            </div>` : ''}
            <div class="sync-stat highlight">
                <span class="sync-stat-value">${pct}%</span>
                <span class="sync-stat-label">In Library</span>
            </div>
        `;

        // Update badge — show downloadable (missing minus unavailable)
        const badge = document.getElementById('sync-badge');
        if (downloadable > 0) {
            badge.textContent = downloadable > 999 ? '999+' : downloadable;
            badge.hidden = false;
        } else {
            badge.hidden = true;
        }
    }

    function renderItems() {
        const listEl = document.getElementById('sync-items-list');

        let filtered = items;
        if (searchQuery) {
            filtered = filtered.filter(i =>
                (i.name || '').toLowerCase().includes(searchQuery)
            );
        }

        if (!filtered.length) {
            listEl.innerHTML = items.length
                ? '<div class="empty-state">No playlists match your filter</div>'
                : '<div class="empty-state">No playlists synced yet. Enable Account Sync in Settings or add playlists from the Library tab.</div>';
            return;
        }

        // Sort: enabled first, then by name
        filtered.sort((a, b) => {
            if (a.enabled !== b.enabled) return b.enabled - a.enabled;
            return (a.name || '').localeCompare(b.name || '');
        });

        listEl.innerHTML = filtered.map(item => syncItemCard(item)).join('');
        attachHandlers(listEl);
    }

    function syncItemCard(item) {
        const total = item.track_count || 0;
        const matched = item.local_count || 0;
        const unavailable = item.unavailable_count || 0;
        const downloadable = Math.max(0, total - matched - unavailable);
        const pct = total > 0 ? Math.round(matched / total * 100) : 0;
        const isComplete = downloadable === 0 && total > 0;
        const lastSynced = item.last_synced_at ? timeAgo(item.last_synced_at) : 'Never scanned';

        let progressColor = 'var(--accent)';
        if (isComplete) progressColor = 'var(--green)';
        else if (pct > 75) progressColor = 'var(--green)';
        else if (pct > 40) progressColor = 'var(--orange)';

        return `<div class="sync-item ${!item.enabled ? 'disabled' : ''} ${isComplete ? 'complete' : ''}" data-id="${item.id}">
            <div class="sync-item-icon playlist">
                <svg viewBox="0 0 16 16" width="16" height="16"><path d="M1 2.75A.75.75 0 0 1 1.75 2h12.5a.75.75 0 0 1 0 1.5H1.75A.75.75 0 0 1 1 2.75Zm0 5A.75.75 0 0 1 1.75 7H9.5a.75.75 0 0 1 0 1.5H1.75A.75.75 0 0 1 1 7.75ZM1.75 12a.75.75 0 0 0 0 1.5H9.5a.75.75 0 0 0 0-1.5H1.75ZM13 9a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z"/></svg>
            </div>
            <div class="sync-item-info">
                <div class="sync-item-name">${item.name || item.spotify_id}</div>
                <div class="sync-item-meta">
                    <span class="sync-item-last">${lastSynced}</span>
                </div>
            </div>
            <div class="sync-item-progress">
                <div class="sync-item-counts">
                    <span>${matched}<span class="sync-item-sep">/</span>${total} in library</span>
                    ${isComplete
                        ? '<span class="sync-complete-label">Complete</span>'
                        : (downloadable > 0
                            ? `<span class="sync-missing">${downloadable} missing</span>`
                            : '')}
                </div>
                ${unavailable > 0 ? `<div class="sync-unavailable-label">${unavailable} unavailable on Spotify</div>` : ''}
                <div class="sync-progress-bar">
                    <div class="sync-progress-fill" style="width:${pct}%;background:${progressColor}"></div>
                </div>
                <div class="sync-pct">${pct}%</div>
            </div>
            <div class="sync-item-actions">
                ${downloadable > 0 ? `<button class="btn-icon sync-dl-btn" title="Download ${downloadable} missing tracks">
                    <svg class="icon" viewBox="0 0 16 16" width="14" height="14"><path d="M7.47 10.78a.75.75 0 0 0 1.06 0l3.75-3.75a.75.75 0 0 0-1.06-1.06L8.75 8.44V1.75a.75.75 0 0 0-1.5 0v6.69L4.78 5.97a.75.75 0 0 0-1.06 1.06l3.75 3.75ZM3.75 13a.75.75 0 0 0 0 1.5h8.5a.75.75 0 0 0 0-1.5h-8.5Z"/></svg>
                </button>` : ''}
                <label class="sync-toggle" title="${item.enabled ? 'Disable sync' : 'Enable sync'}">
                    <input type="checkbox" class="sync-toggle-input" ${item.enabled ? 'checked' : ''}>
                    <span class="sync-toggle-slider"></span>
                </label>
                <button class="btn-icon sync-remove-btn" title="Remove from sync">
                    <svg class="icon" viewBox="0 0 16 16" width="14" height="14"><path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z"/></svg>
                </button>
            </div>
        </div>`;
    }

    function attachHandlers(container) {
        container.querySelectorAll('.sync-toggle-input').forEach(toggle => {
            toggle.addEventListener('change', async (e) => {
                const card = e.target.closest('.sync-item');
                const id = card.dataset.id;
                const enabled = e.target.checked;
                try {
                    await api.put(`/sync/items/${id}`, { enabled });
                    const item = items.find(i => i.id == id);
                    if (item) item.enabled = enabled ? 1 : 0;
                    card.classList.toggle('disabled', !enabled);
                    renderStats();
                    invalidateCache();
                    toast(enabled ? 'Sync enabled' : 'Sync disabled', 'info');
                } catch (err) {
                    e.target.checked = !enabled;
                    toast(err.message, 'error');
                }
            });
        });

        container.querySelectorAll('.sync-remove-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const card = e.target.closest('.sync-item');
                const id = card.dataset.id;
                const item = items.find(i => i.id == id);
                const name = item?.name || 'this item';
                if (!confirm(`Remove "${name}" from sync? Downloads already completed will not be deleted.`)) return;
                try {
                    await api.del(`/sync/items/${id}`);
                    items = items.filter(i => i.id != id);
                    invalidateCache();
                    card.style.transition = 'opacity .2s, transform .2s';
                    card.style.opacity = '0';
                    card.style.transform = 'translateX(20px)';
                    setTimeout(() => {
                        renderStats();
                        renderItems();
                    }, 200);
                    toast(`Removed "${name}" from sync`, 'info');
                } catch (err) {
                    toast(err.message, 'error');
                }
            });
        });

        container.querySelectorAll('.sync-dl-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const card = e.target.closest('.sync-item');
                const id = card.dataset.id;
                const item = items.find(i => i.id == id);
                const name = item?.name || 'playlist';
                try {
                    btn.innerHTML = '<span class="spinner"></span>';
                    btn.disabled = true;
                    await api.post(`/sync/items/${id}/download-missing`);
                    toast(`Downloading missing tracks for "${name}"`, 'success');
                } catch (err) {
                    toast(err.message, 'error');
                    btn.disabled = false;
                }
            });
        });
    }

    async function triggerSync() {
        const btn = document.getElementById('sync-now-btn');
        btn.disabled = true;
        btn.textContent = 'Scanning...';
        try {
            await api.post('/sync/run');
            toast('Library scan started', 'success');
            const pill = document.getElementById('sync-status-pill');
            pill.className = 'sync-status-pill running';
            pill.querySelector('.sync-status-text').textContent = 'Scanning...';
            invalidateCache();
            startPolling();
        } catch (err) {
            toast(err.message, 'error');
            btn.disabled = false;
            btn.textContent = 'Scan Library';
        }
    }

    async function downloadAllMissing() {
        const btn = document.getElementById('download-all-missing-btn');
        const totalUnavailable = items.reduce((s, i) => s + (i.unavailable_count || 0), 0);
        const totalMissing = items.reduce((s, i) => s + Math.max(0, (i.track_count || 0) - (i.local_count || 0) - (i.unavailable_count || 0)), 0);
        if (totalMissing === 0) {
            toast('All downloadable tracks are already in library', 'info');
            return;
        }
        let msg = `Download ${totalMissing} missing tracks across all playlists?`;
        if (totalUnavailable > 0) {
            msg += `\n(${totalUnavailable} tracks are unavailable on Spotify and will be skipped)`;
        }
        if (!confirm(msg)) return;
        btn.disabled = true;
        btn.textContent = 'Starting...';
        try {
            await api.post('/sync/download-missing');
            toast(`Downloading ${totalMissing} missing tracks`, 'success');
            setTimeout(() => {
                btn.disabled = false;
                btn.textContent = 'Download All Missing';
            }, 3000);
        } catch (err) {
            toast(err.message, 'error');
            btn.disabled = false;
            btn.textContent = 'Download All Missing';
        }
    }

    async function toggleAll() {
        let filtered = items;
        if (searchQuery) {
            filtered = filtered.filter(i =>
                (i.name || '').toLowerCase().includes(searchQuery)
            );
        }

        const anyEnabled = filtered.some(i => i.enabled);
        const newState = !anyEnabled;

        try {
            await Promise.all(filtered.map(i =>
                api.put(`/sync/items/${i.id}`, { enabled: newState })
            ));
            filtered.forEach(i => { i.enabled = newState ? 1 : 0; });
            invalidateCache();
            renderStats();
            renderItems();
            toast(newState ? 'All enabled' : 'All disabled', 'info');
        } catch (err) {
            toast(err.message, 'error');
        }
    }

    function startPolling() {
        if (syncPollInterval) return;
        syncPollInterval = setInterval(async () => {
            try {
                const status = await api.get('/sync/status');
                renderStatus(status);
                if (!status.running) {
                    clearInterval(syncPollInterval);
                    syncPollInterval = null;
                    invalidateCache();
                    const syncItems = await api.get('/sync/items');
                    items = syncItems;
                    cachedItems = syncItems;
                    cacheTime = Date.now();
                    renderStats();
                    renderItems();
                    toast('Sync complete', 'success');
                }
            } catch { /* ignore */ }
        }, 5000);
    }

    function unload() {
        if (syncPollInterval) {
            clearInterval(syncPollInterval);
            syncPollInterval = null;
        }
    }

    return { init, load, unload };
})();
