// ─── API Client ──────────────────────────────────────────────────
const API = '/api';

function _check401(res) {
    if (res.status === 401 && typeof App !== 'undefined' && App.showLogin) {
        App.showLogin();
    }
}

const api = {
    async get(path) {
        const res = await fetch(`${API}${path}`);
        if (!res.ok) {
            _check401(res);
            let detail = res.status;
            try { const j = await res.json(); detail = j.detail || detail; } catch {}
            throw new Error(detail);
        }
        return res.json();
    },

    async post(path, body = null) {
        const opts = { method: 'POST', headers: {} };
        if (body) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        const res = await fetch(`${API}${path}`, opts);
        if (!res.ok) { _check401(res); throw new Error(`POST ${path}: ${res.status}`); }
        return res.json();
    },

    async put(path, body) {
        const res = await fetch(`${API}${path}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) { _check401(res); throw new Error(`PUT ${path}: ${res.status}`); }
        return res.json();
    },

    async patch(path, body) {
        const res = await fetch(`${API}${path}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) { _check401(res); throw new Error(`PATCH ${path}: ${res.status}`); }
        return res.json();
    },

    async del(path) {
        const res = await fetch(`${API}${path}`, { method: 'DELETE' });
        if (!res.ok) { _check401(res); throw new Error(`DELETE ${path}: ${res.status}`); }
        return res.json();
    },

    sse(path) {
        return new EventSource(`${API}${path}`);
    },
};

// ─── Toast Notifications ─────────────────────────────────────────
function toast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(8px)';
        el.style.transition = 'all .2s';
        setTimeout(() => el.remove(), 200);
    }, duration);
}

// ─── Helpers ─────────────────────────────────────────────────────
function formatSize(bytes) {
    if (!bytes) return '—';
    if (bytes > 1073741824) return (bytes / 1073741824).toFixed(1) + ' GB';
    if (bytes > 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
    return (bytes / 1024).toFixed(0) + ' KB';
}

function formatDuration(seconds) {
    if (!seconds) return '—';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function statusIcon(status) {
    switch (status) {
        case 'local': return '<span class="status-local" title="In library"><svg class="icon" viewBox="0 0 16 16" width="14" height="14"><path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 0 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z"/></svg></span>';
        case 'downloading': return '<span class="status-downloading" title="Downloading"><span class="spinner"></span></span>';
        case 'failed': return '<span class="status-failed" title="Failed"><svg class="icon" viewBox="0 0 16 16" width="14" height="14"><path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z"/></svg></span>';
        case 'unavailable': return '<span class="status-unavailable" title="Not available on Spotify"><svg class="icon" viewBox="0 0 16 16" width="14" height="14"><path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm6.5-.25a.75.75 0 0 0-1.5 0v.5a.75.75 0 0 0 1.5 0v-.5Zm4-.75a.75.75 0 0 1 .75.75v.5a.75.75 0 0 1-1.5 0v-.5a.75.75 0 0 1 .75-.75ZM5.75 10.5a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5Z"/></svg></span>';
        default: return '<span class="status-available" title="Available"><svg class="icon" viewBox="0 0 16 16" width="14" height="14"><path d="M7.47 10.78a.75.75 0 0 0 1.06 0l3.75-3.75a.75.75 0 0 0-1.06-1.06L8.75 8.44V1.75a.75.75 0 0 0-1.5 0v6.69L4.78 5.97a.75.75 0 0 0-1.06 1.06l3.75 3.75ZM3.75 13a.75.75 0 0 0 0 1.5h8.5a.75.75 0 0 0 0-1.5h-8.5Z"/></svg></span>';
    }
}

function imgUrl(images, size = 56) {
    if (!images || !images.length) return '';
    const sorted = [...images].sort((a, b) => (a.width || 0) - (b.width || 0));
    const img = sorted.find(i => (i.width || 0) >= size) || sorted[sorted.length - 1];
    return img.url;
}

function debounce(fn, ms) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), ms);
    };
}

function timeAgo(dateStr) {
    if (!dateStr) return '';
    const now = new Date();
    const date = new Date(dateStr + (dateStr.includes('Z') || dateStr.includes('+') ? '' : 'Z'));
    const diff = Math.floor((now - date) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

function showSkeleton(container, count = 4) {
    container.innerHTML = Array(count).fill('<div class="skeleton-card"></div>').join('');
}
