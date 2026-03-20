/* Wanted Tab — artist/album monitoring */

const Wanted = (() => {
  let _currentView = 'artists';
  let _artists = [];

  // ── Init ──────────────────────────────────────────────────────────────
  function init() {
    document.querySelectorAll('[data-wanted-view]').forEach(btn => {
      btn.addEventListener('click', () => switchView(btn.dataset.wantedView));
    });

    document.getElementById('add-wanted-artist-btn').addEventListener('click', openModal);
    document.getElementById('wanted-modal-close').addEventListener('click', closeModal);
    document.getElementById('wanted-modal-backdrop').addEventListener('click', closeModal);

    document.getElementById('wanted-artist-search-btn').addEventListener('click', searchArtists);
    document.getElementById('wanted-artist-search').addEventListener('keydown', e => {
      if (e.key === 'Enter') searchArtists();
    });

    document.getElementById('wanted-albums-filter').addEventListener('change', renderAlbums);
  }

  // ── View switching ────────────────────────────────────────────────────
  function switchView(view) {
    _currentView = view;
    document.querySelectorAll('[data-wanted-view]').forEach(b =>
      b.classList.toggle('active', b.dataset.wantedView === view)
    );
    document.querySelectorAll('.wanted-view').forEach(v =>
      v.classList.toggle('active', v.id === `wanted-${view}-view`)
    );
    if (view === 'artists') loadArtists();
    else loadAlbums();
  }

  // ── Load artists ──────────────────────────────────────────────────────
  async function loadArtists() {
    const list = document.getElementById('wanted-artists-list');
    list.innerHTML = '<div class="loading-state">Loading...</div>';
    try {
      const artists = await api.get('/wanted/artists');
      _artists = artists;
      renderArtists(artists);
      updateBadge();
    } catch (e) {
      list.innerHTML = '<div class="empty-state">Failed to load wanted artists.</div>';
    }
  }

  function renderArtists(artists) {
    const list = document.getElementById('wanted-artists-list');
    if (!artists.length) {
      list.innerHTML = '<div class="empty-state">No artists in Wanted list. Click "+ Add Artist" to get started.</div>';
      return;
    }
    list.innerHTML = artists.map(a => {
      const albumStats = a.album_stats || {};
      const wantedCount = albumStats.wanted || 0;
      const haveCount = albumStats.have || 0;
      const totalCount = Object.values(albumStats).reduce((s, n) => s + n, 0);
      const coveragePct = totalCount ? Math.round(haveCount / totalCount * 100) : 0;
      const genres = (a.genres || []).slice(0, 3).join(', ');
      return `
        <div class="wanted-artist-card" data-spotify-id="${a.spotify_id}">
          ${a.image_url ? `<img class="wanted-artist-img" src="${a.image_url}" alt="">` : '<div class="wanted-artist-img-placeholder"></div>'}
          <div class="wanted-artist-info">
            <div class="wanted-artist-name">${esc(a.name)}</div>
            ${genres ? `<div class="wanted-artist-genres">${esc(genres)}</div>` : ''}
            <div class="wanted-artist-stats">
              <span class="wanted-stat">${totalCount} albums</span>
              <span class="wanted-stat wanted-missing">${wantedCount} missing</span>
              <span class="wanted-coverage">${coveragePct}% have</span>
            </div>
          </div>
          <div class="wanted-artist-actions">
            <label class="toggle-label" title="Monitor new releases">
              <input type="checkbox" class="monitor-toggle" ${a.monitor_new_albums ? 'checked' : ''}
                data-spotify-id="${a.spotify_id}">
              <span class="toggle-track"></span>
              Monitor
            </label>
            <button class="btn btn-sm" onclick="Wanted.viewArtistAlbums('${a.spotify_id}')">Albums</button>
            <button class="btn btn-sm btn-danger" onclick="Wanted.removeArtist('${a.spotify_id}', '${esc(a.name)}')">Remove</button>
          </div>
        </div>`;
    }).join('');

    // Attach monitor toggle listeners
    list.querySelectorAll('.monitor-toggle').forEach(chk => {
      chk.addEventListener('change', async () => {
        await api.patch(`/wanted/artists/${chk.dataset.spotifyId}`, {
          monitor_new_albums: chk.checked
        });
      });
    });
  }

  // ── Load albums ───────────────────────────────────────────────────────
  async function loadAlbums(artistSpotifyId = null) {
    const list = document.getElementById('wanted-albums-list');
    list.innerHTML = '<div class="loading-state">Loading...</div>';
    const filter = document.getElementById('wanted-albums-filter').value;
    const params = new URLSearchParams();
    if (artistSpotifyId) params.set('artist_spotify_id', artistSpotifyId);
    if (filter) params.set('status', filter);
    try {
      const albums = await api.get(`/wanted/albums?${params}`);
      renderAlbumsData(albums);
    } catch {
      list.innerHTML = '<div class="empty-state">Failed to load albums.</div>';
    }
  }

  async function renderAlbums() {
    await loadAlbums();
  }

  function renderAlbumsData(albums) {
    const list = document.getElementById('wanted-albums-list');
    if (!albums.length) {
      list.innerHTML = '<div class="empty-state">No albums match the current filter.</div>';
      return;
    }
    list.innerHTML = albums.map(alb => {
      const statusClass = { wanted: 'status-missing', have: 'status-have', ignored: 'status-ignored' }[alb.status] || '';
      const statusLabel = { wanted: 'Missing', have: 'Have', ignored: 'Ignored' }[alb.status] || alb.status;
      return `
        <div class="wanted-album-row" data-spotify-id="${alb.spotify_id}">
          ${alb.image_url ? `<img class="wanted-album-img" src="${alb.image_url}" alt="">` : '<div class="wanted-album-img-placeholder"></div>'}
          <div class="wanted-album-info">
            <div class="wanted-album-name">${esc(alb.name)}</div>
            <div class="wanted-album-meta">${alb.album_type || ''} · ${alb.release_date ? alb.release_date.slice(0,4) : ''} · ${alb.track_count} tracks</div>
          </div>
          <div class="wanted-album-actions">
            <span class="status-pill ${statusClass}">${statusLabel}</span>
            ${alb.status === 'wanted' ? `<button class="btn btn-sm btn-accent" onclick="Wanted.downloadAlbum('${alb.spotify_id}')">Download</button>` : ''}
            <select class="yt-format-select album-status-select" data-spotify-id="${alb.spotify_id}">
              <option value="wanted" ${alb.status==='wanted'?'selected':''}>Missing</option>
              <option value="have" ${alb.status==='have'?'selected':''}>Have</option>
              <option value="ignored" ${alb.status==='ignored'?'selected':''}>Ignore</option>
            </select>
          </div>
        </div>`;
    }).join('');

    list.querySelectorAll('.album-status-select').forEach(sel => {
      sel.addEventListener('change', async () => {
        await api.patch(`/wanted/albums/${sel.dataset.spotifyId}`, { status: sel.value });
        loadAlbums();
      });
    });
  }

  // ── Badge ─────────────────────────────────────────────────────────────
  async function updateBadge() {
    try {
      const data = await api.get('/wanted/missing');
      const badge = document.getElementById('wanted-badge');
      const count = data.missing_albums || 0;
      badge.textContent = count;
      badge.hidden = count === 0;
    } catch {}
  }

  // ── Modal: search Spotify artists ─────────────────────────────────────
  function openModal() {
    document.getElementById('wanted-search-modal').hidden = false;
    document.getElementById('wanted-artist-search').value = '';
    document.getElementById('wanted-artist-results').innerHTML = '';
    document.getElementById('wanted-artist-search').focus();
  }

  function closeModal() {
    document.getElementById('wanted-search-modal').hidden = true;
  }

  async function searchArtists() {
    const q = document.getElementById('wanted-artist-search').value.trim();
    if (!q) return;
    const resultsEl = document.getElementById('wanted-artist-results');
    resultsEl.innerHTML = '<div class="loading-state">Searching...</div>';
    try {
      const data = await api.get(`/spotify/search?q=${encodeURIComponent(q)}&type=artist&limit=10`);
      const artists = data?.artists?.items || [];
      if (!artists.length) {
        resultsEl.innerHTML = '<div class="empty-state">No artists found.</div>';
        return;
      }
      resultsEl.innerHTML = artists.map(a => {
        const img = a.images?.[0]?.url || '';
        const genres = (a.genres || []).slice(0, 2).join(', ');
        return `
          <div class="artist-result-row">
            ${img ? `<img class="artist-result-img" src="${img}" alt="">` : '<div class="artist-result-img-placeholder"></div>'}
            <div class="artist-result-info">
              <div class="artist-result-name">${esc(a.name)}</div>
              ${genres ? `<div class="artist-result-genres">${esc(genres)}</div>` : ''}
            </div>
            <button class="btn btn-sm btn-accent" onclick="Wanted.addArtist(${JSON.stringify(a).replace(/"/g,'&quot;')})">Add</button>
          </div>`;
      }).join('');
    } catch (e) {
      resultsEl.innerHTML = '<div class="empty-state">Search failed. Is Spotify connected?</div>';
    }
  }

  // ── Add artist ────────────────────────────────────────────────────────
  async function addArtist(artistObj) {
    try {
      await api.post('/wanted/artists', {
        spotify_id: artistObj.id,
        name: artistObj.name,
        image_url: artistObj.images?.[0]?.url || null,
        genres: artistObj.genres || [],
        monitor_new_albums: true,
      });

      // Fetch and bulk-add their albums
      try {
        const albumData = await api.get(`/spotify/artist/${artistObj.id}/albums`);
        const albums = albumData?.items || albumData || [];
        if (albums.length) {
          const bulkPayload = albums.map(alb => ({
            spotify_id: alb.id,
            artist_spotify_id: artistObj.id,
            name: alb.name,
            album_type: alb.album_type,
            release_date: alb.release_date,
            track_count: alb.total_tracks || 0,
            image_url: alb.images?.[0]?.url || null,
          }));
          await api.post('/wanted/albums/bulk', bulkPayload);
        }
      } catch (e) {
        // Non-fatal — artist added, albums can be fetched later
        console.warn('Could not fetch artist albums:', e);
      }

      toast(`${artistObj.name} added to Wanted`, 'success');
      closeModal();
      loadArtists();
    } catch (e) {
      toast('Failed to add artist', 'error');
    }
  }

  async function removeArtist(spotifyId, name) {
    if (!confirm(`Remove ${name} from Wanted? All tracked albums will also be removed.`)) return;
    try {
      await api.del(`/wanted/artists/${spotifyId}`);
      toast(`${name} removed from Wanted`, 'info');
      loadArtists();
    } catch {
      toast('Failed to remove artist', 'error');
    }
  }

  function viewArtistAlbums(artistSpotifyId) {
    switchView('albums');
    loadAlbums(artistSpotifyId);
  }

  async function downloadAlbum(albumSpotifyId) {
    // Queue entire album via Spotizerr (uses playlist/album endpoint)
    try {
      await api.post(`/downloads/playlist/${albumSpotifyId}`);
      toast('Album queued for download', 'success');
    } catch {
      toast('Failed to queue album', 'error');
    }
  }

  // ── On tab activate ───────────────────────────────────────────────────
  function onActivate() {
    if (_currentView === 'artists') loadArtists();
    else loadAlbums();
    updateBadge();
  }

  function load() {
    onActivate();
  }

  function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  return { init, load, onActivate, addArtist, removeArtist, viewArtistAlbums, downloadAlbum, updateBadge };
})();
