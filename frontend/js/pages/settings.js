// ─── Settings Page ────────────────────────────────────────────────
const SettingsPage = (() => {
    const root = () => document.getElementById('page-root');

    const SECTIONS = [
        { id: 'media',             label: 'Media Management' },
        { id: 'quality',           label: 'Quality Profiles' },
        { id: 'metadata-profiles', label: 'Metadata Profiles' },
        { id: 'release-profiles',  label: 'Release Profiles' },
        { id: 'clients',           label: 'Download Clients' },
        { id: 'indexers',          label: 'Indexers' },
        { id: 'spotify',           label: 'Spotify' },
        { id: 'notifications',     label: 'Notifications' },
        { id: 'system',            label: 'System' },
    ];

    let activeSection = 'spotify';

    function load({ section } = {}) {
        if (section && SECTIONS.find(s => s.id === section)) {
            activeSection = section;
        }

        root().innerHTML = `
            <div class="page-header">
                <div class="page-header-left">
                    <h1 class="page-title">Settings</h1>
                </div>
            </div>

            <div class="settings-layout">
                <nav class="settings-sidenav">
                    ${SECTIONS.map(s => `
                        <a class="settings-sidenav-item ${s.id === activeSection ? 'active' : ''}"
                           data-section="${s.id}" href="#/settings/${s.id}">${s.label}</a>
                    `).join('')}
                </nav>
                <div class="settings-content" id="settings-content">
                    ${renderSection(activeSection)}
                </div>
            </div>`;

        root().querySelectorAll('.settings-sidenav-item').forEach(el => {
            el.addEventListener('click', e => {
                e.preventDefault();
                activeSection = el.dataset.section;
                root().querySelectorAll('.settings-sidenav-item').forEach(i => {
                    i.classList.toggle('active', i.dataset.section === activeSection);
                });
                document.getElementById('settings-content').innerHTML = renderSection(activeSection);
                bindSection(activeSection);
            });
        });

        bindSection(activeSection);
    }

    function renderSection(id) {
        switch (id) {
            case 'spotify':           return renderSpotify();
            case 'media':             return renderMedia();
            case 'quality':           return renderQuality();
            case 'metadata-profiles': return renderMetadataProfiles();
            case 'release-profiles':  return renderReleaseProfiles();
            case 'clients':           return renderClients();
            case 'indexers':          return renderIndexers();
            case 'system':            return renderSystem();
            case 'notifications':     return renderNotifications();
            default: return `<div class="empty-state"><div class="empty-state-title">Coming Soon</div></div>`;
        }
    }

    function bindSection(id) {
        if (id === 'spotify')           bindSpotify();
        if (id === 'media')             bindMedia();
        if (id === 'quality')           bindQuality();
        if (id === 'metadata-profiles') bindMetadataProfiles();
        if (id === 'release-profiles')  bindReleaseProfiles();
        if (id === 'clients')           bindClients();
        if (id === 'indexers')          bindIndexers();
        if (id === 'system')            bindSystem();
        if (id === 'notifications')     bindNotifications();
    }

    // ── Shared save helper ────────────────────────────────────────
    async function saveSettings(payload, btnEl) {
        if (btnEl) { btnEl.disabled = true; btnEl.textContent = 'Saving…'; }
        try {
            await api.put('/settings', payload);
            toast('Saved', 'success');
        } catch(e) {
            toast('Save failed: ' + (e.message || 'Error'), 'error');
        }
        if (btnEl) { btnEl.disabled = false; btnEl.textContent = 'Save'; }
    }

    // ── Spotify section ───────────────────────────────────────────
    function renderSpotify() {
        return `
            <div class="settings-section-title">Spotify Connection</div>
            <div id="spotify-section-body">
                <div style="text-align:center;padding:32px 0">
                    <div class="spinner spinner-lg" style="margin:0 auto 12px"></div>
                    <div style="font-size:.875rem;color:var(--text-muted)">Loading…</div>
                </div>
            </div>`;
    }

    async function bindSpotify() {
        const body = document.getElementById('spotify-section-body');
        if (!body) return;
        try {
            const [settings, status] = await Promise.all([
                api.get('/settings'),
                api.get('/spotify/status'),
            ]);

            if (status.connected) {
                body.innerHTML = `
                    <div class="info-box" style="margin-bottom:20px">
                        <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16" style="color:var(--teal);flex-shrink:0">
                            <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/>
                        </svg>
                        <span>Spotify is connected.</span>
                    </div>
                    <div class="form-row">
                        <div class="form-label">Scopes</div>
                        <div class="form-control" style="font-size:.8rem;color:var(--text-dim)">${esc(status.scopes || 'unknown')}</div>
                    </div>
                    <div class="form-row">
                        <div class="form-label">Rate Limit</div>
                        <div class="form-control" id="sp-rate-status" style="font-size:.875rem;color:var(--text-dim)">Loading…</div>
                    </div>
                    <div class="form-row">
                        <div class="form-label"></div>
                        <div class="form-control">
                            <button class="btn btn-danger btn-sm" id="spotify-disconnect-btn">Disconnect Spotify</button>
                        </div>
                    </div>`;

                document.getElementById('spotify-disconnect-btn')?.addEventListener('click', async () => {
                    if (!confirm('Disconnect Spotify? You will need to re-authorize.')) return;
                    await api.post('/spotify/disconnect');
                    toast('Spotify disconnected', 'info');
                    bindSpotify();
                });

                // Load rate limit info
                try {
                    const rl = await api.get('/spotify/rate-status');
                    const el = document.getElementById('sp-rate-status');
                    if (el) {
                        const ok = !rl.is_blocked;
                        el.innerHTML = ok
                            ? `<span style="color:var(--green)">● OK</span> — ${rl.calls_last_hour || 0} calls last hour`
                            : `<span style="color:var(--red)">● Rate limited</span> — resets in ${rl.cooldown_remaining_s || '?'}s`;
                    }
                } catch {}
            } else {
                body.innerHTML = `
                    <div class="form-row">
                        <div class="form-label">Client ID
                            <div class="form-hint">From your Spotify developer app</div>
                        </div>
                        <div class="form-control">
                            <input class="input" id="sp-client-id" value="${esc(settings.spotify_client_id)}" placeholder="Spotify Client ID">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-label">Client Secret
                            <div class="form-hint">Keep this private</div>
                        </div>
                        <div class="form-control">
                            <input class="input" id="sp-client-secret" type="password"
                                   placeholder="${settings.spotify_client_secret_set ? '(saved — enter to change)' : 'Spotify Client Secret'}">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-label">Redirect URI
                            <div class="form-hint">Must match your Spotify app</div>
                        </div>
                        <div class="form-control">
                            <input class="input" id="sp-redirect-uri" value="${esc(settings.spotify_redirect_uri)}">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-label"></div>
                        <div class="form-control" style="display:flex;gap:8px">
                            <button class="btn" id="sp-save-btn">Save</button>
                            <button class="btn btn-primary" id="sp-connect-btn">Connect Spotify</button>
                        </div>
                    </div>`;

                document.getElementById('sp-save-btn')?.addEventListener('click', async () => {
                    const btn = document.getElementById('sp-save-btn');
                    const payload = {};
                    const cid  = document.getElementById('sp-client-id').value.trim();
                    const csec = document.getElementById('sp-client-secret').value.trim();
                    const ruri = document.getElementById('sp-redirect-uri').value.trim();
                    if (cid)  payload.spotify_client_id     = cid;
                    if (csec) payload.spotify_client_secret = csec;
                    if (ruri) payload.spotify_redirect_uri  = ruri;
                    await saveSettings(payload, btn);
                });

                document.getElementById('sp-connect-btn')?.addEventListener('click', async () => {
                    try {
                        const cid  = document.getElementById('sp-client-id').value.trim();
                        const csec = document.getElementById('sp-client-secret').value.trim();
                        if (cid || csec) {
                            const payload = {};
                            if (cid)  payload.spotify_client_id     = cid;
                            if (csec) payload.spotify_client_secret = csec;
                            await api.put('/settings', payload);
                        }
                        const data = await api.get('/spotify/auth-url');
                        const win = window.open(data.url, 'spotify-auth', 'width=520,height=720');
                        const handler = (e) => {
                            if (e.data?.type === 'spotify-connected') {
                                window.removeEventListener('message', handler);
                                toast('Spotify connected!', 'success');
                                bindSpotify();
                            }
                        };
                        window.addEventListener('message', handler);
                    } catch (e) { toast(e.message || 'Failed to get auth URL', 'error'); }
                });
            }
        } catch {
            body.innerHTML = `<div class="empty-state"><div class="empty-state-title">Could not load settings</div></div>`;
        }
    }

    // ── Media Management ──────────────────────────────────────────
    function renderMedia() {
        return `
            <div class="settings-section-title">Media Management</div>
            <div id="media-section-body">
                <div style="text-align:center;padding:32px 0;color:var(--text-muted)">Loading…</div>
            </div>`;
    }

    async function bindMedia() {
        const body = document.getElementById('media-section-body');
        if (!body) return;
        try {
            const s = await api.get('/settings');
            body.innerHTML = `
                <div class="form-row">
                    <div class="form-label">Music Folder
                        <div class="form-hint">Absolute path inside the container</div>
                    </div>
                    <div class="form-control">
                        <input class="input" id="m-music-path" value="${esc(s.music_path)}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">M3U Path Prefix
                        <div class="form-hint">Prepended to track paths in M3U playlists</div>
                    </div>
                    <div class="form-control">
                        <input class="input" id="m-m3u-prefix" value="${esc(s.m3u_path_prefix)}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Scan Interval
                        <div class="form-hint">Hours between automatic scans</div>
                    </div>
                    <div class="form-control" style="display:flex;align-items:center;gap:8px">
                        <input class="input" id="m-scan-interval" type="number" min="1" max="168" value="${s.scan_interval_hours}" style="width:80px">
                        <span style="color:var(--text-muted)">hours</span>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Fuzzy Match Threshold
                        <div class="form-hint">Minimum match score (0–100) for local track enrichment</div>
                    </div>
                    <div class="form-control" style="display:flex;align-items:center;gap:8px">
                        <input class="input" id="m-fuzzy" type="number" min="50" max="100" value="${s.fuzzy_threshold}" style="width:80px">
                        <span style="color:var(--text-muted)">%</span>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Jellyfin URL
                        <div class="form-hint">Optional — for library refresh triggers</div>
                    </div>
                    <div class="form-control">
                        <input class="input" id="m-jellyfin-url" value="${esc(s.jellyfin_url)}" placeholder="http://jellyfin:8096">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Jellyfin API Key</div>
                    <div class="form-control">
                        <input class="input" id="m-jellyfin-key" type="password"
                               placeholder="${s.jellyfin_api_key ? '(saved)' : 'API key'}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label"></div>
                    <div class="form-control">
                        <button class="btn btn-primary" id="m-save-btn">Save</button>
                    </div>
                </div>`;

            document.getElementById('m-save-btn').addEventListener('click', async () => {
                const btn = document.getElementById('m-save-btn');
                const payload = {
                    music_path:        document.getElementById('m-music-path').value.trim(),
                    m3u_path_prefix:   document.getElementById('m-m3u-prefix').value.trim(),
                    scan_interval_hours: parseInt(document.getElementById('m-scan-interval').value) || 6,
                    fuzzy_threshold:   parseInt(document.getElementById('m-fuzzy').value) || 85,
                    jellyfin_url:      document.getElementById('m-jellyfin-url').value.trim(),
                };
                const jKey = document.getElementById('m-jellyfin-key').value.trim();
                if (jKey) payload.jellyfin_api_key = jKey;
                await saveSettings(payload, btn);
            });
        } catch(e) {
            body.innerHTML = `<div class="empty-state"><div class="empty-state-title">Load failed</div></div>`;
        }
    }

    // ── Quality Profiles ──────────────────────────────────────────
    function renderQuality() {
        return `
            <div class="settings-section-title" style="display:flex;align-items:center;justify-content:space-between">
                Quality Profiles
                <button class="btn btn-sm btn-primary" id="qp-add-btn">+ Add Profile</button>
            </div>
            <div id="qp-list">
                <div style="padding:24px 0;color:var(--text-muted);text-align:center">Loading…</div>
            </div>
            <div id="qp-edit-panel" hidden></div>`;
    }

    async function bindQuality() {
        await loadQualityProfiles();
        document.getElementById('qp-add-btn')?.addEventListener('click', () => showQualityForm(null));
    }

    async function loadQualityProfiles() {
        const list = document.getElementById('qp-list');
        if (!list) return;
        try {
            const profiles = await api.get('/quality-profiles');
            if (profiles.length === 0) {
                list.innerHTML = `<div style="padding:16px 0;color:var(--text-muted)">No profiles. Add one above.</div>`;
                return;
            }
            list.innerHTML = `
                <table class="arr-table" style="margin-top:8px;border-left:2px solid var(--accent,#f5c518)">
                    <thead><tr>
                        <th>Name</th><th>Format</th><th>Min Bitrate</th><th>Upgrade</th><th>Default</th><th style="width:80px">Actions</th>
                    </tr></thead>
                    <tbody>
                    ${profiles.map(p => `
                        <tr data-qp-id="${p.id}">
                            <td style="font-weight:500">${esc(p.name)}</td>
                            <td>${esc(p.preferred_format || 'Any')}</td>
                            <td>${p.min_bitrate ? p.min_bitrate + ' kbps' : '—'}</td>
                            <td>${p.upgrade_allowed ? '✓' : '—'}</td>
                            <td>${p.is_default ? '<span style="color:var(--accent);font-weight:600">Default</span>' : ''}</td>
                            <td>
                                <div style="display:flex;gap:4px;align-items:center">
                                    <button class="btn-xs btn-qp-edit" data-id="${p.id}" ${p.is_default ? 'disabled' : ''}>Edit</button>
                                    ${!p.is_default ? `<button class="btn-xs btn-danger btn-qp-del" data-id="${p.id}">Del</button>` : ''}
                                </div>
                            </td>
                        </tr>`).join('')}
                    </tbody>
                </table>`;

            list.querySelectorAll('.btn-qp-edit').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const p = profiles.find(x => x.id == btn.dataset.id);
                    if (p) showQualityForm(p);
                });
            });
            list.querySelectorAll('.btn-qp-del').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm('Delete this quality profile?')) return;
                    btn.disabled = true;
                    try {
                        await api.del(`/quality-profiles/${btn.dataset.id}`);
                        await loadQualityProfiles();
                    } catch(e) { toast('Delete failed: ' + e.message, 'error'); btn.disabled = false; }
                });
            });
        } catch(e) {
            list.innerHTML = `<div style="color:var(--red)">Failed to load profiles</div>`;
        }
    }

    function showQualityForm(profile) {
        const panel = document.getElementById('qp-edit-panel');
        if (!panel) return;
        panel.hidden = false;
        panel.innerHTML = `
            <div style="border-top:1px solid var(--border);margin-top:16px;padding-top:16px">
                <div class="settings-section-title" style="margin-bottom:16px">${profile ? 'Edit Profile' : 'New Profile'}</div>
                <div class="form-row">
                    <div class="form-label">Name</div>
                    <div class="form-control"><input class="input" id="qp-name" value="${esc(profile?.name || '')}"></div>
                </div>
                <div class="form-row">
                    <div class="form-label">Preferred Format</div>
                    <div class="form-control">
                        <select class="input" id="qp-format" style="width:160px">
                            ${['any','flac','mp3','opus','aac','m4a'].map(f =>
                                `<option value="${f}" ${profile?.preferred_format === f ? 'selected' : ''}>${f.toUpperCase()}</option>`
                            ).join('')}
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Min Bitrate (kbps)
                        <div class="form-hint">0 = any</div>
                    </div>
                    <div class="form-control"><input class="input" id="qp-bitrate" type="number" min="0" max="9999" value="${profile?.min_bitrate || 0}" style="width:90px"></div>
                </div>
                <div class="form-row">
                    <div class="form-label">Allow Upgrade</div>
                    <div class="form-control">
                        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                            <input type="checkbox" id="qp-upgrade" ${profile?.upgrade_allowed ? 'checked' : ''}>
                            Upgrade if better quality found
                        </label>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label"></div>
                    <div class="form-control" style="display:flex;gap:8px">
                        <button class="btn btn-primary" id="qp-save">Save</button>
                        <button class="btn" id="qp-cancel">Cancel</button>
                    </div>
                </div>
            </div>`;

        document.getElementById('qp-cancel').addEventListener('click', () => {
            panel.hidden = true;
        });

        document.getElementById('qp-save').addEventListener('click', async () => {
            const btn = document.getElementById('qp-save');
            btn.disabled = true; btn.textContent = 'Saving…';
            const body = {
                name:             document.getElementById('qp-name').value.trim(),
                preferred_format: document.getElementById('qp-format').value,
                min_bitrate:      parseInt(document.getElementById('qp-bitrate').value) || 0,
                upgrade_allowed:  document.getElementById('qp-upgrade').checked,
            };
            if (!body.name) { toast('Name required', 'error'); btn.disabled = false; btn.textContent = 'Save'; return; }
            try {
                if (profile?.id) {
                    await api.put(`/quality-profiles/${profile.id}`, body);
                } else {
                    await api.post('/quality-profiles', body);
                }
                toast('Profile saved', 'success');
                panel.hidden = true;
                await loadQualityProfiles();
            } catch(e) { toast('Save failed: ' + e.message, 'error'); btn.disabled = false; btn.textContent = 'Save'; }
        });
    }

    // ── Download Clients ──────────────────────────────────────────
    const DC_TYPE_LABELS = {
        spotizerr: 'Spotizerr', metube: 'MeTube (YouTube)',
        qbittorrent: 'qBittorrent', slskd: 'slskd (Soulseek)', sabnzbd: 'SABnzbd',
    };

    function renderClients() {
        return `
            <p style="font-size:.85rem;color:var(--text-dim);margin-bottom:16px">Configure your download clients. If multiple clients of the same type are added, the topmost enabled one is used.</p>
            <div class="settings-section-title" style="display:flex;align-items:center;justify-content:space-between">
                Download Clients
                <div style="display:flex;gap:8px;align-items:center">
                    <select class="input" id="dc-type-select" style="width:180px;font-size:13px">
                        ${Object.entries(DC_TYPE_LABELS).map(([v,l]) => `<option value="${v}">${l}</option>`).join('')}
                    </select>
                    <button class="btn btn-sm btn-primary" id="dc-add-btn">+ Add</button>
                </div>
            </div>
            <div id="dc-list">
                <div style="padding:24px 0;color:var(--text-muted);text-align:center">Loading…</div>
            </div>
            <div id="dc-edit-panel" hidden></div>

            <div class="settings-section-title" style="margin-top:32px">Spotizerr Settings</div>
            <div id="spotizerr-settings-body">
                <div style="padding:16px 0;color:var(--text-muted);text-align:center">Loading…</div>
            </div>

            <div class="settings-section-title" style="margin-top:32px">MeTube / YouTube Settings</div>
            <div id="metube-settings-body">
                <div style="padding:16px 0;color:var(--text-muted);text-align:center">Loading…</div>
            </div>

            <div class="settings-section-title" style="margin-top:32px">Soulseek Settings</div>
            <div id="slsk-settings-body">
                <div style="padding:16px 0;color:var(--text-muted);text-align:center">Loading…</div>
            </div>

            <div class="settings-section-title" style="margin-top:32px">qBittorrent Post-Download</div>
            <p style="font-size:.85rem;color:var(--text-dim);margin:0 0 12px">
                When a torrent completes, automatically hardlink the files into your music library.
                Requires qBit save path and library to be on the same filesystem/volume.
            </p>
            <div id="qbit-postdl-body">
                <div style="padding:16px 0;color:var(--text-muted);text-align:center">Loading…</div>
            </div>

            <div class="settings-section-title" style="margin-top:32px">Download Source Priority</div>
            <p style="font-size:.85rem;color:var(--text-dim);margin:0 0 12px">
                When dispatching wanted tracks, each source is tried in this order. Drag to reorder. Spotizerr is manual-only and not included here.
            </p>
            <div id="source-priority-body">
                <div style="padding:16px 0;color:var(--text-muted);text-align:center">Loading…</div>
            </div>`;
    }

    async function bindClients() {
        await loadDCList();
        document.getElementById('dc-add-btn')?.addEventListener('click', () => {
            const type = document.getElementById('dc-type-select')?.value || 'qbittorrent';
            showDCForm(null, type);
        });
        loadSpotizerrSettings();
        loadMeTubeSettings();
        loadSlskSettings();
        loadQbitPostDl();
        loadSourcePriority();
    }

    async function loadDCList() {
        const list = document.getElementById('dc-list');
        if (!list) return;
        try {
            const clients = await api.get('/download-clients');
            if (clients.length === 0) {
                list.innerHTML = `<div style="padding:16px 0;color:var(--text-muted)">No additional download clients configured. Add one above.</div>`;
                return;
            }
            list.innerHTML = `
                <table class="arr-table" style="margin-top:8px">
                    <thead><tr>
                        <th>Name</th><th>Type</th><th>Status</th>
                        <th style="width:100px">Actions</th>
                    </tr></thead>
                    <tbody>
                    ${clients.map((c, i) => `
                        <tr data-dc-id="${c.id}">
                            <td style="font-weight:500">${esc(c.name)}</td>
                            <td>${esc(DC_TYPE_LABELS[c.type] || c.type)}</td>
                            <td>
                                <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
                                    <input type="checkbox" class="dc-enabled-cb" data-id="${c.id}" ${c.enabled ? 'checked' : ''}>
                                    <span style="font-size:.8rem;color:${c.enabled ? 'var(--green)' : 'var(--text-muted)'}">${c.enabled ? 'Enabled' : 'Disabled'}</span>
                                </label>
                            </td>
                            <td style="display:flex;gap:4px;align-items:center">
                                <button class="btn-xs dc-test" data-id="${c.id}">Test</button>
                                <button class="btn-xs dc-edit" data-id="${c.id}">Edit</button>
                                <button class="btn-xs btn-danger dc-del" data-id="${c.id}">Del</button>
                            </td>
                        </tr>`).join('')}
                    </tbody>
                </table>`;

            list.querySelectorAll('.dc-enabled-cb').forEach(cb => {
                cb.addEventListener('change', async () => {
                    cb.disabled = true;
                    try { await api.put(`/download-clients/${cb.dataset.id}`, { enabled: cb.checked ? 1 : 0 }); }
                    catch(e) { toast('Failed: ' + e.message, 'error'); cb.checked = !cb.checked; }
                    cb.disabled = false;
                    await loadDCList();
                });
            });

            list.querySelectorAll('.dc-test').forEach(btn => {
                btn.addEventListener('click', async () => {
                    btn.disabled = true; btn.textContent = '…';
                    try {
                        const r = await api.post(`/download-clients/${btn.dataset.id}/test`);
                        toast(r.ok ? `✓ ${r.message}` : `✗ ${r.message}`, r.ok ? 'success' : 'error');
                    } catch(e) { toast('Test failed: ' + e.message, 'error'); }
                    btn.disabled = false; btn.textContent = 'Test';
                });
            });

            list.querySelectorAll('.dc-edit').forEach(btn => {
                btn.addEventListener('click', () => {
                    const c = clients.find(x => x.id == btn.dataset.id);
                    if (c) showDCForm(c, c.type);
                });
            });

            list.querySelectorAll('.dc-del').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm('Delete this download client?')) return;
                    btn.disabled = true;
                    try { await api.del(`/download-clients/${btn.dataset.id}`); await loadDCList(); }
                    catch(e) { toast('Delete failed: ' + e.message, 'error'); btn.disabled = false; }
                });
            });
        } catch(e) {
            list.innerHTML = `<div style="color:var(--red)">Failed to load clients</div>`;
        }
    }

    function showDCForm(client, type) {
        const panel = document.getElementById('dc-edit-panel');
        if (!panel) return;
        panel.hidden = false;
        const isEdit = !!client;

        const fields = buildDCFields(type, client);
        panel.innerHTML = `
            <div style="border-top:1px solid var(--border);margin-top:16px;padding-top:16px">
                <div class="settings-section-title" style="margin-bottom:16px">${isEdit ? 'Edit' : 'Add'} ${DC_TYPE_LABELS[type] || type}</div>
                <div class="form-row">
                    <div class="form-label">Name</div>
                    <div class="form-control"><input class="input" id="dcf-name" value="${esc(client?.name || DC_TYPE_LABELS[type] || '')}"></div>
                </div>
                ${fields}
                <div class="form-row">
                    <div class="form-label"></div>
                    <div class="form-control" style="display:flex;gap:8px">
                        <button class="btn btn-primary" id="dcf-save">Save</button>
                        <button class="btn" id="dcf-cancel">Cancel</button>
                    </div>
                </div>
            </div>`;

        document.getElementById('dcf-cancel').addEventListener('click', () => {
            panel.hidden = true; panel.innerHTML = '';
        });

        document.getElementById('dcf-save').addEventListener('click', async () => {
            const btn = document.getElementById('dcf-save');
            btn.disabled = true; btn.textContent = 'Saving…';
            try {
                const payload = { name: document.getElementById('dcf-name').value.trim(), type };
                collectDCFields(payload, type);
                if (isEdit) {
                    await api.put(`/download-clients/${client.id}`, payload);
                } else {
                    await api.post('/download-clients', payload);
                }
                panel.hidden = true; panel.innerHTML = '';
                toast(isEdit ? 'Client updated' : 'Client added', 'success');
                await loadDCList();
            } catch(e) {
                toast('Save failed: ' + e.message, 'error');
                btn.disabled = false; btn.textContent = 'Save';
            }
        });
    }

    function buildDCFields(type, client) {
        const v = client || {};
        if (type === 'spotizerr') {
            return `
            <div class="form-row">
                <div class="form-label">URL</div>
                <div class="form-control"><input class="input" id="dcf-url" value="${esc(v.url_base || '')}" placeholder="http://spotizerr:7171"></div>
            </div>`;
        }
        if (type === 'metube') {
            return `
            <div class="form-row">
                <div class="form-label">URL</div>
                <div class="form-control"><input class="input" id="dcf-url" value="${esc(v.url_base || '')}" placeholder="http://metube:8081"></div>
            </div>`;
        }
        if (type === 'qbittorrent') {
            return `
            <div class="form-row">
                <div class="form-label">Host</div>
                <div class="form-control"><input class="input" id="dcf-host" value="${esc(v.host || '')}" placeholder="localhost"></div>
            </div>
            <div class="form-row">
                <div class="form-label">Port</div>
                <div class="form-control"><input class="input" id="dcf-port" type="number" value="${v.port || 8080}" style="width:100px"></div>
            </div>
            <div class="form-row">
                <div class="form-label">Username</div>
                <div class="form-control"><input class="input" id="dcf-user" value="${esc(v.username || '')}"></div>
            </div>
            <div class="form-row">
                <div class="form-label">Password</div>
                <div class="form-control"><input class="input" id="dcf-pass" type="password" placeholder="${v.password ? '(saved)' : ''}"></div>
            </div>
            <div class="form-row">
                <div class="form-label">URL Base</div>
                <div class="form-control"><input class="input" id="dcf-urlbase" value="${esc(v.url_base || '')}" placeholder="/"></div>
            </div>
            <div class="form-row">
                <div class="form-label">SSL</div>
                <div class="form-control">
                    <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                        <input type="checkbox" id="dcf-ssl" ${v.use_ssl ? 'checked' : ''}>Use HTTPS
                    </label>
                </div>
            </div>`;
        }
        if (type === 'sabnzbd') {
            return `
            <div class="form-row">
                <div class="form-label">Host</div>
                <div class="form-control"><input class="input" id="dcf-host" value="${esc(v.host || '')}" placeholder="localhost"></div>
            </div>
            <div class="form-row">
                <div class="form-label">Port</div>
                <div class="form-control"><input class="input" id="dcf-port" type="number" value="${v.port || 8080}" style="width:100px"></div>
            </div>
            <div class="form-row">
                <div class="form-label">API Key</div>
                <div class="form-control"><input class="input" id="dcf-apikey" value="${esc(v.api_key || '')}" placeholder="SABnzbd API key"></div>
            </div>
            <div class="form-row">
                <div class="form-label">URL Base</div>
                <div class="form-control"><input class="input" id="dcf-urlbase" value="${esc(v.url_base || '')}" placeholder="/sabnzbd"></div>
            </div>
            <div class="form-row">
                <div class="form-label">SSL</div>
                <div class="form-control">
                    <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                        <input type="checkbox" id="dcf-ssl" ${v.use_ssl ? 'checked' : ''}>Use HTTPS
                    </label>
                </div>
            </div>`;
        }
        if (type === 'slskd') {
            return `
            <div class="form-row">
                <div class="form-label">URL</div>
                <div class="form-control"><input class="input" id="dcf-url" value="${esc(v.url_base || '')}" placeholder="http://localhost:5030"></div>
            </div>
            <div class="form-row">
                <div class="form-label">API Key</div>
                <div class="form-control"><input class="input" id="dcf-apikey" value="${esc(v.api_key || '')}" placeholder="slskd API key"></div>
            </div>`;
        }
        return '';
    }

    function collectDCFields(payload, type) {
        const g = id => document.getElementById(id)?.value?.trim() || '';
        const gi = id => parseInt(document.getElementById(id)?.value) || 0;
        const gc = id => document.getElementById(id)?.checked || false;
        if (type === 'spotizerr' || type === 'metube' || type === 'slskd') {
            payload.url_base = g('dcf-url');
        }
        if (type === 'slskd' || type === 'sabnzbd') {
            payload.api_key = g('dcf-apikey');
        }
        if (type === 'qbittorrent' || type === 'sabnzbd') {
            payload.host = g('dcf-host');
            payload.port = gi('dcf-port');
            payload.url_base = g('dcf-urlbase');
            payload.use_ssl = gc('dcf-ssl') ? 1 : 0;
        }
        if (type === 'qbittorrent') {
            payload.username = g('dcf-user');
            payload.password = g('dcf-pass');
        }
        if (type === 'sabnzbd') {
            payload.api_key = g('dcf-apikey');
        }
    }

    async function loadSpotizerrSettings() {
        const body = document.getElementById('spotizerr-settings-body');
        if (!body) return;
        try {
            const s = await api.get('/settings');
            body.innerHTML = `
                <div class="form-row">
                    <div class="form-label">Spotizerr URL
                        <div class="form-hint">Base URL for Spotizerr API</div>
                    </div>
                    <div class="form-control">
                        <input class="input" id="c-spotizerr-url" value="${esc(s.spotizerr_url)}" placeholder="http://spotizerr:7171">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Concurrent Limit
                        <div class="form-hint">Max parallel downloads dispatched</div>
                    </div>
                    <div class="form-control" style="display:flex;align-items:center;gap:8px">
                        <input class="input" id="c-concurrent" type="number" min="1" max="50" value="${s.spotizerr_concurrent_limit}" style="width:80px">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Dispatch Batch
                        <div class="form-hint">Downloads sent per dispatch cycle</div>
                    </div>
                    <div class="form-control" style="display:flex;align-items:center;gap:8px">
                        <input class="input" id="c-batch" type="number" min="1" max="50" value="${s.dispatch_batch_size}" style="width:80px">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label"></div>
                    <div class="form-control">
                        <button class="btn btn-primary" id="c-spotizerr-save">Save</button>
                    </div>
                </div>`;

            document.getElementById('c-spotizerr-save').addEventListener('click', async () => {
                const btn = document.getElementById('c-spotizerr-save');
                const payload = {
                    spotizerr_concurrent_limit: parseInt(document.getElementById('c-concurrent').value) || 20,
                    dispatch_batch_size: parseInt(document.getElementById('c-batch').value) || 10,
                };
                const url = document.getElementById('c-spotizerr-url').value.trim();
                if (url) payload.spotizerr_url = url;
                await saveSettings(payload, btn);
            });
        } catch(e) {
            body.innerHTML = `<div style="color:var(--red)">Failed to load: ${esc(e.message)}</div>`;
        }
    }

    async function loadMeTubeSettings() {
        const body = document.getElementById('metube-settings-body');
        if (!body) return;
        try {
            const [s, ytStatus] = await Promise.all([
                api.get('/settings'),
                api.get('/youtube/status').catch(() => ({ reachable: false })),
            ]);
            body.innerHTML = `
                <div class="form-row">
                    <div class="form-label">MeTube Status</div>
                    <div class="form-control">
                        ${ytStatus.reachable
                            ? `<span style="color:var(--green)">● Connected</span>`
                            : `<span style="color:var(--red)">● Not reachable</span>`}
                        <span style="color:var(--text-muted);font-size:12px;margin-left:8px">${esc(ytStatus.url || s.metube_url)}</span>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">MeTube URL</div>
                    <div class="form-control">
                        <input class="input" id="c-metube-url" value="${esc(s.metube_url)}" placeholder="http://metube:8081">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Default Format
                        <div class="form-hint">Audio format for YouTube downloads</div>
                    </div>
                    <div class="form-control">
                        <select class="input" id="c-yt-format" style="width:120px">
                            ${['mp3','opus','flac','m4a','wav','best'].map(f =>
                                `<option value="${f}" ${s.youtube_audio_format === f ? 'selected' : ''}>${f.toUpperCase()}</option>`
                            ).join('')}
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Audio Quality
                        <div class="form-hint">0 = best, 9 = worst (MP3 VBR)</div>
                    </div>
                    <div class="form-control" style="display:flex;align-items:center;gap:8px">
                        <input class="input" id="c-yt-quality" type="number" min="0" max="9" value="${s.youtube_audio_quality}" style="width:60px">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Search Mode
                        <div class="form-hint">What to search for when finding a track on YouTube</div>
                    </div>
                    <div class="form-control" style="display:flex;flex-direction:column;gap:8px">
                        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                            <input type="radio" name="yt-search-mode" value="studio" ${(s.youtube_search_mode || 'studio') === 'studio' ? 'checked' : ''}>
                            <span>Studio Release <span style="color:var(--text-muted);font-size:.8rem">— Official audio / lyric video (recommended)</span></span>
                        </label>
                        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                            <input type="radio" name="yt-search-mode" value="music_video" ${s.youtube_search_mode === 'music_video' ? 'checked' : ''}>
                            <span>Music Video <span style="color:var(--text-muted);font-size:.8rem">— Official music video</span></span>
                        </label>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">YouTube API Key
                        <div class="form-hint">Required for automatic fallback search</div>
                    </div>
                    <div class="form-control">
                        <input class="input" id="c-yt-api-key" type="password"
                               placeholder="${s.youtube_api_key_set ? '(saved — enter to change)' : 'AIza…'}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Enable Fallback
                        <div class="form-hint">Try YouTube when Spotizerr fails</div>
                    </div>
                    <div class="form-control">
                        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                            <input type="checkbox" id="c-yt-fallback" ${s.youtube_fallback_enabled ? 'checked' : ''}>
                            Auto-fallback to YouTube
                        </label>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label">Auto-Accept Threshold
                        <div class="form-hint">Score ≥ this → auto-download</div>
                    </div>
                    <div class="form-control" style="display:flex;align-items:center;gap:8px">
                        <input class="input" id="c-yt-threshold" type="number" min="70" max="100" value="${s.youtube_auto_threshold}" style="width:70px">
                        <span style="color:var(--text-muted)">%</span>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label"></div>
                    <div class="form-control">
                        <button class="btn btn-primary" id="c-metube-save">Save</button>
                    </div>
                </div>`;

            document.getElementById('c-metube-save').addEventListener('click', async () => {
                const btn = document.getElementById('c-metube-save');
                const payload = {
                    metube_url:            document.getElementById('c-metube-url').value.trim(),
                    youtube_audio_format:  document.getElementById('c-yt-format').value,
                    youtube_audio_quality: document.getElementById('c-yt-quality').value,
                    youtube_fallback_enabled: document.getElementById('c-yt-fallback').checked,
                    youtube_auto_threshold: parseInt(document.getElementById('c-yt-threshold').value) || 85,
                    youtube_search_mode: document.querySelector('input[name="yt-search-mode"]:checked')?.value || 'studio',
                };
                const ytKey = document.getElementById('c-yt-api-key').value.trim();
                if (ytKey) payload.youtube_api_key = ytKey;
                await saveSettings(payload, btn);
            });
        } catch(e) {
            body.innerHTML = `<div style="color:var(--red)">Failed to load: ${esc(e.message)}</div>`;
        }
    }

    async function loadSlskSettings() {
        const body = document.getElementById('slsk-settings-body');
        if (!body) return;
        try {
            const s = await api.get('/settings');
            body.innerHTML = `
                <div class="form-row">
                    <div class="form-label">Download Mode
                        <div class="form-hint">Default action when grabbing from Soulseek. People rarely upload singles — full albums are the norm.</div>
                    </div>
                    <div class="form-control" style="display:flex;flex-direction:column;gap:8px">
                        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                            <input type="radio" name="slsk-dl-mode" value="1" ${s.slsk_album_download !== false ? 'checked' : ''}>
                            <span>Full Album <span style="color:var(--text-muted);font-size:.8rem">— Download the entire folder (recommended)</span></span>
                        </label>
                        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                            <input type="radio" name="slsk-dl-mode" value="0" ${s.slsk_album_download === false ? 'checked' : ''}>
                            <span>Track Only <span style="color:var(--text-muted);font-size:.8rem">— Download only the wanted track</span></span>
                        </label>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-label"></div>
                    <div class="form-control">
                        <button class="btn btn-primary" id="c-slsk-save">Save</button>
                    </div>
                </div>`;
            document.getElementById('c-slsk-save').addEventListener('click', async () => {
                const btn = document.getElementById('c-slsk-save');
                const val = document.querySelector('input[name="slsk-dl-mode"]:checked')?.value;
                await saveSettings({ slsk_album_download: val !== '0' }, btn);
            });
        } catch(e) {
            body.innerHTML = `<div style="color:var(--red)">Failed to load: ${esc(e.message)}</div>`;
        }
    }

    // ── Auto-Download Priority ─────────────────────────────────────
    async function loadQbitPostDl() {
        const body = document.getElementById('qbit-postdl-body');
        if (!body) return;
        try {
            const s = await api.get('/settings');
            const enabled = s.torrent_hardlink_enabled || false;
            const savePath = s.torrent_save_path || '';
            body.innerHTML = `
                <div style="display:flex;flex-direction:column;gap:12px;max-width:520px">
                    <label style="display:flex;align-items:center;gap:10px;cursor:pointer">
                        <input type="checkbox" id="qbit-hardlink-enabled" ${enabled ? 'checked' : ''} style="accent-color:var(--accent);width:16px;height:16px">
                        <div>
                            <div style="font-size:.9rem;font-weight:500">Hardlink completed torrents to library</div>
                            <div style="font-size:.75rem;color:var(--text-muted)">Creates hardlinks so qBit keeps seeding while music is accessible</div>
                        </div>
                    </label>
                    <div>
                        <div class="form-label">Torrent save path (inside container)
                            <div class="form-hint">Where qBittorrent saves music downloads — must be on the same volume as the music library</div>
                        </div>
                        <input class="input" id="qbit-save-path" value="${esc(savePath)}" placeholder="/music/downloads" style="width:100%">
                    </div>
                    <div><button class="btn btn-primary" id="qbit-postdl-save">Save</button></div>
                </div>`;
            document.getElementById('qbit-postdl-save').addEventListener('click', async () => {
                const btn = document.getElementById('qbit-postdl-save');
                await saveSettings({
                    torrent_hardlink_enabled: document.getElementById('qbit-hardlink-enabled').checked,
                    torrent_save_path: document.getElementById('qbit-save-path').value.trim(),
                }, btn);
            });
        } catch(e) {
            body.innerHTML = `<div style="color:var(--red)">Failed to load: ${esc(e.message)}</div>`;
        }
    }

    const SOURCE_LABELS = {
        torrent:    { label: 'Torrents',   icon: '⬇', desc: 'via qBittorrent + Prowlarr' },
        usenet:     { label: 'Usenet',     icon: '📰', desc: 'via SABnzbd + Prowlarr' },
        soulseek:   { label: 'Soulseek',   icon: '🎵', desc: 'via slskd' },
        youtube:    { label: 'YouTube',    icon: '▶', desc: 'via MeTube / yt-dlp' },
    };

    async function loadSourcePriority() {
        const body = document.getElementById('source-priority-body');
        if (!body) return;
        try {
            const s = await api.get('/settings');
            let sources;
            try { sources = JSON.parse(s.download_source_priority || '[]'); } catch { sources = []; }
            if (!sources.length) sources = ['torrent','usenet','soulseek','youtube'];
            // Filter out spotizerr if present (now manual-only)
            sources = sources.filter(s => s !== 'spotizerr');

            renderSourcePriorityList(body, sources);
        } catch(e) {
            body.innerHTML = `<div style="color:var(--red)">Failed to load: ${esc(e.message)}</div>`;
        }
    }

    function renderSourcePriorityList(body, sources) {
        body.innerHTML = `
            <div id="source-priority-list" style="display:flex;flex-direction:column;gap:6px;max-width:520px">
                ${sources.map((src, i) => {
                    const info = SOURCE_LABELS[src] || { label: src, icon: '?', desc: '' };
                    return `
                    <div class="source-priority-row" draggable="true" data-source="${esc(src)}"
                         style="display:flex;align-items:center;gap:10px;padding:10px 12px;
                                background:var(--bg-raised);border:1px solid var(--border);
                                border-radius:6px;cursor:grab;user-select:none">
                        <span style="color:var(--text-muted);font-size:.85rem;width:18px;text-align:center">${i + 1}</span>
                        <span style="font-size:1rem">${info.icon}</span>
                        <div style="flex:1">
                            <div style="font-weight:500;font-size:.9rem">${esc(info.label)}</div>
                            <div style="font-size:.75rem;color:var(--text-muted)">${esc(info.desc)}</div>
                        </div>
                        <span style="color:var(--text-muted);font-size:1.1rem;cursor:grab">⠿</span>
                    </div>`;
                }).join('')}
            </div>
            <div style="display:flex;gap:8px;margin-top:12px">
                <button class="btn btn-primary" id="source-priority-save">Save Order</button>
                <span style="font-size:.8rem;color:var(--text-muted);align-self:center">Drag rows to reorder</span>
            </div>`;

        // Drag-and-drop reorder
        const list = body.querySelector('#source-priority-list');
        let dragSrc = null;

        list.querySelectorAll('.source-priority-row').forEach(row => {
            row.addEventListener('dragstart', () => {
                dragSrc = row;
                setTimeout(() => row.style.opacity = '0.4', 0);
            });
            row.addEventListener('dragend', () => {
                row.style.opacity = '1';
                // Update position numbers
                list.querySelectorAll('.source-priority-row').forEach((r, i) => {
                    r.querySelector('span:first-child').textContent = i + 1;
                });
            });
            row.addEventListener('dragover', e => {
                e.preventDefault();
                if (row !== dragSrc) {
                    const rect = row.getBoundingClientRect();
                    const mid = rect.top + rect.height / 2;
                    if (e.clientY < mid) {
                        list.insertBefore(dragSrc, row);
                    } else {
                        list.insertBefore(dragSrc, row.nextSibling);
                    }
                }
            });
        });

        body.querySelector('#source-priority-save').addEventListener('click', async () => {
            const btn = body.querySelector('#source-priority-save');
            const newOrder = [...list.querySelectorAll('.source-priority-row')]
                .map(r => r.dataset.source);
            await saveSettings({ download_source_priority: JSON.stringify(newOrder) }, btn);
        });
    }

    // ── Indexers ───────────────────────────────────────────────────
    const IDX_TYPE_LABELS = {
        prowlarr: 'Prowlarr', torznab: 'Torznab (Direct)', newznab: 'Newznab (Direct)',
    };

    function renderIndexers() {
        return `
            <div class="settings-section-title" style="display:flex;align-items:center;justify-content:space-between">
                Indexers
                <div style="display:flex;gap:8px;align-items:center">
                    <select class="input" id="idx-type-select" style="width:180px;font-size:13px">
                        ${Object.entries(IDX_TYPE_LABELS).map(([v,l]) => `<option value="${v}">${l}</option>`).join('')}
                    </select>
                    <button class="btn btn-sm btn-primary" id="idx-add-btn">+ Add</button>
                </div>
            </div>
            <p style="font-size:.85rem;color:var(--text-dim);margin:0 0 16px">
                Add Prowlarr as a proxy to all your torrent/usenet indexers, or add individual Torznab/Newznab feeds directly.
            </p>
            <div id="idx-list">
                <div style="padding:24px 0;color:var(--text-muted);text-align:center">Loading…</div>
            </div>
            <div id="idx-edit-panel" hidden></div>

            <div class="settings-section-title" style="margin-top:32px;display:flex;align-items:center;justify-content:space-between">
                Prowlarr Indexers
                <button class="btn btn-sm" id="prl-refresh-btn" title="Refresh from Prowlarr">↻ Refresh</button>
            </div>
            <p style="font-size:.85rem;color:var(--text-dim);margin:0 0 12px">
                All indexers configured in Prowlarr. Enable/disable them in Prowlarr — configure audio-capable indexers here for best results.
            </p>
            <div id="prowlarr-indexers-body">
                <div style="padding:16px 0;color:var(--text-muted);text-align:center">Loading…</div>
            </div>`;
    }

    async function bindIndexers() {
        await loadIdxList();
        document.getElementById('idx-add-btn')?.addEventListener('click', () => {
            const type = document.getElementById('idx-type-select')?.value || 'prowlarr';
            showIdxForm(null, type);
        });
        await loadProwlarrIndexers();
        document.getElementById('prl-refresh-btn')?.addEventListener('click', () => loadProwlarrIndexers());
    }

    async function loadProwlarrIndexers() {
        const body = document.getElementById('prowlarr-indexers-body');
        if (!body) return;
        body.innerHTML = `<div style="padding:12px 0;color:var(--text-muted)">Loading from Prowlarr…</div>`;
        try {
            const data = await api.get('/indexers/prowlarr-list');
            if (data.error) {
                body.innerHTML = `<div style="color:var(--text-muted);font-size:.85rem;padding:8px 0">${esc(data.error)}</div>`;
                return;
            }
            const idxs = data.indexers || [];
            if (idxs.length === 0) {
                body.innerHTML = `<div style="color:var(--text-muted);font-size:.85rem;padding:8px 0">No indexers found in Prowlarr.</div>`;
                return;
            }
            body.innerHTML = `
                <div style="font-size:.8rem;color:var(--text-dim);margin-bottom:8px">
                    ${idxs.length} indexers · ${idxs.filter(i => i.enabled).length} enabled ·
                    ${idxs.filter(i => i.has_audio).length} with audio categories
                </div>
                <table class="arr-table" style="width:100%">
                    <thead><tr>
                        <th>Name</th>
                        <th style="width:70px">Protocol</th>
                        <th style="width:70px">Privacy</th>
                        <th style="width:90px">Categories</th>
                        <th style="width:55px;text-align:center">Status</th>
                        <th style="width:70px;text-align:right">Action</th>
                    </tr></thead>
                    <tbody>
                    ${idxs.map(idx => `
                        <tr class="arr-table-row" style="${!idx.enabled ? 'opacity:.55' : ''}">
                            <td style="font-weight:500">
                                ${esc(idx.name)}
                                ${idx.has_audio ? `<span style="font-size:.7rem;color:var(--teal);margin-left:4px">♪ audio</span>` : ''}
                            </td>
                            <td><span style="font-size:.75rem;color:var(--text-muted)">${esc(idx.protocol)}</span></td>
                            <td><span style="font-size:.75rem;color:var(--text-muted)">${esc(idx.privacy)}</span></td>
                            <td style="max-width:90px">
                                <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:.72rem;color:var(--text-muted)" title="${esc((idx.categories||[]).join(', '))}">${esc((idx.categories||[]).slice(0,2).join(', '))}</div>
                            </td>
                            <td style="text-align:center">
                                <span style="font-size:.75rem;color:${idx.enabled ? 'var(--green)' : 'var(--text-muted)'}">
                                    ${idx.enabled ? '● On' : '○ Off'}
                                </span>
                            </td>
                            <td style="text-align:right">
                                <button class="btn-xs prl-test-btn" data-id="${idx.id}" title="Test this indexer">Test</button>
                            </td>
                        </tr>`).join('')}
                    </tbody>
                </table>
                <div style="font-size:.75rem;color:var(--text-muted);margin-top:8px">
                    Enable/disable indexers in Prowlarr's own UI. Changes reflect here after refresh.
                </div>`;

            body.querySelectorAll('.prl-test-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    btn.disabled = true; btn.textContent = '…';
                    try {
                        const r = await api.post(`/indexers/prowlarr-test/${btn.dataset.id}`);
                        toast(r.ok ? `✓ ${r.message}` : `✗ ${r.message}`, r.ok ? 'success' : 'error');
                    } catch(e) { toast('Test failed: ' + e.message, 'error'); }
                    btn.disabled = false; btn.textContent = 'Test';
                });
            });
        } catch(e) {
            body.innerHTML = `<div style="color:var(--red);font-size:.85rem">Failed: ${esc(e.message)}</div>`;
        }
    }

    async function loadIdxList() {
        const list = document.getElementById('idx-list');
        if (!list) return;
        try {
            const indexers = await api.get('/indexers');
            if (indexers.length === 0) {
                list.innerHTML = `<div style="padding:16px 0;color:var(--text-muted)">No indexers configured. Add one above.</div>`;
                return;
            }
            list.innerHTML = `
                <table class="arr-table" style="margin-top:8px">
                    <thead><tr>
                        <th style="width:32px">#</th>
                        <th>Name</th><th>Type</th><th>Status</th>
                        <th style="width:120px">Actions</th>
                    </tr></thead>
                    <tbody>
                    ${indexers.map((idx, i) => `
                        <tr data-idx-id="${idx.id}">
                            <td style="color:var(--text-muted)">${i + 1}</td>
                            <td style="font-weight:500">${esc(idx.name)}</td>
                            <td>${esc(IDX_TYPE_LABELS[idx.type] || idx.type)}</td>
                            <td>
                                <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
                                    <input type="checkbox" class="idx-enabled-cb" data-id="${idx.id}" ${idx.enabled ? 'checked' : ''}>
                                    <span style="font-size:.8rem;color:${idx.enabled ? 'var(--green)' : 'var(--text-muted)'}">${idx.enabled ? 'Enabled' : 'Disabled'}</span>
                                </label>
                            </td>
                            <td style="display:flex;gap:4px;align-items:center">
                                <button class="btn-xs idx-up" data-id="${idx.id}" ${i === 0 ? 'disabled' : ''}>↑</button>
                                <button class="btn-xs idx-down" data-id="${idx.id}" ${i === indexers.length - 1 ? 'disabled' : ''}>↓</button>
                                <button class="btn-xs idx-test" data-id="${idx.id}">Test</button>
                                <button class="btn-xs idx-edit" data-id="${idx.id}">Edit</button>
                                <button class="btn-xs btn-danger idx-del" data-id="${idx.id}">Del</button>
                            </td>
                        </tr>`).join('')}
                    </tbody>
                </table>`;

            const orderedIds = indexers.map(i => i.id);

            list.querySelectorAll('.idx-enabled-cb').forEach(cb => {
                cb.addEventListener('change', async () => {
                    cb.disabled = true;
                    try { await api.put(`/indexers/${cb.dataset.id}`, { enabled: cb.checked ? 1 : 0 }); }
                    catch(e) { toast('Failed: ' + e.message, 'error'); cb.checked = !cb.checked; }
                    cb.disabled = false; await loadIdxList();
                });
            });

            list.querySelectorAll('.idx-up').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const id = parseInt(btn.dataset.id);
                    const idx = orderedIds.indexOf(id);
                    if (idx <= 0) return;
                    [orderedIds[idx-1], orderedIds[idx]] = [orderedIds[idx], orderedIds[idx-1]];
                    await api.post('/indexers/reorder', { ids: orderedIds });
                    await loadIdxList();
                });
            });

            list.querySelectorAll('.idx-down').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const id = parseInt(btn.dataset.id);
                    const idx = orderedIds.indexOf(id);
                    if (idx < 0 || idx >= orderedIds.length - 1) return;
                    [orderedIds[idx], orderedIds[idx+1]] = [orderedIds[idx+1], orderedIds[idx]];
                    await api.post('/indexers/reorder', { ids: orderedIds });
                    await loadIdxList();
                });
            });

            list.querySelectorAll('.idx-test').forEach(btn => {
                btn.addEventListener('click', async () => {
                    btn.disabled = true; btn.textContent = '…';
                    try {
                        const r = await api.post(`/indexers/${btn.dataset.id}/test`);
                        toast(r.ok ? `✓ ${r.message}` : `✗ ${r.message}`, r.ok ? 'success' : 'error');
                    } catch(e) { toast('Test failed: ' + e.message, 'error'); }
                    btn.disabled = false; btn.textContent = 'Test';
                });
            });

            list.querySelectorAll('.idx-edit').forEach(btn => {
                btn.addEventListener('click', () => {
                    const idx = indexers.find(x => x.id == btn.dataset.id);
                    if (idx) showIdxForm(idx, idx.type);
                });
            });

            list.querySelectorAll('.idx-del').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm('Delete this indexer?')) return;
                    btn.disabled = true;
                    try { await api.del(`/indexers/${btn.dataset.id}`); await loadIdxList(); }
                    catch(e) { toast('Delete failed: ' + e.message, 'error'); btn.disabled = false; }
                });
            });
        } catch(e) {
            list.innerHTML = `<div style="color:var(--red)">Failed to load indexers</div>`;
        }
    }

    function showIdxForm(indexer, type) {
        const panel = document.getElementById('idx-edit-panel');
        if (!panel) return;
        panel.hidden = false;
        const isEdit = !!indexer;
        const v = indexer || {};

        panel.innerHTML = `
            <div style="border-top:1px solid var(--border);margin-top:16px;padding-top:16px">
                <div class="settings-section-title" style="margin-bottom:16px">${isEdit ? 'Edit' : 'Add'} ${IDX_TYPE_LABELS[type] || type}</div>
                <div class="form-row">
                    <div class="form-label">Name</div>
                    <div class="form-control"><input class="input" id="idxf-name" value="${esc(v.name || IDX_TYPE_LABELS[type] || '')}"></div>
                </div>
                <div class="form-row">
                    <div class="form-label">${type === 'prowlarr' ? 'Prowlarr URL' : 'Feed URL'}
                        <div class="form-hint">${type === 'prowlarr' ? 'e.g. http://prowlarr:9696' : 'Torznab/Newznab endpoint URL'}</div>
                    </div>
                    <div class="form-control"><input class="input" id="idxf-url" value="${esc(v.url || '')}"></div>
                </div>
                <div class="form-row">
                    <div class="form-label">API Key</div>
                    <div class="form-control"><input class="input" id="idxf-apikey" value="${esc(v.api_key || '')}" placeholder="API key"></div>
                </div>
                <div class="form-row">
                    <div class="form-label"></div>
                    <div class="form-control" style="display:flex;gap:8px">
                        <button class="btn btn-primary" id="idxf-save">Save</button>
                        <button class="btn" id="idxf-cancel">Cancel</button>
                    </div>
                </div>
            </div>`;

        document.getElementById('idxf-cancel').addEventListener('click', () => {
            panel.hidden = true; panel.innerHTML = '';
        });

        document.getElementById('idxf-save').addEventListener('click', async () => {
            const btn = document.getElementById('idxf-save');
            btn.disabled = true; btn.textContent = 'Saving…';
            try {
                const payload = {
                    name: document.getElementById('idxf-name').value.trim(),
                    type,
                    url: document.getElementById('idxf-url').value.trim(),
                    api_key: document.getElementById('idxf-apikey').value.trim(),
                };
                if (isEdit) {
                    await api.put(`/indexers/${indexer.id}`, payload);
                } else {
                    await api.post('/indexers', payload);
                }
                panel.hidden = true; panel.innerHTML = '';
                toast(isEdit ? 'Indexer updated' : 'Indexer added', 'success');
                await loadIdxList();
            } catch(e) {
                toast('Save failed: ' + e.message, 'error');
                btn.disabled = false; btn.textContent = 'Save';
            }
        });
    }

    // ── Release Profiles ───────────────────────────────────────────
    function renderReleaseProfiles() {
        return `
            <div class="settings-section-title">Release Profiles</div>
            <div style="font-size:.85rem;color:var(--text-dim);margin-bottom:16px">
                Filter search results by required/ignored/preferred words. Required words must all appear; ignored words exclude results; preferred words boost the score.
            </div>
            <div id="rp-list">
                <div style="text-align:center;padding:32px 0;color:var(--text-muted)">Loading…</div>
            </div>
            <div style="margin-top:16px">
                <button class="btn btn-primary btn-sm" id="rp-add-btn">+ Add Profile</button>
            </div>
            <div id="rp-form" style="display:none;margin-top:20px;padding:16px;background:var(--bg-raised);border-radius:8px"></div>`;
    }

    async function bindReleaseProfiles() {
        await loadRPList();
        document.getElementById('rp-add-btn')?.addEventListener('click', () => showRPForm(null));
    }

    async function loadRPList() {
        const listEl = document.getElementById('rp-list');
        if (!listEl) return;
        try {
            const profiles = await api.get('/release-profiles');
            if (!profiles.length) {
                listEl.innerHTML = `<div style="color:var(--text-muted);font-size:.875rem">No profiles yet.</div>`;
                return;
            }
            listEl.innerHTML = `
                <table class="arr-table" style="width:100%">
                    <thead><tr>
                        <th>Name</th><th>Required</th><th>Ignored</th><th>Preferred</th><th>Boost</th><th>Default</th><th style="width:100px">Actions</th>
                    </tr></thead>
                    <tbody>
                    ${profiles.map(p => `
                        <tr class="arr-table-row">
                            <td style="font-weight:500">${esc(p.name)}</td>
                            <td style="color:var(--text-dim);font-size:.8rem">${p.required_words ? p.required_words.split(',').filter(w=>w.trim()).length + ' word(s)' : '<span style="color:var(--text-muted)">—</span>'}</td>
                            <td style="color:var(--text-dim);font-size:.8rem">${p.ignored_words ? p.ignored_words.split(',').filter(w=>w.trim()).length + ' word(s)' : '<span style="color:var(--text-muted)">—</span>'}</td>
                            <td style="color:var(--text-dim);font-size:.8rem">${p.preferred_words ? p.preferred_words.split(',').filter(w=>w.trim()).length + ' word(s)' : '<span style="color:var(--text-muted)">—</span>'}</td>
                            <td style="color:var(--text-dim)">${p.score_boost || 0}</td>
                            <td>${p.is_default ? '<span style="color:var(--teal);font-size:.8rem">Default</span>' : ''}</td>
                            <td style="display:flex;gap:4px;align-items:center">
                                <button class="btn-xs rp-edit-btn" data-id="${p.id}">Edit</button>
                                <button class="btn-xs btn-danger rp-del-btn" data-id="${p.id}" data-name="${esc(p.name)}">Del</button>
                            </td>
                        </tr>`).join('')}
                    </tbody>
                </table>`;

            listEl.querySelectorAll('.rp-edit-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const p = profiles.find(x => x.id === parseInt(btn.dataset.id));
                    if (p) showRPForm(p);
                });
            });

            listEl.querySelectorAll('.rp-del-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm(`Delete profile "${btn.dataset.name}"?`)) return;
                    try {
                        await api.del(`/release-profiles/${btn.dataset.id}`);
                        toast('Profile deleted', 'success');
                        await loadRPList();
                    } catch (e) { toast('Delete failed: ' + e.message, 'error'); }
                });
            });
        } catch (e) {
            listEl.innerHTML = `<div style="color:var(--red);font-size:.875rem">Failed to load profiles</div>`;
        }
    }

    function showRPForm(profile) {
        const formEl = document.getElementById('rp-form');
        if (!formEl) return;
        formEl.style.display = 'block';
        formEl.innerHTML = `
            <div style="font-weight:600;margin-bottom:12px">${profile ? 'Edit Profile' : 'New Profile'}</div>
            <div class="form-row">
                <div class="form-label">Name</div>
                <div class="form-control"><input class="input" id="rp-name" value="${esc(profile?.name || '')}"></div>
            </div>
            <div class="form-row">
                <div class="form-label">Required Words
                    <div class="form-hint">All must appear (comma-separated)</div>
                </div>
                <div class="form-control"><input class="input" id="rp-required" value="${esc(profile?.required_words || '')}" placeholder="e.g. FLAC,lossless"></div>
            </div>
            <div class="form-row">
                <div class="form-label">Ignored Words
                    <div class="form-hint">Any match → skip result</div>
                </div>
                <div class="form-control"><input class="input" id="rp-ignored" value="${esc(profile?.ignored_words || '')}" placeholder="e.g. live,karaoke,cover"></div>
            </div>
            <div class="form-row">
                <div class="form-label">Preferred Words
                    <div class="form-hint">Matches boost the score</div>
                </div>
                <div class="form-control"><input class="input" id="rp-preferred" value="${esc(profile?.preferred_words || '')}" placeholder="e.g. remaster,deluxe"></div>
            </div>
            <div class="form-row">
                <div class="form-label">Score Boost
                    <div class="form-hint">Extra points added when preferred words match (0–100)</div>
                </div>
                <div class="form-control"><input class="input" id="rp-boost" type="number" min="0" max="100" value="${profile?.score_boost ?? 0}" style="width:80px"></div>
            </div>
            <div class="form-row">
                <div class="form-label">Default</div>
                <div class="form-control">
                    <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                        <input type="checkbox" id="rp-is-default" ${profile?.is_default ? 'checked' : ''}>
                        Set as default profile
                    </label>
                </div>
            </div>
            <div style="display:flex;gap:8px;margin-top:12px">
                <button class="btn btn-primary btn-sm" id="rp-save-btn">${profile ? 'Save' : 'Create'}</button>
                <button class="btn btn-sm" id="rp-cancel-btn">Cancel</button>
            </div>`;

        document.getElementById('rp-cancel-btn')?.addEventListener('click', () => {
            formEl.style.display = 'none';
        });

        document.getElementById('rp-save-btn')?.addEventListener('click', async () => {
            const btn = document.getElementById('rp-save-btn');
            const name = document.getElementById('rp-name').value.trim();
            if (!name) { toast('Name is required', 'error'); return; }
            btn.disabled = true; btn.textContent = 'Saving…';
            const payload = {
                name,
                required_words:  document.getElementById('rp-required').value.trim(),
                ignored_words:   document.getElementById('rp-ignored').value.trim(),
                preferred_words: document.getElementById('rp-preferred').value.trim(),
                score_boost:     parseInt(document.getElementById('rp-boost').value) || 0,
                is_default:      document.getElementById('rp-is-default').checked,
            };
            try {
                if (profile) {
                    await api.put(`/release-profiles/${profile.id}`, payload);
                } else {
                    await api.post('/release-profiles', payload);
                }
                toast(profile ? 'Profile updated' : 'Profile created', 'success');
                formEl.style.display = 'none';
                await loadRPList();
            } catch (e) {
                toast('Save failed: ' + e.message, 'error');
                btn.disabled = false; btn.textContent = profile ? 'Save' : 'Create';
            }
        });
    }

    // ── System ────────────────────────────────────────────────────
    // ── Metadata Profiles ──────────────────────────────────────────
    function renderMetadataProfiles() {
        return `
            <div class="settings-section-title">Metadata Profiles</div>
            <div style="font-size:.85rem;color:var(--text-dim);margin-bottom:16px">
                Control which release types are monitored per artist (albums, singles, EPs, etc.)
            </div>
            <div id="mp-list">
                <div style="text-align:center;padding:32px 0;color:var(--text-muted)">Loading…</div>
            </div>
            <div style="margin-top:16px">
                <button class="btn btn-primary btn-sm" id="mp-add-btn">+ Add Profile</button>
            </div>
            <div id="mp-form" style="display:none;margin-top:20px;padding:16px;background:var(--bg-raised);border-radius:8px"></div>`;
    }

    async function bindMetadataProfiles() {
        await loadMPList();

        document.getElementById('mp-add-btn')?.addEventListener('click', () => showMPForm(null));
    }

    async function loadMPList() {
        const listEl = document.getElementById('mp-list');
        if (!listEl) return;
        try {
            const profiles = await api.get('/metadata-profiles');
            if (!profiles.length) {
                listEl.innerHTML = `<div style="color:var(--text-muted);font-size:.875rem">No profiles yet.</div>`;
                return;
            }
            listEl.innerHTML = `
                <table class="arr-table" style="width:100%">
                    <thead><tr>
                        <th>Name</th><th>Albums</th><th>Singles</th><th>EPs</th><th>Compilations</th><th>Live</th><th>Default</th><th style="width:100px">Actions</th>
                    </tr></thead>
                    <tbody>
                    ${profiles.map(p => `
                        <tr class="arr-table-row">
                            <td style="font-weight:500">${esc(p.name)}</td>
                            <td>${p.include_albums ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--text-muted)">—</span>'}</td>
                            <td>${p.include_singles ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--text-muted)">—</span>'}</td>
                            <td>${p.include_eps ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--text-muted)">—</span>'}</td>
                            <td>${p.include_compilations ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--text-muted)">—</span>'}</td>
                            <td>${p.include_live ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--text-muted)">—</span>'}</td>
                            <td>${p.is_default ? '<span style="color:var(--teal);font-size:.8rem">Default</span>' : ''}</td>
                            <td style="display:flex;gap:4px;align-items:center">
                                <button class="btn-xs mp-edit-btn" data-id="${p.id}">Edit</button>
                                <button class="btn-xs btn-danger mp-del-btn" data-id="${p.id}" data-name="${esc(p.name)}">Del</button>
                            </td>
                        </tr>`).join('')}
                    </tbody>
                </table>`;

            listEl.querySelectorAll('.mp-edit-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const p = profiles.find(x => x.id === parseInt(btn.dataset.id));
                    if (p) showMPForm(p);
                });
            });

            listEl.querySelectorAll('.mp-del-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm(`Delete profile "${btn.dataset.name}"?`)) return;
                    try {
                        await api.del(`/metadata-profiles/${btn.dataset.id}`);
                        toast('Profile deleted', 'success');
                        await loadMPList();
                    } catch (e) { toast('Delete failed: ' + e.message, 'error'); }
                });
            });
        } catch (e) {
            listEl.innerHTML = `<div style="color:var(--red);font-size:.875rem">Failed to load profiles</div>`;
        }
    }

    function showMPForm(profile) {
        const formEl = document.getElementById('mp-form');
        if (!formEl) return;
        formEl.style.display = 'block';
        formEl.innerHTML = `
            <div style="font-weight:600;margin-bottom:12px">${profile ? 'Edit Profile' : 'New Profile'}</div>
            <div class="form-row">
                <div class="form-label">Name</div>
                <div class="form-control"><input class="input" id="mp-name" value="${esc(profile?.name || '')}"></div>
            </div>
            ${['albums','singles','eps','compilations','live'].map(type => `
            <div class="form-row">
                <div class="form-label">${type.charAt(0).toUpperCase() + type.slice(1)}</div>
                <div class="form-control">
                    <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                        <input type="checkbox" id="mp-${type}" ${(profile ? profile['include_' + type] : (type === 'albums' || type === 'eps')) ? 'checked' : ''}>
                        Include ${type}
                    </label>
                </div>
            </div>`).join('')}
            <div class="form-row">
                <div class="form-label">Default</div>
                <div class="form-control">
                    <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                        <input type="checkbox" id="mp-is-default" ${profile?.is_default ? 'checked' : ''}>
                        Set as default profile
                    </label>
                </div>
            </div>
            <div style="display:flex;gap:8px;margin-top:12px">
                <button class="btn btn-primary btn-sm" id="mp-save-btn">${profile ? 'Save' : 'Create'}</button>
                <button class="btn btn-sm" id="mp-cancel-btn">Cancel</button>
            </div>`;

        document.getElementById('mp-cancel-btn')?.addEventListener('click', () => {
            formEl.style.display = 'none';
        });

        document.getElementById('mp-save-btn')?.addEventListener('click', async () => {
            const btn = document.getElementById('mp-save-btn');
            const name = document.getElementById('mp-name').value.trim();
            if (!name) { toast('Name is required', 'error'); return; }
            btn.disabled = true; btn.textContent = 'Saving…';
            const payload = {
                name,
                include_albums:       document.getElementById('mp-albums').checked,
                include_singles:      document.getElementById('mp-singles').checked,
                include_eps:          document.getElementById('mp-eps').checked,
                include_compilations: document.getElementById('mp-compilations').checked,
                include_live:         document.getElementById('mp-live').checked,
                is_default:           document.getElementById('mp-is-default').checked,
            };
            try {
                if (profile) {
                    await api.put(`/metadata-profiles/${profile.id}`, payload);
                } else {
                    await api.post('/metadata-profiles', payload);
                }
                toast(profile ? 'Profile updated' : 'Profile created', 'success');
                formEl.style.display = 'none';
                await loadMPList();
            } catch (e) {
                toast('Save failed: ' + e.message, 'error');
                btn.disabled = false; btn.textContent = profile ? 'Save' : 'Create';
            }
        });
    }

    function renderSystem() {
        return `
            <div class="settings-section-title">System</div>
            <div class="form-row">
                <div class="form-label">Backend Status</div>
                <div class="form-control" id="health-body" style="font-size:.875rem;color:var(--text-dim)">Checking…</div>
            </div>
            <div class="form-row">
                <div class="form-label">Library Scan
                    <div class="form-hint">Scan your music folder for new files</div>
                </div>
                <div class="form-control">
                    <button class="btn" id="scan-now-btn">Scan Now</button>
                </div>
            </div>
            <div class="form-row">
                <div class="form-label">Release Check
                    <div class="form-hint">Check monitored artists for new releases</div>
                </div>
                <div class="form-control">
                    <button class="btn" id="release-check-btn">Check Now</button>
                </div>
            </div>
            <div class="form-row">
                <div class="form-label">Failed Imports
                    <div class="form-hint">Files that couldn't be imported</div>
                </div>
                <div class="form-control" id="failed-imports-body" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                    <span style="color:var(--text-muted);font-size:.875rem">Loading…</span>
                </div>
            </div>
            <div class="form-row">
                <div class="form-label">Unmatched Files
                    <div class="form-hint">Local tracks with no Spotify match</div>
                </div>
                <div class="form-control" id="unmatched-body" style="font-size:.875rem;color:var(--text-dim)">Loading…</div>
            </div>
            <div class="settings-section-title" style="margin-top:24px">Settings</div>
            <div class="form-row">
                <div class="form-label">Sync Interval
                    <div class="form-hint">Minutes between auto-sync runs</div>
                </div>
                <div class="form-control" style="display:flex;align-items:center;gap:8px">
                    <input class="input" id="sys-sync-interval" type="number" min="5" max="1440" style="width:80px">
                    <span style="color:var(--text-muted)">minutes</span>
                </div>
            </div>
            <div class="form-row">
                <div class="form-label">Account Sync
                    <div class="form-hint">Automatically sync Spotify Liked Songs</div>
                </div>
                <div class="form-control">
                    <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                        <input type="checkbox" id="sys-account-sync">
                        Enable auto-sync
                    </label>
                </div>
            </div>
            <div class="form-row">
                <div class="form-label">Calendar
                    <div class="form-hint">Show the Calendar page in the sidebar</div>
                </div>
                <div class="form-control">
                    <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                        <input type="checkbox" id="sys-calendar-enabled">
                        Enable Calendar
                    </label>
                </div>
            </div>
            <div class="form-row">
                <div class="form-label">Match Threshold
                    <div class="form-hint">Min score (0–100) for auto-match</div>
                </div>
                <div class="form-control" style="display:flex;align-items:center;gap:8px">
                    <input class="input" id="sys-match-threshold" type="number" min="50" max="100" style="width:80px">
                    <span style="color:var(--text-muted)">%</span>
                </div>
            </div>
            <div class="form-row">
                <div class="form-label"></div>
                <div class="form-control">
                    <button class="btn btn-primary" id="sys-save-btn">Save</button>
                </div>
            </div>
            <div class="settings-section-title" style="margin-top:24px">Recent Activity</div>
            <div id="sys-activity-log" style="font-size:.8rem;color:var(--text-dim);max-height:320px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;padding:8px">
                <div style="text-align:center;padding:16px;color:var(--text-muted)">Loading…</div>
            </div>`;
    }

    async function bindSystem() {
        // Health check
        try {
            await api.get('/health');
            const el = document.getElementById('health-body');
            if (el) el.innerHTML = `<span style="color:var(--green)">● Online</span>`;
        } catch {
            const el = document.getElementById('health-body');
            if (el) el.innerHTML = `<span style="color:var(--red)">● Offline</span>`;
        }

        // Load current settings
        try {
            const s = await api.get('/settings');
            const si = document.getElementById('sys-sync-interval');
            const as = document.getElementById('sys-account-sync');
            const mt = document.getElementById('sys-match-threshold');
            const ce = document.getElementById('sys-calendar-enabled');
            if (si) si.value = s.sync_interval_minutes;
            if (as) as.checked = s.account_sync_enabled;
            if (mt) mt.value = s.match_review_threshold;
            if (ce) ce.checked = s.calendar_enabled;
        } catch {}

        // Failed imports stats
        try {
            const fi = await api.get('/library/failed-imports');
            const el = document.getElementById('failed-imports-body');
            if (el) {
                if (!fi.exists || fi.file_count === 0) {
                    el.innerHTML = `<span style="color:var(--text-muted);font-size:.875rem">None</span>`;
                } else {
                    el.innerHTML = `
                        <span style="font-size:.875rem">${fi.file_count} files (${fi.size_gb} GB)</span>
                        <button class="btn btn-sm btn-danger" id="clean-failed-btn">Clean Up</button>`;
                    document.getElementById('clean-failed-btn')?.addEventListener('click', async () => {
                        if (!confirm(`Delete ${fi.file_count} files (${fi.size_gb} GB) from failed_imports?`)) return;
                        const btn = document.getElementById('clean-failed-btn');
                        btn.disabled = true; btn.textContent = 'Cleaning…';
                        try {
                            await api.post('/library/failed-imports/clean');
                            toast('Failed imports cleaned', 'success');
                            const el2 = document.getElementById('failed-imports-body');
                            if (el2) el2.innerHTML = `<span style="color:var(--text-muted);font-size:.875rem">None</span>`;
                        } catch (e) { toast('Clean failed: ' + e.message, 'error'); btn.disabled = false; btn.textContent = 'Clean Up'; }
                    });
                }
            }
        } catch {}

        // Unmatched files
        try {
            const um = await api.get('/library/unmatched?limit=1');
            const el = document.getElementById('unmatched-body');
            if (el) {
                if (um.total === 0) {
                    el.innerHTML = `<span style="color:var(--text-muted)">None</span>`;
                } else {
                    el.innerHTML = `<span>${um.total} unmatched files</span>
                        <button class="btn btn-sm" id="view-unmatched-btn" style="margin-left:8px">View</button>`;
                    document.getElementById('view-unmatched-btn')?.addEventListener('click', async () => {
                        const data = await api.get('/library/unmatched?limit=200');
                        const el2 = document.getElementById('unmatched-body');
                        if (!el2) return;
                        el2.innerHTML = `<div style="margin-top:8px;max-height:300px;overflow-y:auto;border:1px solid var(--border);border-radius:6px">
                            <table class="arr-table" style="width:100%">
                                <thead><tr><th>Artist</th><th>Title</th><th>Album</th><th style="font-size:.75rem">Format</th></tr></thead>
                                <tbody>${data.items.map(t => `<tr class="arr-table-row">
                                    <td style="color:var(--text-dim)">${esc(t.artist||'')}</td>
                                    <td>${esc(t.title||t.path.split('/').pop())}</td>
                                    <td style="color:var(--text-dim)">${esc(t.album||'')}</td>
                                    <td style="color:var(--text-muted);font-size:.75rem">${esc(t.format||'')}</td>
                                </tr>`).join('')}</tbody>
                            </table>
                        </div>`;
                    });
                }
            }
        } catch {}

        // Scan button
        document.getElementById('scan-now-btn')?.addEventListener('click', async () => {
            const btn = document.getElementById('scan-now-btn');
            btn.disabled = true; btn.textContent = 'Scanning…';
            try {
                await api.post('/library/scan');
                toast('Scan started', 'success');
            } catch (e) { toast('Scan failed: ' + e.message, 'error'); }
            setTimeout(() => { if (btn) { btn.disabled = false; btn.textContent = 'Scan Now'; } }, 3000);
        });

        // Release check button
        document.getElementById('release-check-btn')?.addEventListener('click', async () => {
            const btn = document.getElementById('release-check-btn');
            btn.disabled = true; btn.textContent = 'Checking…';
            try {
                await api.post('/release-check/trigger');
                toast('Release check started', 'success');
            } catch (e) { toast('Check failed: ' + e.message, 'error'); }
            setTimeout(() => { if (btn) { btn.disabled = false; btn.textContent = 'Check Now'; } }, 5000);
        });

        // Save button
        document.getElementById('sys-save-btn')?.addEventListener('click', async () => {
            const btn = document.getElementById('sys-save-btn');
            const payload = {
                sync_interval_minutes:  parseInt(document.getElementById('sys-sync-interval').value) || 60,
                account_sync_enabled:   document.getElementById('sys-account-sync').checked,
                match_review_threshold: parseInt(document.getElementById('sys-match-threshold').value) || 75,
                calendar_enabled:       document.getElementById('sys-calendar-enabled')?.checked ?? false,
            };
            await saveSettings(payload, btn);
            if (typeof App !== 'undefined') App.applyCalendarSetting();
        });

        // Activity log
        try {
            const entries = await api.get('/activity?limit=50');
            const el = document.getElementById('sys-activity-log');
            if (el) {
                if (!entries.length) {
                    el.innerHTML = `<div style="text-align:center;padding:16px;color:var(--text-muted)">No recent activity</div>`;
                } else {
                    el.innerHTML = entries.map(e => {
                        const d = new Date(e.created_at + 'Z');
                        const ts = d.toLocaleString();
                        return `<div style="display:flex;gap:8px;padding:4px 0;border-bottom:1px solid var(--border)">
                            <span style="color:var(--text-muted);white-space:nowrap;flex-shrink:0">${esc(ts)}</span>
                            <span style="color:var(--teal);flex-shrink:0">${esc(e.action)}</span>
                            <span style="color:var(--text-dim)">${esc(e.detail || '')}</span>
                        </div>`;
                    }).join('');
                }
            }
        } catch {}
    }

    // ── Notifications (Discord + API Key) ─────────────────────────
    function renderNotifications() {
        return `
            <div class="settings-section-title">Discord Notifications</div>
            <div class="settings-card" id="discord-settings-card">
                <div class="loading-spinner" style="padding:16px;text-align:center">Loading…</div>
            </div>

            <div class="settings-section-title" style="margin-top:32px">API Key</div>
            <div class="settings-card" id="api-key-card">
                <div class="loading-spinner" style="padding:16px;text-align:center">Loading…</div>
            </div>

            <div class="settings-section-title" style="margin-top:32px">Blocklist</div>
            <div class="settings-card" id="blocklist-card">
                <div class="loading-spinner" style="padding:16px;text-align:center">Loading…</div>
            </div>`;
    }

    async function bindNotifications() {
        loadDiscordSettings();
        loadApiKey();
        loadBlocklist();
    }

    async function loadDiscordSettings() {
        const card = document.getElementById('discord-settings-card');
        if (!card) return;
        try {
            const s = await api.get('/settings');
            card.innerHTML = `
                <div class="settings-row">
                    <label class="settings-label">Webhook URL</label>
                    <input class="input" id="discord-webhook-url" placeholder="https://discord.com/api/webhooks/…" value="${esc(s.discord_webhook_url || '')}">
                </div>
                <div class="settings-row" style="margin-top:12px">
                    <label class="settings-label">Notify on</label>
                    <div style="display:flex;flex-direction:column;gap:8px">
                        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                            <input type="checkbox" id="discord-notify-complete" ${s.discord_notify_download_complete ? 'checked' : ''}>
                            Download completed
                        </label>
                        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                            <input type="checkbox" id="discord-notify-release" ${s.discord_notify_new_release ? 'checked' : ''}>
                            New release found
                        </label>
                        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                            <input type="checkbox" id="discord-notify-dispatch" ${s.discord_notify_dispatch ? 'checked' : ''}>
                            Dispatch cycle results
                        </label>
                    </div>
                </div>
                <div style="margin-top:16px;display:flex;gap:8px">
                    <button class="btn btn-primary" id="btn-save-discord">Save</button>
                    <button class="btn" id="btn-test-discord">Test Webhook</button>
                </div>`;

            document.getElementById('btn-save-discord').addEventListener('click', async (e) => {
                await saveSettings({
                    discord_webhook_url: document.getElementById('discord-webhook-url').value.trim(),
                    discord_notify_download_complete: document.getElementById('discord-notify-complete').checked,
                    discord_notify_new_release: document.getElementById('discord-notify-release').checked,
                    discord_notify_dispatch: document.getElementById('discord-notify-dispatch').checked,
                }, e.target);
            });

            document.getElementById('btn-test-discord').addEventListener('click', async (btn) => {
                btn = document.getElementById('btn-test-discord');
                btn.disabled = true; btn.textContent = 'Sending…';
                try {
                    await api.post('/notifications/test-discord');
                    toast('Test sent to Discord!', 'success');
                } catch(e) {
                    toast('Error: ' + e.message, 'error');
                }
                btn.disabled = false; btn.textContent = 'Test Webhook';
            });
        } catch(e) {
            card.innerHTML = `<div style="color:var(--red)">Failed to load settings.</div>`;
        }
    }

    async function loadApiKey() {
        const card = document.getElementById('api-key-card');
        if (!card) return;
        try {
            const r = await api.get('/auth/api-key');
            card.innerHTML = `
                <div style="font-size:13px;color:var(--text-muted);margin-bottom:12px">
                    Use this key to authenticate API calls from external tools.<br>
                    Pass it as <code>X-Api-Key</code> header or <code>?apikey=</code> query param.
                </div>
                <div style="display:flex;gap:8px;align-items:center">
                    <input class="input" id="api-key-display" value="${esc(r.api_key)}" readonly style="font-family:monospace;font-size:12px;flex:1">
                    <button class="btn" id="btn-copy-api-key" title="Copy">Copy</button>
                    <button class="btn btn-danger" id="btn-regen-api-key">Regenerate</button>
                </div>`;

            document.getElementById('btn-copy-api-key').addEventListener('click', () => {
                navigator.clipboard.writeText(r.api_key).then(() => toast('Copied!', 'success'));
            });
            document.getElementById('btn-regen-api-key').addEventListener('click', async () => {
                if (!confirm('Regenerate API key? Existing integrations will break.')) return;
                const res = await api.post('/auth/api-key/regenerate');
                document.getElementById('api-key-display').value = res.api_key;
                toast('API key regenerated', 'success');
            });
        } catch(e) {
            card.innerHTML = `<div style="color:var(--red)">Failed to load API key.</div>`;
        }
    }

    async function loadBlocklist() {
        const card = document.getElementById('blocklist-card');
        if (!card) return;
        try {
            const items = await api.get('/blocklist');
            if (items.length === 0) {
                card.innerHTML = `
                    <div style="color:var(--text-muted);font-size:13px;margin-bottom:12px">
                        No blocklisted items. URLs/hashes here are skipped during auto-dispatch.
                    </div>
                    ${renderAddBlocklistForm()}`;
            } else {
                card.innerHTML = `
                    <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center">
                        <span style="font-size:13px;color:var(--text-muted)">${items.length} blocklisted item${items.length !== 1 ? 's' : ''}</span>
                        <button class="btn btn-xs btn-danger" id="btn-clear-blocklist">Clear All</button>
                    </div>
                    <table class="arr-table" style="margin-bottom:16px">
                        <thead><tr><th style="width:70px">Type</th><th>Value</th><th>Reason</th><th style="width:80px">Date</th><th style="width:50px"></th></tr></thead>
                        <tbody>
                        ${items.map(i => `
                            <tr data-bl-id="${i.id}">
                                <td><span style="font-size:11px;background:var(--surface-alt);padding:2px 6px;border-radius:4px">${esc(i.type)}</span></td>
                                <td style="font-family:monospace;font-size:11px;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(i.value)}">${esc(i.value)}</td>
                                <td style="font-size:12px;color:var(--text-muted)">${esc(i.reason || '')}</td>
                                <td style="font-size:11px;color:var(--text-muted)">${i.added_at ? i.added_at.split('T')[0] : ''}</td>
                                <td><button class="btn btn-xs btn-danger btn-bl-del" data-id="${i.id}">✕</button></td>
                            </tr>`).join('')}
                        </tbody>
                    </table>
                    ${renderAddBlocklistForm()}`;

                card.querySelectorAll('.btn-bl-del').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        btn.disabled = true;
                        try {
                            await api.delete(`/blocklist/${btn.dataset.id}`);
                            btn.closest('tr').remove();
                            toast('Removed from blocklist', 'success');
                        } catch(e) { btn.disabled = false; toast('Error', 'error'); }
                    });
                });

                document.getElementById('btn-clear-blocklist')?.addEventListener('click', async () => {
                    if (!confirm('Clear all blocklist entries?')) return;
                    await api.delete('/blocklist');
                    loadBlocklist();
                    toast('Blocklist cleared', 'success');
                });
            }

            // Wire add form
            document.getElementById('btn-add-blocklist')?.addEventListener('click', async () => {
                const val = document.getElementById('bl-value-input').value.trim();
                const reason = document.getElementById('bl-reason-input').value.trim();
                const type = document.getElementById('bl-type-select').value;
                if (!val) return;
                try {
                    await api.post('/blocklist', { value: val, type, reason });
                    toast('Added to blocklist', 'success');
                    loadBlocklist();
                } catch(e) { toast('Error: ' + e.message, 'error'); }
            });
        } catch(e) {
            card.innerHTML = `<div style="color:var(--red)">Failed to load blocklist.</div>`;
        }
    }

    function renderAddBlocklistForm() {
        return `
            <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap">
                <div style="flex:1;min-width:200px">
                    <label class="settings-label" style="font-size:11px">URL or Hash</label>
                    <input class="input" id="bl-value-input" placeholder="magnet:?xt=… or https://…">
                </div>
                <div>
                    <label class="settings-label" style="font-size:11px">Type</label>
                    <select class="input" id="bl-type-select" style="width:100px">
                        <option value="url">URL</option>
                        <option value="hash">Hash</option>
                        <option value="title">Title</option>
                    </select>
                </div>
                <div style="flex:1;min-width:160px">
                    <label class="settings-label" style="font-size:11px">Reason (optional)</label>
                    <input class="input" id="bl-reason-input" placeholder="Wrong album, bad quality…">
                </div>
                <button class="btn btn-primary" id="btn-add-blocklist">Add</button>
            </div>`;
    }

    // ── Util ──────────────────────────────────────────────────────
    function esc(s) {
        return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function toast(msg, type) {
        if (typeof Notifications !== 'undefined' && Notifications.show) {
            Notifications.show(msg, type);
        } else {
            console.log('[Toast]', msg);
        }
    }

    function unload() {}
    return { load, unload };
})();
