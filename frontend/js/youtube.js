/* YouTube / MeTube integration */

const YouTube = (() => {
  let _reachable = false;

  function init() {
    document.getElementById('yt-download-btn').addEventListener('click', submitDownload);
    document.getElementById('yt-url-input').addEventListener('keydown', e => {
      if (e.key === 'Enter') submitDownload();
    });
    checkStatus();
    loadHistory();
  }

  async function checkStatus() {
    const pill = document.getElementById('yt-status-pill');
    try {
      const data = await api.get('/youtube/status');
      _reachable = data.reachable;
      pill.textContent = _reachable ? 'MeTube connected' : 'MeTube offline';
      pill.className = `yt-status-pill ${_reachable ? 'yt-status-ok' : 'yt-status-err'}`;
    } catch {
      _reachable = false;
      pill.textContent = 'MeTube offline';
      pill.className = 'yt-status-pill yt-status-err';
    }
  }

  async function submitDownload() {
    const url = document.getElementById('yt-url-input').value.trim();
    if (!url) return;
    if (!url.includes('youtube.com') && !url.includes('youtu.be')) {
      toast('Please enter a YouTube URL', 'error');
      return;
    }
    const format = document.getElementById('yt-format-select').value;
    const btn = document.getElementById('yt-download-btn');
    btn.disabled = true;
    btn.textContent = 'Queuing...';
    try {
      await api.post('/youtube/download', { url, audio_format: format });
      toast('YouTube download queued', 'success');
      document.getElementById('yt-url-input').value = '';
      setTimeout(loadHistory, 1500);
    } catch (e) {
      toast('Failed to queue download — is MeTube running?', 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Download';
    }
  }

  async function loadHistory() {
    const list = document.getElementById('yt-history-list');
    try {
      const items = await api.get('/youtube/history');
      if (!items.length) {
        list.innerHTML = '<div class="empty-state" style="font-size:13px">No YouTube downloads yet.</div>';
        return;
      }
      list.innerHTML = items.slice(0, 30).map(item => `
        <div class="download-item yt-download-item">
          <div class="dl-info">
            <span class="dl-title">${esc(item.url)}</span>
            <span class="dl-meta">${item.created_at ? new Date(item.created_at).toLocaleString() : ''}</span>
          </div>
          <span class="dl-status-badge status-${item.status}">${item.status}</span>
        </div>
      `).join('');
    } catch {
      list.innerHTML = '';
    }
  }

  function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  return { init, checkStatus, loadHistory };
})();
