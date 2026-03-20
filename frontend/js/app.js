// ─── JukeBoxx Client-side App & Router ───────────────────────────

const App = (() => {
    // Route table — order matters, more specific first
    const ROUTES = [
        { re: /^\/artists\/([^/]+)\/albums\/([^/]+)$/, page: 'album-detail',   keys: ['artistId','albumId'] },
        { re: /^\/artists\/([^/]+)$/,                  page: 'artist-detail',  keys: ['id'] },
        { re: /^\/artists\/?$/,                        page: 'artists',        keys: [] },
        { re: /^\/albums\/([^/]+)$/,                   page: 'album-detail',   keys: ['id'] },
        { re: /^\/wanted\/?$/,                         page: 'wanted',         keys: [] },
        { re: /^\/calendar\/?$/,                       page: 'calendar',       keys: [] },
        { re: /^\/activity\/?$/,                       page: 'activity',       keys: [] },
        { re: /^\/playlists\/?$/,                      page: 'playlists',      keys: [] },
        { re: /^\/soundcloud\/?$/,                     page: 'soundcloud',     keys: [] },
        { re: /^\/import\/?$/,                         page: 'import',         keys: [] },
        { re: /^\/library\/?$/,                        page: 'library',        keys: [] },
        { re: /^\/spotizerr\/?$/,                      page: 'spotizerr',      keys: [] },
        { re: /^\/settings(?:\/([^/]*))?$/,            page: 'settings',       keys: ['section'] },
        { re: /^\/logs\/?$/,                           page: 'logs',           keys: [] },
        { re: /^\/?$/,                                 page: 'artists',        keys: [] },
    ];

    // Map page name → module object
    const PAGES = {
        'artists':       typeof ArtistsPage       !== 'undefined' ? ArtistsPage       : null,
        'artist-detail': typeof ArtistDetailPage   !== 'undefined' ? ArtistDetailPage   : null,
        'album-detail':  typeof AlbumDetailPage    !== 'undefined' ? AlbumDetailPage    : null,
        'wanted':        typeof WantedPage         !== 'undefined' ? WantedPage         : null,
        'calendar':      typeof CalendarPage       !== 'undefined' ? CalendarPage       : null,
        'activity':      typeof ActivityPage       !== 'undefined' ? ActivityPage       : null,
        'playlists':     typeof PlaylistsPage      !== 'undefined' ? PlaylistsPage      : null,
        'soundcloud':    typeof SoundCloudPage      !== 'undefined' ? SoundCloudPage      : null,
        'import':        typeof ImportPage         !== 'undefined' ? ImportPage         : null,
        'library':       typeof LibraryPage        !== 'undefined' ? LibraryPage        : null,
        'spotizerr':     typeof SpotizerPage       !== 'undefined' ? SpotizerPage       : null,
        'settings':      typeof SettingsPage       !== 'undefined' ? SettingsPage       : null,
        'logs':          typeof LogsPage           !== 'undefined' ? LogsPage           : null,
    };

    // Which nav item should be active for a given page
    const PAGE_NAV = {
        'artists':       'artists',
        'artist-detail': 'artists',
        'album-detail':  'artists',
        'wanted':        'wanted',
        'calendar':      'calendar',
        'activity':      'activity',
        'playlists':     'playlists',
        'soundcloud':    'soundcloud',
        'import':        'import',
        'library':       'library',
        'spotizerr':     'spotizerr',
        'settings':      'settings',
        'logs':          'logs',
    };

    let currentPage     = null;
    let currentPageName = null;
    let booted          = false;
    let badgeInterval   = null;
    let calendarEnabled = false;

    // ── Bootstrap ─────────────────────────────────────────────────
    async function init() {
        try {
            const auth = await api.get('/auth/status');
            if (!auth.setup_complete) { showSetup(); return; }
            if (!auth.authenticated)  { showLogin();  return; }
            await boot(auth.username);
        } catch {
            showLogin();
        }
    }

    async function boot(username) {
        document.getElementById('auth-overlay').hidden = true;
        document.getElementById('app-shell').hidden    = false;
        document.getElementById('user-btn').hidden     = false;

        if (!booted) {
            setupSidebar();
            setupSearch();
            setupUserBtn(username);
            Notifications.init();
            window.addEventListener('hashchange', handleRoute);
            booted = true;
        }

        await applyCalendarSetting();
        handleRoute();
        startBadgePolling();
        refreshSidebarStats();
    }

    // ── Auth UI ───────────────────────────────────────────────────
    function showLogin() {
        document.getElementById('app-shell').hidden = true;
        document.getElementById('auth-overlay').hidden = false;
        document.getElementById('auth-form').innerHTML = `
            <div id="auth-error" class="auth-error" hidden></div>
            <div class="auth-field">
                <label>Username</label>
                <input class="input" id="login-user" autocomplete="username">
            </div>
            <div class="auth-field">
                <label>Password</label>
                <input class="input" id="login-pass" type="password" autocomplete="current-password">
            </div>
            <button class="btn btn-primary btn-lg auth-submit" id="login-submit">Sign In</button>
        `;
        const submit = async () => {
            const btn  = document.getElementById('login-submit');
            const err  = document.getElementById('auth-error');
            const user = document.getElementById('login-user').value.trim();
            const pass = document.getElementById('login-pass').value;
            err.hidden = true;
            if (!user || !pass) { err.textContent = 'Username and password required.'; err.hidden = false; return; }
            btn.disabled = true; btn.textContent = 'Signing in…';
            try {
                await api.post('/auth/login', { username: user, password: pass });
                boot(user);
            } catch (e) {
                err.textContent = e.message || 'Invalid credentials.';
                err.hidden = false;
                btn.disabled = false; btn.textContent = 'Sign In';
            }
        };
        document.getElementById('login-submit').addEventListener('click', submit);
        document.getElementById('login-pass').addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
        document.getElementById('login-user').focus();
    }

    function showSetup() {
        document.getElementById('app-shell').hidden = true;
        document.getElementById('auth-overlay').hidden = false;
        document.getElementById('auth-form').innerHTML = `
            <p style="font-size:.85rem;color:var(--text-dim);text-align:center;margin-bottom:16px">Create your admin account to get started.</p>
            <div id="auth-error" class="auth-error" hidden></div>
            <div class="auth-field">
                <label>Username</label>
                <input class="input" id="setup-user" autocomplete="username">
            </div>
            <div class="auth-field">
                <label>Password</label>
                <input class="input" id="setup-pass" type="password" autocomplete="new-password">
            </div>
            <button class="btn btn-primary btn-lg auth-submit" id="setup-submit">Create Account</button>
        `;
        const submit = async () => {
            const btn  = document.getElementById('setup-submit');
            const err  = document.getElementById('auth-error');
            const user = document.getElementById('setup-user').value.trim();
            const pass = document.getElementById('setup-pass').value;
            err.hidden = true;
            if (!user || pass.length < 4) { err.textContent = 'Username required, password min 4 chars.'; err.hidden = false; return; }
            btn.disabled = true; btn.textContent = 'Creating…';
            try {
                await api.post('/auth/setup', { username: user, password: pass });
                boot(user);
            } catch (e) {
                err.textContent = e.message || 'Setup failed.';
                err.hidden = false;
                btn.disabled = false; btn.textContent = 'Create Account';
            }
        };
        document.getElementById('setup-submit').addEventListener('click', submit);
        document.getElementById('setup-pass').addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
        document.getElementById('setup-user').focus();
    }

    async function logout() {
        try { await api.post('/auth/logout'); } catch {}
        stopBadgePolling();
        booted = false;
        currentPage = null;
        currentPageName = null;
        showLogin();
    }

    // ── Calendar guard ────────────────────────────────────────────
    async function applyCalendarSetting() {
        try {
            const s = await api.get('/settings');
            calendarEnabled = !!s.calendar_enabled;
        } catch { calendarEnabled = false; }
        const navCal = document.getElementById('nav-calendar');
        if (navCal) navCal.hidden = !calendarEnabled;
    }

    // ── Sidebar ───────────────────────────────────────────────────
    function setupSidebar() {
        const menuBtn = document.getElementById('topbar-menu-btn');
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebar-overlay');

        menuBtn.addEventListener('click', () => {
            sidebar.classList.toggle('mobile-open');
            overlay.classList.toggle('open');
        });
        overlay.addEventListener('click', () => {
            sidebar.classList.remove('mobile-open');
            overlay.classList.remove('open');
        });
    }

    function setActiveNav(pageName) {
        const target = PAGE_NAV[pageName] || pageName;
        document.querySelectorAll('.nav-item[data-route]').forEach(el => {
            el.classList.toggle('active', el.dataset.route === target);
        });
    }

    // ── Global search ─────────────────────────────────────────────
    function setupSearch() {
        const input = document.getElementById('global-search');
        // Shortcut: '/' focuses search
        document.addEventListener('keydown', e => {
            if (e.key === '/' && document.activeElement !== input) {
                e.preventDefault();
                input.focus();
                input.select();
            }
            if (e.key === 'Escape' && document.activeElement === input) {
                input.blur();
                input.value = '';
            }
        });
        // Delegate to current page's search handler
        input.addEventListener('input', () => {
            if (currentPage?.onSearch) currentPage.onSearch(input.value);
        });
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter' && currentPageName !== 'artists') {
                navigate('/artists?q=' + encodeURIComponent(input.value));
            }
        });
    }

    // ── User button ───────────────────────────────────────────────
    function setupUserBtn(username) {
        const btn = document.getElementById('user-btn');
        btn.title = username;
        btn.addEventListener('click', () => {
            if (confirm(`Sign out as ${username}?`)) logout();
        });
    }

    // ── Router ────────────────────────────────────────────────────
    function handleRoute() {
        const raw  = location.hash.slice(1) || '/';
        const path = raw.split('?')[0];
        const qs   = raw.includes('?') ? raw.split('?')[1] : '';

        let matched = null;
        let params  = {};
        for (const route of ROUTES) {
            const m = path.match(route.re);
            if (m) {
                matched = route;
                route.keys.forEach((k, i) => { params[k] = m[i + 1] || ''; });
                break;
            }
        }

        if (!matched) { navigate('/artists'); return; }

        // Guard: calendar disabled — force load artists even if already there
        if (matched.page === 'calendar' && !calendarEnabled) {
            navigate('/artists');
            if (location.hash === '#/artists') { navigate('/'); }
            return;
        }

        // Parse query string into params
        if (qs) {
            new URLSearchParams(qs).forEach((v, k) => { params[k] = v; });
        }

        const PageModule = PAGES[matched.page];
        if (!PageModule) {
            document.getElementById('page-root').innerHTML = buildStub(matched.page);
            setActiveNav(matched.page);
            return;
        }

        // Unload current
        if (currentPage?.unload) currentPage.unload();

        // Close mobile sidebar
        document.getElementById('sidebar').classList.remove('mobile-open');
        document.getElementById('sidebar-overlay').classList.remove('open');

        // Scroll to top
        document.getElementById('page-root').scrollTop = 0;

        // Load new
        currentPage     = PageModule;
        currentPageName = matched.page;
        currentPage.load(params);
        setActiveNav(matched.page);
    }

    function navigate(path) {
        location.hash = '#' + path;
    }

    // ── Badges & stats polling ────────────────────────────────────
    function startBadgePolling() {
        stopBadgePolling();
        updateBadges();
        badgeInterval = setInterval(updateBadges, 30000);
    }
    function stopBadgePolling() {
        if (badgeInterval) { clearInterval(badgeInterval); badgeInterval = null; }
    }

    async function updateBadges() {
        // Wanted count
        try {
            const data = await api.get('/wanted/missing');
            const count = (data.missing_albums || 0) + (data.missing_tracks || 0);
            setBadge('nav-wanted-badge', count);
        } catch {}

        // Queue count
        try {
            const data = await api.get('/downloads/queue-stats');
            const active = (data.active || 0) + (data.queued || 0);
            setBadge('nav-queue-badge', active);
        } catch {}

        // Spotify status
        try {
            const data = await api.get('/spotify/status');
            const dot = document.getElementById('spotify-dot');
            dot.classList.toggle('connected', !!data.connected);
            dot.title = data.connected ? 'Spotify connected' : 'Spotify disconnected';
        } catch {}
    }

    function setBadge(id, count) {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = count > 999999 ? '999999+' : count;
        el.hidden = count === 0;
    }

    async function refreshSidebarStats() {
        try {
            const stats = await api.get('/stats');
            const el = document.getElementById('sidebar-stats');
            el.innerHTML = [
                ['Artists',  stats.total_artists  || 0],
                ['Albums',   stats.total_albums   || 0],
                ['Tracks',   stats.total_tracks   || 0],
                ['Missing',  stats.total_missing  || 0],
            ].map(([label, val]) =>
                `<div class="sidebar-stat">
                    <span>${label}</span>
                    <span class="sidebar-stat-value">${val.toLocaleString()}</span>
                </div>`
            ).join('');
        } catch {}
    }

    // ── Stub renderer for pages not yet implemented ───────────────
    function buildStub(pageName) {
        const label = pageName.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        return `
            <div class="empty-state" style="padding-top:80px">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" width="64" height="64">
                    <path d="M9 19V6l12-3v13"/><circle cx="6" cy="19" r="3"/><circle cx="18" cy="16" r="3"/>
                </svg>
                <div class="empty-state-title">${label}</div>
                <div class="empty-state-body">This page is coming soon.</div>
            </div>`;
    }

    // ── Public API ────────────────────────────────────────────────
    return {
        init,
        navigate,
        logout,
        setBadge,
        refreshSidebarStats,
        applyCalendarSetting,
        showLogin,
        // expose for 401 middleware in api.js
        get isLoggedIn() { return booted; },
    };
})();

