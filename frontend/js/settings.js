// ─── Settings Tab ────────────────────────────────────────────────
const Settings = (() => {
    function init() {
        window.addEventListener('message', (e) => {
            if (e.data?.type === 'spotify-connected') {
                toast('Spotify connected!', 'success');
                load();
                Library.load();
                updateSpotifyDot(true);
            }
        });
    }

    async function load() {
        const spotifyEl = document.getElementById('spotify-settings');
        const configEl = document.getElementById('config-settings');
        spotifyEl.innerHTML = '<div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div>';
        configEl.innerHTML = '<div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div>';

        try {
            const settings = await api.get('/settings');
            renderSpotify(settings);
            renderConfig(settings);
        } catch (err) {
            spotifyEl.innerHTML = `<div style="color:var(--red)">${err.message}</div>`;
        }
    }

    function renderSpotify(settings) {
        const el = document.getElementById('spotify-settings');
        updateSpotifyDot(settings.spotify_connected);

        const credentialsConfigured = settings.spotify_client_id && settings.spotify_client_secret_set;

        el.innerHTML = `
            <div class="setting-row">
                <span class="setting-label">Client ID</span>
                <input class="setting-input" id="cfg-spotify-client-id" value="${settings.spotify_client_id || ''}" placeholder="From developer.spotify.com">
            </div>
            <div class="setting-row">
                <span class="setting-label">Client Secret</span>
                <input class="setting-input" id="cfg-spotify-client-secret" type="password" value="" placeholder="${settings.spotify_client_secret_set ? '(saved — leave blank to keep)' : 'From developer.spotify.com'}">
            </div>
            <div class="setting-row">
                <span class="setting-label">Redirect URI</span>
                <input class="setting-input" id="cfg-spotify-redirect-uri" value="${settings.spotify_redirect_uri || ''}">
            </div>
            <div class="setting-row">
                <span class="setting-label"></span>
                <button class="btn btn-accent btn-sm" id="save-spotify-creds">Save Credentials</button>
            </div>
            <hr style="border-color:var(--border);margin:16px 0">
            <div class="setting-row">
                <span class="setting-label">Status</span>
                <span style="color:${settings.spotify_connected ? 'var(--green)' : 'var(--red)'};font-weight:500">
                    ${settings.spotify_connected ? 'Connected' : 'Not connected'}
                </span>
            </div>
            ${settings.spotify_connected ? `
                <div class="setting-row">
                    <span class="setting-label">Scopes</span>
                    <span style="font-size:.8rem;color:var(--text-dim)">${settings.spotify_scopes || '—'}</span>
                </div>
                <div class="setting-row">
                    <span class="setting-label"></span>
                    <button class="btn btn-danger btn-sm" id="spotify-disconnect">Disconnect</button>
                </div>
            ` : `
                <div class="setting-row">
                    <span class="setting-label"></span>
                    <button class="btn btn-accent btn-sm" id="spotify-connect" ${credentialsConfigured ? '' : 'disabled title="Save Client ID and Secret first"'}>Connect Spotify</button>
                </div>
            `}
        `;

        document.getElementById('save-spotify-creds').addEventListener('click', async () => {
            const clientId = document.getElementById('cfg-spotify-client-id').value.trim();
            const clientSecret = document.getElementById('cfg-spotify-client-secret').value.trim();
            const redirectUri = document.getElementById('cfg-spotify-redirect-uri').value.trim();

            const body = { spotify_client_id: clientId, spotify_redirect_uri: redirectUri };
            if (clientSecret) body.spotify_client_secret = clientSecret;

            try {
                await api.put('/settings', body);
                toast('Spotify credentials saved', 'success');
                load();
            } catch (err) { toast(err.message, 'error'); }
        });

        if (settings.spotify_connected) {
            document.getElementById('spotify-disconnect').addEventListener('click', async () => {
                if (!confirm('Disconnect Spotify?')) return;
                try {
                    await api.post('/spotify/disconnect');
                    toast('Spotify disconnected', 'info');
                    updateSpotifyDot(false);
                    load();
                } catch (err) { toast(err.message, 'error'); }
            });
        } else {
            const connectBtn = document.getElementById('spotify-connect');
            if (connectBtn && !connectBtn.disabled) {
                connectBtn.addEventListener('click', async () => {
                    try {
                        const data = await api.get('/spotify/auth-url');
                        window.open(data.url, 'spotify-auth', 'width=500,height=700');
                    } catch (err) { toast(err.message, 'error'); }
                });
            }
        }
    }

    function renderConfig(settings) {
        const el = document.getElementById('config-settings');
        el.innerHTML = `
            <div class="setting-row">
                <span class="setting-label">Music Library Path</span>
                <input class="setting-input" id="cfg-music-path" value="${settings.music_path || '/music'}" placeholder="/music">
            </div>
            <div class="setting-row">
                <span class="setting-label">Spotizerr URL</span>
                <input class="setting-input" id="cfg-spotizerr-url" value="${settings.spotizerr_url || ''}" disabled>
            </div>
            <div class="setting-row">
                <span class="setting-label">Sync Interval (min)</span>
                <input class="setting-input" id="cfg-sync-interval" type="number" value="${settings.sync_interval_minutes}" min="5" max="1440">
            </div>
            <div class="setting-row">
                <span class="setting-label">Fuzzy Match Threshold</span>
                <input class="setting-input" id="cfg-fuzzy-threshold" type="number" value="${settings.fuzzy_threshold}" min="50" max="100">
            </div>
            <div class="setting-row">
                <span class="setting-label">M3U Path Prefix</span>
                <input class="setting-input" id="cfg-m3u-prefix" value="${settings.m3u_path_prefix || ''}">
            </div>
            <div class="setting-row">
                <span class="setting-label">Scan Interval (hours)</span>
                <input class="setting-input" id="cfg-scan-interval" type="number" value="${settings.scan_interval_hours}" min="1" max="168">
            </div>
            <hr style="border-color:var(--border);margin:16px 0">
            <div class="setting-row">
                <span class="setting-label">Jellyfin URL</span>
                <input class="setting-input" id="cfg-jellyfin-url" value="${settings.jellyfin_url || ''}" placeholder="http://192.168.1.152:8096/jellyfin">
            </div>
            <div class="setting-row">
                <span class="setting-label">Jellyfin API Key</span>
                <input class="setting-input" id="cfg-jellyfin-api-key" value="${settings.jellyfin_api_key || ''}" placeholder="From Jellyfin Dashboard > API Keys">
            </div>
            <div class="setting-row">
                <span class="setting-label"></span>
                <button class="btn btn-accent btn-sm" id="save-config">Save Settings</button>
            </div>
        `;

        document.getElementById('save-config').addEventListener('click', async () => {
            try {
                await api.put('/settings', {
                    music_path: document.getElementById('cfg-music-path').value,
                    sync_interval_minutes: parseInt(document.getElementById('cfg-sync-interval').value),
                    fuzzy_threshold: parseInt(document.getElementById('cfg-fuzzy-threshold').value),
                    m3u_path_prefix: document.getElementById('cfg-m3u-prefix').value,
                    scan_interval_hours: parseInt(document.getElementById('cfg-scan-interval').value),
                    jellyfin_url: document.getElementById('cfg-jellyfin-url').value,
                    jellyfin_api_key: document.getElementById('cfg-jellyfin-api-key').value,
                });
                toast('Settings saved', 'success');
            } catch (err) { toast(err.message, 'error'); }
        });
    }

    function updateSpotifyDot(connected) {
        const dot = document.getElementById('spotify-dot');
        dot.classList.toggle('connected', connected);
        dot.title = connected ? 'Spotify connected' : 'Spotify disconnected';
    }

    return { init, load };
})();
