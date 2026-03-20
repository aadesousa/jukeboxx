// ─── Calendar Page ────────────────────────────────────────────────
const CalendarPage = (() => {
    const root = () => document.getElementById('page-root');
    const MONTHS = ['January','February','March','April','May','June',
                    'July','August','September','October','November','December'];
    const DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

    let viewYear  = new Date().getFullYear();
    let viewMonth = new Date().getMonth() + 1; // 1-based
    let releases  = [];

    // ── Status color ─────────────────────────────────────────────
    function statusColor(status) {
        switch(status) {
            case 'have':     return '#5cb85c';
            case 'wanted':   return 'var(--accent)';
            case 'ignored':  return 'var(--text-muted)';
            default:         return 'var(--orange)';
        }
    }

    function statusLabel(status) {
        switch(status) {
            case 'have':     return 'Have';
            case 'wanted':   return 'Wanted';
            case 'ignored':  return 'Ignored';
            default:         return status || 'Missing';
        }
    }

    // ── Entry point ───────────────────────────────────────────────
    function load(params) {
        const today = new Date();
        viewYear  = today.getFullYear();
        viewMonth = today.getMonth() + 1;

        root().innerHTML = `
            <div class="page-header">
                <div class="page-header-left">
                    <h1 class="page-title">Calendar</h1>
                    <div class="page-subtitle" id="cal-subtitle">Upcoming & recent releases</div>
                </div>
                <div class="page-header-right" style="display:flex;align-items:center;gap:8px">
                    <button class="btn btn-sm" id="btn-cal-prev">◀</button>
                    <span id="cal-month-label" style="font-size:.95rem;font-weight:600;min-width:130px;text-align:center"></span>
                    <button class="btn btn-sm" id="btn-cal-next">▶</button>
                    <button class="btn btn-sm" id="btn-cal-today">Today</button>
                </div>
            </div>

            <div id="cal-body">
                <div class="loading-spinner" style="padding:40px 0;text-align:center">Loading releases…</div>
            </div>

            <div id="cal-upcoming-section" style="margin-top:32px"></div>`;

        document.getElementById('btn-cal-prev').addEventListener('click', () => {
            if (viewMonth === 1) { viewMonth = 12; viewYear--; }
            else viewMonth--;
            fetchAndRender();
        });
        document.getElementById('btn-cal-next').addEventListener('click', () => {
            if (viewMonth === 12) { viewMonth = 1; viewYear++; }
            else viewMonth++;
            fetchAndRender();
        });
        document.getElementById('btn-cal-today').addEventListener('click', () => {
            const now = new Date();
            viewYear  = now.getFullYear();
            viewMonth = now.getMonth() + 1;
            fetchAndRender();
        });

        fetchAndRender();
    }

    function unload() {}

    // ── Fetch & render ────────────────────────────────────────────
    async function fetchAndRender() {
        document.getElementById('cal-month-label').textContent =
            `${MONTHS[viewMonth - 1]} ${viewYear}`;

        try {
            const data = await api.get(`/calendar/releases?year=${viewYear}&month=${viewMonth}`);
            releases = data.releases || [];

            // Subtitle: count for this month
            const thisMonth = releases.filter(r => {
                const d = r.release_date?.slice(0, 7);
                return d === `${viewYear}-${String(viewMonth).padStart(2,'0')}`;
            });
            const sub = document.getElementById('cal-subtitle');
            if (sub) sub.textContent = `${thisMonth.length} release${thisMonth.length !== 1 ? 's' : ''} this month`;

            renderCalendar();
            renderPanels();
        } catch(e) {
            document.getElementById('cal-body').innerHTML =
                `<div class="empty-state" style="padding:40px 0">
                    <div class="empty-state-title">Failed to load releases</div>
                    <div class="empty-state-body">${e.message || 'No monitored artists yet.'}</div>
                </div>`;
        }
    }

    // ── Calendar grid ─────────────────────────────────────────────
    function renderCalendar() {
        const firstDow = new Date(viewYear, viewMonth - 1, 1).getDay(); // 0=Sun
        const daysInMonth = new Date(viewYear, viewMonth, 0).getDate();
        const today = new Date();
        const todayStr = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;

        // Build release map: "YYYY-MM-DD" → [release, ...]
        const byDate = {};
        releases.forEach(r => {
            const dateKey = r.release_date?.slice(0, 10);
            if (!dateKey) return;
            // Only show current month's releases on the grid
            if (!dateKey.startsWith(`${viewYear}-${String(viewMonth).padStart(2,'0')}`)) return;
            if (!byDate[dateKey]) byDate[dateKey] = [];
            byDate[dateKey].push(r);
        });

        // Header row
        let html = `<div class="cal-grid">`;
        DOW.forEach(d => { html += `<div class="cal-header-cell">${d}</div>`; });

        // Empty cells before first day
        for (let i = 0; i < firstDow; i++) {
            html += `<div class="cal-cell cal-cell-empty"></div>`;
        }

        // Day cells
        for (let day = 1; day <= daysInMonth; day++) {
            const dateStr = `${viewYear}-${String(viewMonth).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
            const isToday = dateStr === todayStr;
            const dayReleases = byDate[dateStr] || [];

            html += `<div class="cal-cell${isToday ? ' cal-cell-today' : ''}">
                <div class="cal-day-num${isToday ? ' cal-today-num' : ''}">${day}</div>`;

            if (dayReleases.length > 0) {
                // Show up to 3 dots + overflow
                const dots = dayReleases.slice(0, 3);
                const overflow = dayReleases.length - 3;
                html += `<div class="cal-dots">`;
                dots.forEach(r => {
                    html += `<span class="cal-dot" style="background:${statusColor(r.status)}" title="${esc(r.artist_name)} — ${esc(r.name)}"></span>`;
                });
                if (overflow > 0) {
                    html += `<span style="font-size:9px;color:var(--text-muted)">+${overflow}</span>`;
                }
                html += `</div>`;

                // Release mini-cards (shown below dots, up to 2)
                dayReleases.slice(0, 2).forEach(r => {
                    html += `<div class="cal-release-chip" style="border-left-color:${statusColor(r.status)}" title="${esc(r.name)} by ${esc(r.artist_name)}">
                        <span class="cal-chip-artist">${esc(r.artist_name)}</span>
                        <span class="cal-chip-album">${esc(r.name)}</span>
                    </div>`;
                });
                if (dayReleases.length > 2) {
                    html += `<div style="font-size:10px;color:var(--text-muted);padding:2px 4px">+${dayReleases.length - 2} more</div>`;
                }
            }

            html += `</div>`;
        }

        // Fill remaining cells
        const totalCells = firstDow + daysInMonth;
        const remainder  = totalCells % 7;
        if (remainder > 0) {
            for (let i = 0; i < 7 - remainder; i++) {
                html += `<div class="cal-cell cal-cell-empty"></div>`;
            }
        }
        html += `</div>`;

        document.getElementById('cal-body').innerHTML = html;
    }

    // ── Upcoming / recent panels ──────────────────────────────────
    function renderPanels() {
        const container = document.getElementById('cal-upcoming-section');
        if (!container) return;

        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const todayStr = today.toISOString().slice(0, 10);

        const upcoming = releases.filter(r => r.release_date && r.release_date >= todayStr)
                                 .sort((a, b) => a.release_date.localeCompare(b.release_date))
                                 .slice(0, 20);
        const recent   = releases.filter(r => r.release_date && r.release_date < todayStr)
                                 .sort((a, b) => b.release_date.localeCompare(a.release_date))
                                 .slice(0, 20);

        container.innerHTML = `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px">
                <div>
                    <div class="section-heading">Upcoming Releases</div>
                    ${renderReleaseList(upcoming, true)}
                </div>
                <div>
                    <div class="section-heading">Recent Releases</div>
                    ${renderReleaseList(recent, false)}
                </div>
            </div>`;
    }

    function renderReleaseList(items, upcoming) {
        if (items.length === 0) {
            return `<div style="padding:16px 0;color:var(--text-muted);font-size:13px">
                ${upcoming ? 'No upcoming releases this period.' : 'No recent releases this period.'}
            </div>`;
        }
        return items.map(r => {
            const dateLabel = formatReleaseDate(r.release_date);
            return `<div class="cal-release-row">
                ${r.image_url
                    ? `<img src="${esc(r.image_url)}" class="cal-row-thumb" alt="">`
                    : `<div class="cal-row-thumb cal-row-thumb-ph"></div>`}
                <div class="cal-row-info">
                    <div class="cal-row-album">${esc(r.name)}</div>
                    <div class="cal-row-artist">${esc(r.artist_name || '')}</div>
                    <div class="cal-row-meta">${dateLabel} · ${r.album_type || 'Album'} · ${r.track_count || 0} tracks</div>
                </div>
                <span class="cal-row-status" style="background:${statusColor(r.status)}">${statusLabel(r.status)}</span>
            </div>`;
        }).join('');
    }

    function formatReleaseDate(dateStr) {
        if (!dateStr) return '—';
        try {
            const d = new Date(dateStr + 'T00:00:00');
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        } catch { return dateStr; }
    }

    function esc(s) {
        return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    return { load, unload };
})();