// ── Global helpers (used by page modules) ─────────────────────────

function navigate(path) { App.navigate(path); }

function esc(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function timeAgo(dateStr) {
    if (!dateStr) return '';
    const diff = Date.now() - new Date(dateStr).getTime();
    const s = Math.floor(diff / 1000);
    if (s < 60)    return 'just now';
    if (s < 3600)  return `${Math.floor(s/60)}m ago`;
    if (s < 86400) return `${Math.floor(s/3600)}h ago`;
    return `${Math.floor(s/86400)}d ago`;
}

function formatDuration(ms) {
    if (!ms) return '—';
    const s = Math.round(ms / 1000);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${String(sec).padStart(2,'0')}`;
}

function formatSize(bytes) {
    if (!bytes) return '—';
    if (bytes > 1073741824) return (bytes / 1073741824).toFixed(1) + ' GB';
    if (bytes > 1048576)    return (bytes / 1048576).toFixed(1) + ' MB';
    return (bytes / 1024).toFixed(0) + ' KB';
}

function debounce(fn, ms = 300) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function toast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
        el.style.transition = 'opacity .25s, transform .25s';
        el.style.opacity = '0';
        el.style.transform = 'translateX(20px)';
        setTimeout(() => el.remove(), 260);
    }, duration);
}

// ── Boot ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => App.init());
