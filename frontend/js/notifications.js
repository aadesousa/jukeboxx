// ─── Notification Center ─────────────────────────────────────────
const Notifications = (() => {
    let pollInterval = null;
    let isOpen = false;

    const icons = {
        scan_complete:      '🔍',
        sync_complete:      '🔄',
        download_complete:  '✅',
        download_failed:    '❌',
        new_release:        '🎵',
        hash_complete:      '#️⃣',
    };

    function init() {
        const btn      = document.getElementById('notif-btn');
        const dropdown = document.getElementById('notif-dropdown');
        const wrap     = document.getElementById('notif-wrap');

        btn.addEventListener('click', e => {
            e.stopPropagation();
            isOpen = !isOpen;
            dropdown.hidden = !isOpen;
            if (isOpen) loadNotifications();
        });

        document.addEventListener('click', e => {
            if (!wrap.contains(e.target)) {
                isOpen = false;
                dropdown.hidden = true;
            }
        });

        document.getElementById('notif-read-all').addEventListener('click', async () => {
            try {
                await api.post('/notifications/read-all');
                updateCount();
                loadNotifications();
            } catch {}
        });

        pollInterval = setInterval(updateCount, 30000);
        updateCount();
    }

    async function updateCount() {
        try {
            const data  = await api.get('/notifications?unread=true');
            const count = data.length;
            const badge = document.getElementById('notif-badge');
            badge.textContent = count > 99 ? '99+' : count;
            badge.hidden = count === 0;
        } catch {}
    }

    async function loadNotifications() {
        const list = document.getElementById('notif-list');
        try {
            const data = await api.get('/notifications?limit=20');
            if (!data.length) {
                list.innerHTML = '<div class="notif-empty">No notifications yet</div>';
                return;
            }
            list.innerHTML = data.map(n => {
                const icon   = icons[n.type] || 'ℹ️';
                const unread = n.read === 0 ? ' unread' : '';
                return `<div class="notif-item${unread}" data-id="${n.id}">
                    <span class="notif-icon">${icon}</span>
                    <div class="notif-body">
                        <div class="notif-title">${esc(n.title)}</div>
                        ${n.message ? `<div style="font-size:.75rem;color:var(--text-dim);margin-top:2px">${esc(n.message)}</div>` : ''}
                        <div class="notif-time">${timeAgo(n.created_at)}</div>
                    </div>
                </div>`;
            }).join('');

            list.querySelectorAll('.notif-item.unread').forEach(item => {
                item.addEventListener('click', async () => {
                    try {
                        await api.post(`/notifications/${item.dataset.id}/read`);
                        item.classList.remove('unread');
                        updateCount();
                    } catch {}
                });
            });
        } catch {
            list.innerHTML = '<div class="notif-empty">Could not load notifications</div>';
        }
    }

    function destroy() {
        if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
    }

    return { init, updateCount, destroy };
})();
