// ─── Dashboard Tab ───────────────────────────────────────────────
const Dashboard = (() => {
    let scanPollInterval = null;

    function init() {
        document.getElementById('scan-btn').addEventListener('click', startScan);
    }

    async function load() {
        try {
            const [stats, syncStatus, scanStatus, scanProg] = await Promise.all([
                api.get('/stats'),
                api.get('/sync/status'),
                api.get('/library/scan/status'),
                api.get('/library/scan/progress'),
            ]);

            renderOverview(stats);
            renderFormats(stats.format_breakdown);
            renderSync(stats, syncStatus);
            renderScan(scanStatus, scanProg);
            loadActivity();

            // Check for active scan
            if (scanStatus.status === 'running') {
                renderScanProgress(scanProg);
                startScanProgressPolling();
            }
        } catch (err) {
            document.getElementById('dash-overview-body').innerHTML =
                `<div style="color:var(--red)">${err.message}</div>`;
        }
    }

    function renderOverview(stats) {
        const el = document.getElementById('dash-overview-body');
        let html = `
            <div class="dash-stat"><span>Total Tracks</span><span class="dash-stat-value">${stats.total_tracks.toLocaleString()}</span></div>
            <div class="dash-stat"><span>Library Size</span><span class="dash-stat-value">${stats.total_size_gb} GB</span></div>
            <div class="dash-stat"><span>Pending Downloads</span><span class="dash-stat-value">${stats.pending_downloads}</span></div>
            <div class="dash-stat"><span>Failed Downloads</span><span class="dash-stat-value" style="color:${stats.failed_downloads > 0 ? 'var(--red)' : ''}">${stats.failed_downloads}</span></div>
            <div class="dash-stat"><span>Pending Duplicates</span><span class="dash-stat-value">${stats.pending_duplicates}</span></div>
            <div class="dash-stat"><span>Spotizerr</span><span class="dash-stat-value" style="color:${stats.spotizerr_reachable ? 'var(--green)' : 'var(--red)'}">${stats.spotizerr_reachable ? 'Connected' : 'Unreachable'}</span></div>
            <div class="dash-stat"><span>Spotify</span><span class="dash-stat-value" style="color:${stats.spotify_connected ? 'var(--green)' : 'var(--red)'}">${stats.spotify_connected ? 'Connected' : 'Disconnected'}</span></div>
        `;

        // Failed imports warning
        const fi = stats.failed_imports;
        if (fi && fi.exists && fi.file_count > 0) {
            html += `<div class="failed-imports-warning">
                <div class="dash-stat">
                    <span style="color:var(--orange)">Failed Imports</span>
                    <span class="dash-stat-value" style="color:var(--orange)">${fi.file_count.toLocaleString()} files (${fi.size_gb} GB)</span>
                </div>
                <div style="font-size:.75rem;color:var(--text-dim);margin:4px 0 6px">
                    Spotizerr failed downloads — wasting disk space. Auto-cleaned every 6h.
                </div>
                <button class="btn btn-sm btn-danger" id="clean-failed-imports">Delete All Now</button>
            </div>`;
        }

        el.innerHTML = html;

        // Attach clean button handler
        const cleanBtn = document.getElementById('clean-failed-imports');
        if (cleanBtn) {
            cleanBtn.addEventListener('click', async () => {
                if (!confirm(`Delete ${fi.file_count.toLocaleString()} failed import files (${fi.size_gb} GB)? This cannot be undone.`)) return;
                cleanBtn.disabled = true;
                cleanBtn.textContent = 'Cleaning...';
                try {
                    const result = await api.post('/library/failed-imports/clean');
                    toast(`Cleaned ${result.cleaned} files (${result.size_gb} GB)`, 'success');
                    load();
                } catch (err) { toast(err.message, 'error'); }
            });
        }
    }

    function renderFormats(breakdown) {
        const el = document.getElementById('dash-formats-body');
        if (!breakdown || !Object.keys(breakdown).length) {
            el.innerHTML = '<div style="color:var(--text-muted)">No tracks scanned yet</div>';
            return;
        }
        const total = Object.values(breakdown).reduce((a, b) => a + b, 0);
        const colors = { FLAC: '#58a6ff', MP3: '#3fb950', M4A: '#d29922', OGG: '#bc8cff', OPUS: '#f78166', WAV: '#8b949e' };

        el.innerHTML = Object.entries(breakdown)
            .sort((a, b) => b[1] - a[1])
            .map(([fmt, count]) => {
                const pct = Math.round(count / total * 100);
                const color = colors[fmt] || 'var(--accent)';
                return `<div class="dash-bar">
                    <span class="dash-bar-label">${fmt}</span>
                    <div class="dash-bar-track"><div class="dash-bar-fill" style="width:${pct}%;background:${color}"></div></div>
                    <span style="font-size:.8rem;color:var(--text-dim);width:60px;text-align:right">${count} (${pct}%)</span>
                </div>`;
            }).join('');
    }

    function renderSync(stats, syncStatus) {
        const el = document.getElementById('dash-sync-body');
        el.innerHTML = `
            <div class="dash-stat"><span>Sync Items</span><span class="dash-stat-value">${stats.sync_items}</span></div>
            <div class="dash-stat"><span>Status</span><span class="dash-stat-value">${syncStatus.running ? 'Running...' : 'Idle'}</span></div>
            <div class="dash-stat"><span>Next Run</span><span class="dash-stat-value" style="font-size:.8rem">${syncStatus.next_run ? new Date(syncStatus.next_run).toLocaleTimeString() : '—'}</span></div>
        `;
    }

    function renderScan(scan, progress) {
        const el = document.getElementById('dash-scan-body');
        const btn = document.getElementById('scan-btn');

        if (scan.status === 'idle') {
            el.innerHTML = '<div style="color:var(--text-muted)">No scans yet — click Scan Now to index your library</div>';
            btn.disabled = false;
            btn.textContent = 'Scan Now';
            return;
        }

        const isRunning = scan.status === 'running';

        // Build status label with phase detail
        let statusLabel = scan.status;
        let statusColor = '';
        if (isRunning && progress) {
            const phaseLabels = {
                walking: 'Counting files...',
                indexing: 'Reading tags...',
                dedup: 'Detecting duplicates...',
            };
            statusLabel = phaseLabels[progress.phase] || 'Running...';
            statusColor = 'var(--orange)';
        } else if (scan.status === 'completed') {
            statusColor = 'var(--green)';
        } else if (scan.status === 'failed' || scan.status === 'interrupted') {
            statusColor = 'var(--red)';
        }

        let html = `<div class="dash-stat"><span>Status</span><span class="dash-stat-value" style="color:${statusColor}">${statusLabel}</span></div>`;

        // If running, show live progress detail
        if (isRunning && progress && progress.phase !== 'idle') {
            if (progress.phase === 'indexing' && progress.total_files > 0) {
                const pct = (progress.processed / progress.total_files * 100).toFixed(1);
                html += `<div class="dash-stat"><span>Progress</span><span class="dash-stat-value">${progress.processed.toLocaleString()} / ${progress.total_files.toLocaleString()} (${pct}%)</span></div>`;
            }
            if (progress.eta_seconds != null && progress.eta_seconds > 0) {
                const mins = Math.ceil(progress.eta_seconds / 60);
                html += `<div class="dash-stat"><span>ETA</span><span class="dash-stat-value" style="color:var(--text-dim)">~${mins} min</span></div>`;
            }
        }

        // Completed scan stats
        if (!isRunning) {
            html += `
                <div class="dash-stat"><span>Tracks Found</span><span class="dash-stat-value">${scan.tracks_found.toLocaleString()}</span></div>
                <div class="dash-stat"><span>Added</span><span class="dash-stat-value">${scan.tracks_added}</span></div>
                <div class="dash-stat"><span>Updated</span><span class="dash-stat-value">${scan.tracks_updated}</span></div>
                <div class="dash-stat"><span>Removed</span><span class="dash-stat-value">${scan.tracks_removed}</span></div>
                <div class="dash-stat"><span>Duplicates</span><span class="dash-stat-value">${scan.duplicates_found}</span></div>
            `;
            if (scan.completed_at) {
                html += `<div class="dash-stat"><span>Completed</span><span style="font-size:.8rem;color:var(--text-dim)">${new Date(scan.completed_at).toLocaleString()}</span></div>`;
            }
        }

        if (scan.error_message) {
            html += `<div style="color:var(--red);font-size:.8rem;margin-top:4px">${scan.error_message}</div>`;
        }

        el.innerHTML = html;

        // Update button state
        btn.disabled = isRunning;
        btn.textContent = isRunning ? 'Scanning...' : 'Scan Now';
    }

    function renderScanProgress(progress) {
        const container = document.getElementById('scan-progress-container');
        if (progress.phase === 'idle' || progress.phase === 'complete') {
            container.innerHTML = '';
            return;
        }

        const phases = ['walking', 'indexing', 'dedup'];
        const phaseLabels = ['Counting', 'Indexing', 'Dedup'];
        const phaseIndex = phases.indexOf(progress.phase);

        let detailText = '';
        if (progress.phase === 'walking') {
            detailText = 'Scanning directory tree...';
        } else if (progress.phase === 'indexing' && progress.total_files > 0) {
            const pct = (progress.processed / progress.total_files * 100).toFixed(1);
            let eta = '';
            if (progress.eta_seconds != null && progress.eta_seconds > 0) {
                const mins = Math.ceil(progress.eta_seconds / 60);
                eta = mins > 1 ? ` — ~${mins} min remaining` : ' — ~1 min remaining';
            }
            detailText = `${progress.processed.toLocaleString()} / ${progress.total_files.toLocaleString()} tracks (${pct}%)${eta}`;
        } else if (progress.phase === 'dedup') {
            detailText = 'Comparing tracks for duplicates...';
        }

        container.innerHTML = `<div class="scan-progress">
            <div class="scan-progress-phases">
                ${phases.map((p, i) => {
                    let cls = 'scan-phase';
                    if (i < phaseIndex) cls += ` ${p}`;
                    else if (i === phaseIndex) cls += ` ${p} active`;
                    return `<div class="${cls}"></div>`;
                }).join('')}
            </div>
            <div class="scan-progress-labels">
                ${phaseLabels.map((label, i) => {
                    const active = i === phaseIndex;
                    const done = i < phaseIndex;
                    const style = active ? 'color:var(--text);font-weight:600' : done ? 'color:var(--green)' : '';
                    return `<span style="${style}">${done ? '✓ ' : ''}${label}</span>`;
                }).join('')}
            </div>
            ${detailText ? `<div class="scan-progress-eta">${detailText}</div>` : ''}
        </div>`;
    }

    function startScanProgressPolling() {
        if (scanPollInterval) return;
        scanPollInterval = setInterval(async () => {
            try {
                const [scanStatus, progress] = await Promise.all([
                    api.get('/library/scan/status'),
                    api.get('/library/scan/progress'),
                ]);

                renderScanProgress(progress);
                renderScan(scanStatus, progress);

                if (scanStatus.status !== 'running') {
                    clearInterval(scanPollInterval);
                    scanPollInterval = null;
                    document.getElementById('scan-progress-container').innerHTML = '';
                    document.getElementById('scan-btn').disabled = false;
                    document.getElementById('scan-btn').textContent = 'Scan Now';
                    toast('Scan complete', 'success');
                    load();
                }
            } catch { /* ignore */ }
        }, 2000);
    }

    async function startScan() {
        try {
            await api.post('/library/scan');
            toast('Library scan started', 'info');
            document.getElementById('scan-btn').disabled = true;
            document.getElementById('scan-btn').textContent = 'Scanning...';
            startScanProgressPolling();
        } catch (err) { toast(err.message, 'error'); }
    }

    async function loadActivity() {
        const el = document.getElementById('dash-activity-body');
        try {
            const data = await api.get('/activity?limit=20');
            if (!data.length) {
                el.innerHTML = '<div style="color:var(--text-muted)">No activity yet</div>';
                return;
            }
            el.innerHTML = data.map(a => {
                let iconClass = 'info';
                let icon = 'ℹ';
                if (a.action.includes('completed') || a.action.includes('complete')) { iconClass = 'success'; icon = '✓'; }
                else if (a.action.includes('failed') || a.action.includes('error')) { iconClass = 'error'; icon = '✗'; }
                else if (a.action.includes('started')) { iconClass = 'info'; icon = '▸'; }

                return `<div class="activity-item">
                    <span class="activity-icon ${iconClass}">${icon}</span>
                    <div class="activity-body">
                        <div class="activity-action">${a.action.replace(/_/g, ' ')}</div>
                        ${a.detail ? `<div class="activity-detail">${a.detail}</div>` : ''}
                    </div>
                    <span class="activity-time">${timeAgo(a.created_at)}</span>
                </div>`;
            }).join('');
        } catch {
            el.innerHTML = '<div style="color:var(--text-muted)">Could not load activity</div>';
        }
    }

    return { init, load };
})();
