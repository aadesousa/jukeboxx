// ─── Downloads Tab ───────────────────────────────────────────────
const Downloads = (() => {
    let pollInterval = null;
    let sseSource = null;
    let statsInterval = null;
    let countdownInterval = null;
    let _lastStats = null;
    let _statsRefreshPending = false;
    let _libraryReady = true;

    function init() {
        document.getElementById('clear-completed').addEventListener('click', clearCompleted);
        document.getElementById('retry-all-failed').addEventListener('click', retryAllFailed);
        YouTube.init();
    }

    async function load() {
        await Promise.all([loadActive(), loadFailed(), loadHistory(), loadQueueStats()]);
        YouTube.checkStatus();
        YouTube.loadHistory();
        connectSSE();
        updateBadge();
        statsInterval = setInterval(loadQueueStats, 15000);
    }

    function unload() {
        stopPolling();
        disconnectSSE();
        if (statsInterval) { clearInterval(statsInterval); statsInterval = null; }
        if (countdownInterval) { clearInterval(countdownInterval); countdownInterval = null; }
        _lastStats = null;
        _statsRefreshPending = false;
    }

    function setLibraryReady(ready, reason, phase) {
        _libraryReady = ready;
        const banner = document.getElementById('downloads-ready-banner');
        if (!ready && reason) {
            const isActive = phase && !['never_scanned', 'incomplete', 'idle'].includes(phase);
            const icon = isActive
                ? '<span class="spinner"></span>'
                : '<svg class="icon" viewBox="0 0 16 16" width="16" height="16" style="flex-shrink:0"><path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm9 3a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM8 4a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 8 4Z"/></svg>';
            banner.innerHTML = `<div class="library-banner">${icon} ${reason}</div>`;
        } else {
            banner.innerHTML = '';
        }
    }

    // ── Queue Stats & Pipeline Panel ───────────────────────────────

    async function loadQueueStats() {
        const container = document.getElementById('downloads-queue-health');
        if (!container) return;
        try {
            const stats = await api.get('/downloads/queue-stats');
            _lastStats = stats;
            container.innerHTML = renderQueueHealth(stats);
            // Wire up inline dispatch button
            const btn = document.getElementById('dl-dispatch-now-btn');
            if (btn) btn.addEventListener('click', dispatchNow);
            // Restart live countdown
            startCountdown();
        } catch {
            if (!_lastStats) {
                container.innerHTML = `<div class="dl-pipeline-error">Queue stats unavailable</div>`;
            }
        }
    }

    function startCountdown() {
        if (countdownInterval) { clearInterval(countdownInterval); countdownInterval = null; }
        if (!_lastStats || !_lastStats.next_dispatch) return;

        countdownInterval = setInterval(() => {
            const el = document.getElementById('dl-countdown-val');
            if (!el) { clearInterval(countdownInterval); countdownInterval = null; return; }
            const next = new Date(_lastStats.next_dispatch);
            const secsLeft = Math.max(0, Math.round((next - Date.now()) / 1000));
            const mins = Math.floor(secsLeft / 60);
            const secs = secsLeft % 60;
            el.textContent = mins > 0
                ? `${mins}m ${secs.toString().padStart(2, '0')}s`
                : `${secs}s`;
            if (secsLeft === 0) {
                clearInterval(countdownInterval);
                countdownInterval = null;
                el.textContent = 'now…';
                setTimeout(loadQueueStats, 4000);
            }
        }, 1000);
    }

    // Throttle SSE-triggered stat refreshes to at most once per 3s
    function throttledStatsRefresh() {
        if (_statsRefreshPending) return;
        _statsRefreshPending = true;
        setTimeout(() => {
            _statsRefreshPending = false;
            loadQueueStats();
            loadActive();
            updateBadge();
        }, 3000);
    }

    function renderQueueHealth(stats) {
        const sp = stats.spotizerr || {};
        const counts = stats.counts || {};

        const reachable = sp.reachable !== false;
        const downloading = counts['downloading'] || 0;
        const pending = counts['pending'] || 0;
        const failed = counts['failed'] || 0;
        const cooling = stats.cooling || 0;
        const stuck = stats.stuck_downloading || 0;
        const recentDone = stats.recent_completed_1h || 0;
        const totalAll = stats.total_all || 0;
        const completedTotal = stats.completed_total || counts['completed'] || 0;

        // Health dot
        let dotClass = 'ok';
        if (!reachable) dotClass = 'error';
        else if (stuck > 5 || failed > 200) dotClass = 'warn';

        // Overall progress bar
        const overallPct = totalAll > 0 ? Math.round((completedTotal / totalAll) * 100) : 0;
        const overallBar = totalAll > 0 ? `
            <div class="dl-overall-progress">
                <div class="dl-overall-header">
                    <span class="dl-overall-label">${completedTotal.toLocaleString()} of ${totalAll.toLocaleString()} tracks downloaded</span>
                    <span class="dl-overall-pct">${overallPct}%</span>
                </div>
                <div class="dl-overall-bar-track">
                    <div class="dl-overall-bar-fill" style="width:${overallPct}%"></div>
                </div>
            </div>` : '';

        // Queue status pills
        const statusParts = [];
        if (downloading > 0) statusParts.push(`<span class="dl-pill downloading">${downloading} downloading</span>`);
        if (pending > 0) statusParts.push(`<span class="dl-pill pending">${pending} queued</span>`);
        if (cooling > 0) statusParts.push(`<span class="dl-pill cooling">${cooling} cooling off</span>`);
        if (failed > 0) statusParts.push(`<span class="dl-pill failed">${failed} failed</span>`);
        if (stuck > 0) statusParts.push(`<span class="dl-pill stuck">⚠ ${stuck} stuck</span>`);
        const statusRow = statusParts.length
            ? statusParts.join('')
            : `<span class="dl-pill neutral">Queue empty</span>`;

        const recentDoneHtml = recentDone > 0
            ? `<span class="dl-recent-inline">✓ ${recentDone} done this hour</span>` : '';

        const unreachableHtml = !reachable
            ? `<div class="dl-unreachable-banner">⚠ Download service unreachable — check Spotizerr</div>` : '';

        // Live countdown
        let countdownHtml = '';
        if (stats.next_dispatch) {
            try {
                const next = new Date(stats.next_dispatch);
                const secsLeft = Math.max(0, Math.round((next - Date.now()) / 1000));
                const mins = Math.floor(secsLeft / 60);
                const secs = secsLeft % 60;
                const display = mins > 0 ? `${mins}m ${secs.toString().padStart(2, '0')}s` : `${secs}s`;
                countdownHtml = `<span class="dl-countdown">Next batch in <strong id="dl-countdown-val">${display}</strong></span>`;
            } catch {}
        }

        return `
            <div class="dl-pipeline">
                <div class="dl-pipeline-header">
                    <span class="dl-pipeline-title">
                        <span class="dl-pipeline-status-dot ${dotClass}"></span>
                        Download Queue
                    </span>
                    <div class="dl-pipeline-header-right">
                        ${countdownHtml}
                        <button class="btn btn-sm" id="dl-dispatch-now-btn">Dispatch Now</button>
                    </div>
                </div>
                ${unreachableHtml}
                ${overallBar}
                <div class="dl-status-row">
                    ${statusRow}
                    ${recentDoneHtml}
                </div>
            </div>`;
    }

    async function dispatchNow() {
        const btn = document.getElementById('dl-dispatch-now-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Dispatching…'; }
        try {
            await api.post('/downloads/dispatch-now');
            toast('Dispatch triggered', 'info');
            setTimeout(() => { loadQueueStats(); loadActive(); }, 3000);
        } catch (err) {
            toast(err.message || 'Dispatch failed', 'error');
        }
        if (btn) { btn.disabled = false; btn.textContent = 'Dispatch Now'; }
    }

    // ── SSE & Polling ──────────────────────────────────────────────

    function connectSSE() {
        disconnectSSE();
        try {
            sseSource = api.sse('/downloads/stream');
            sseSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.spotify_id) {
                        updateDownloadItem(data);
                        if (data.status === 'completed' || data.status === 'failed') {
                            throttledStatsRefresh();
                        }
                    }
                } catch { /* ignore parse errors */ }
            };
            sseSource.onerror = () => {
                disconnectSSE();
                startPolling();
            };
        } catch {
            startPolling();
        }
    }

    function disconnectSSE() {
        if (sseSource) { sseSource.close(); sseSource = null; }
    }

    function updateDownloadItem(data) {
        // Match by data-spotify-id attribute (reliable) or fall back to title
        let item = null;
        if (data.spotify_id) {
            item = document.querySelector(`.dl-item[data-spotify-id="${data.spotify_id}"]`);
        }
        if (!item && data.title) {
            for (const el of document.querySelectorAll('#active-list .dl-item, #failed-list .dl-item')) {
                if (el.querySelector('.dl-title')?.textContent === data.title) { item = el; break; }
            }
        }
        if (!item) return;

        if (data.status) {
            const statusEl = item.querySelector('.dl-status');
            if (statusEl) {
                statusEl.className = `dl-status ${data.status}`;
                statusEl.textContent = data.status;
            }
        }
        if (data.progress !== undefined) {
            let prog = item.querySelector('.dl-progress');
            if (!prog) {
                prog = document.createElement('div');
                prog.className = 'dl-progress';
                prog.innerHTML = '<div class="dl-progress-fill"></div>';
                item.querySelector('.dl-meta')?.before(prog);
            }
            prog.querySelector('.dl-progress-fill').style.width = `${data.progress}%`;
        }
    }

    function startPolling() {
        stopPolling();
        pollInterval = setInterval(async () => {
            await loadActive();
            await loadFailed();
            updateBadge();
        }, 5000);
    }

    function stopPolling() {
        if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
    }

    // ── List Loaders ───────────────────────────────────────────────

    async function loadActive() {
        const container = document.getElementById('active-list');
        const header = document.querySelector('#downloads-active h3');
        try {
            const data = await api.get('/downloads/active');
            const queued = data.queued || [];
            header.textContent = queued.length > 0 ? `Active (${queued.length})` : 'Active';
            if (!queued.length) {
                container.innerHTML = '<div class="dl-empty">No active downloads</div>';
                return;
            }
            // Sort: actively downloading first, then pending
            queued.sort((a, b) => {
                if (a.status === 'downloading' && b.status !== 'downloading') return -1;
                if (b.status === 'downloading' && a.status !== 'downloading') return 1;
                return 0;
            });
            container.innerHTML = queued.map(dl => dlItem(dl)).join('');
            attachDlHandlers(container);
        } catch (err) {
            container.innerHTML = `<div class="dl-empty" style="color:var(--red)">${err.message}</div>`;
        }
    }

    async function loadFailed() {
        const container = document.getElementById('failed-list');
        const header = document.querySelector('#downloads-failed h3');
        try {
            const data = await api.get('/downloads/failed');
            header.textContent = data.length > 0 ? `Failed (${data.length})` : 'Failed';
            if (!data.length) {
                container.innerHTML = '<div class="dl-empty">No failed downloads</div>';
                return;
            }
            container.innerHTML = data.map(dl => dlItem(dl)).join('');
            attachDlHandlers(container);
        } catch {
            container.innerHTML = '';
        }
    }

    async function loadHistory() {
        const container = document.getElementById('history-list');
        const header = document.querySelector('#downloads-history h3');
        try {
            const data = await api.get('/downloads/history?limit=30');
            const completed = data.filter(d => d.status === 'completed');
            header.textContent = completed.length > 0 ? `History (${completed.length})` : 'History';
            if (!completed.length) {
                container.innerHTML = '<div class="dl-empty">No download history</div>';
                return;
            }
            container.innerHTML = completed.slice(0, 20).map(dl => dlItem(dl)).join('');
            attachDlHandlers(container);
        } catch {
            container.innerHTML = '';
        }
    }

    // ── Item Rendering ─────────────────────────────────────────────

    function dlCoolingTime(dl) {
        if (dl.status !== 'cooling' || !dl.updated_at) return '';
        try {
            const retryAt = new Date(dl.updated_at);
            retryAt.setHours(retryAt.getHours() + 6);
            const msLeft = retryAt - Date.now();
            if (msLeft <= 0) return '';
            const hLeft = Math.floor(msLeft / 3600000);
            const mLeft = Math.floor((msLeft % 3600000) / 60000);
            return `<span class="dl-cooling-time">retry in ${hLeft > 0 ? hLeft + 'h ' : ''}${mLeft}m</span>`;
        } catch { return ''; }
    }

    const STAGE_LABELS = {
        initializing: 'Starting',
        downloading: 'Downloading audio',
        processing: 'Processing',
        converting: 'Converting',
        tagging: 'Tagging',
        muxing: 'Muxing',
        error: '',
    };

    function dlItem(dl) {
        const title = dl.title || 'Unknown Track';
        const hasNoTitle = !dl.title;
        const actions = [];
        const isDownloading = dl.status === 'downloading';

        if (dl.status === 'failed' || dl.status === 'cooling') {
            actions.push(`<button class="btn btn-sm btn-accent retry-btn" data-id="${dl.id}">Retry</button>`);
        }
        if (dl.status === 'pending' || isDownloading) {
            actions.push(`<button class="btn btn-sm btn-danger cancel-btn" data-id="${dl.id}">Cancel</button>`);
        }
        actions.push(`<button class="btn-icon dismiss-btn" data-id="${dl.id}" title="Dismiss"><svg class="icon" viewBox="0 0 16 16" width="14" height="14"><path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z"/></svg></button>`);

        const retryInfo = (dl.status === 'failed' || dl.status === 'cooling') && dl.retry_count > 0
            ? `<span class="dl-retry-count">${dl.retry_count} retries</span>` : '';

        const updatedAgo = dl.updated_at ? timeAgo(dl.updated_at) : '';

        // Stage badge from live Spotizerr data
        const stageKey = dl.spotizerr_stage || '';
        const stageLabel = stageKey && STAGE_LABELS[stageKey] !== undefined
            ? STAGE_LABELS[stageKey]
            : (stageKey ? stageKey : '');
        const stageBadge = isDownloading && stageLabel
            ? `<span class="dl-stage-badge">${stageLabel}</span>` : '';

        // Indeterminate progress bar for active downloads
        const progressBar = isDownloading
            ? `<div class="dl-progress-indeterminate"><div class="dl-progress-indeterminate-fill"></div></div>` : '';

        return `<div class="dl-item${dl.status === 'failed' ? ' dl-item-failed' : ''}${isDownloading ? ' dl-item-active' : ''}" data-spotify-id="${dl.spotify_id || ''}">
            <div class="dl-info">
                <div class="dl-title">${title}</div>
                <div class="dl-artist">${dl.artist || ''}${dl.album ? ' — ' + dl.album : ''}</div>
                ${hasNoTitle ? `<div class="dl-spotify-id">ID: ${dl.spotify_id}</div>` : ''}
                ${progressBar}
                ${dl.error_message ? `<div class="dl-error-msg"><svg class="icon" viewBox="0 0 16 16" width="12" height="12"><path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm9 3a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM8 4a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 8 4Z"/></svg> ${dl.error_message}</div>` : ''}
            </div>
            <div class="dl-meta">
                <span class="dl-status ${dl.status}">${dl.status}</span>
                ${stageBadge}
                ${dl.source === 'auto_sync' ? '<span class="dl-source-badge">auto</span>' : ''}
                ${retryInfo}
                ${dlCoolingTime(dl)}
                ${updatedAgo ? `<span class="dl-time">${updatedAgo}</span>` : ''}
            </div>
            <div class="dl-actions">${actions.join('')}</div>
        </div>`;
    }

    function attachDlHandlers(container) {
        container.querySelectorAll('.retry-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                try {
                    await api.post(`/downloads/${btn.dataset.id}/retry`);
                    toast('Retrying download', 'info');
                    load();
                } catch (err) { toast(err.message, 'error'); }
            });
        });
        container.querySelectorAll('.cancel-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                try {
                    await api.post(`/downloads/${btn.dataset.id}/cancel`);
                    toast('Download cancelled', 'info');
                    load();
                } catch (err) { toast(err.message, 'error'); }
            });
        });
        container.querySelectorAll('.dismiss-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                try {
                    await api.del(`/downloads/${btn.dataset.id}`);
                    const item = btn.closest('.dl-item');
                    if (item) {
                        item.style.opacity = '0';
                        item.style.transform = 'translateX(20px)';
                        item.style.transition = 'all .2s';
                        setTimeout(() => { item.remove(); updateBadge(); }, 200);
                    }
                } catch (err) { toast(err.message, 'error'); }
            });
        });
    }

    // ── Bulk Actions ───────────────────────────────────────────────

    async function retryAllFailed() {
        const btn = document.getElementById('retry-all-failed');
        btn.disabled = true;
        btn.textContent = 'Retrying…';
        try {
            const result = await api.post('/downloads/retry-all-failed');
            toast(`Retried ${result.retried} downloads${result.errors ? `, ${result.errors} skipped` : ''}`, 'success');
            load();
        } catch (err) {
            toast(err.message, 'error');
        }
        btn.disabled = false;
        btn.textContent = 'Retry All Failed';
    }

    async function clearCompleted() {
        try {
            const data = await api.get('/downloads/history?limit=200');
            const completed = data.filter(d => d.status === 'completed');
            for (const dl of completed) {
                await api.del(`/downloads/${dl.id}`);
            }
            toast(`Cleared ${completed.length} completed downloads`, 'success');
            load();
        } catch (err) { toast(err.message, 'error'); }
    }

    async function updateBadge() {
        const badge = document.getElementById('downloads-badge');
        try {
            const data = await api.get('/downloads/failed');
            if (data.length > 0) {
                badge.textContent = data.length;
                badge.hidden = false;
            } else {
                badge.hidden = true;
            }
        } catch {
            badge.hidden = true;
        }
    }

    return { init, load, unload, updateBadge, setLibraryReady };
})();
