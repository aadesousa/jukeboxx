// ─── Duplicates Tab ──────────────────────────────────────────────
const Duplicates = (() => {
    let offset = 0;
    const limit = 10;
    let currentPairId = null;
    function init() {
        document.getElementById('auto-resolve-btn').addEventListener('click', autoResolve);
        document.getElementById('resolve-all-btn').addEventListener('click', resolveAll);

        document.addEventListener('keydown', (e) => {
            if (document.querySelector('#panel-duplicates.active') && currentPairId) {
                if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
                if (e.key === '1') resolve(currentPairId, 'keep_a');
                if (e.key === '2') resolve(currentPairId, 'keep_b');
                if (e.key === '3') resolve(currentPairId, 'keep_both');
                if (e.key === 's' || e.key === 'S') resolve(currentPairId, 'skip');
            }
        });
    }

    async function load() {
        const container = document.getElementById('dup-pairs');
        const pagination = document.getElementById('dup-pagination');
        showSkeleton(container, 3);

        try {
            const [data, stats] = await Promise.all([
                api.get(`/duplicates?offset=${offset}&limit=${limit}`),
                api.get('/duplicates/stats'),
            ]);

            const badge = document.getElementById('duplicates-badge');
            const pending = stats.pending || 0;
            if (pending > 0) {
                badge.textContent = pending;
                badge.hidden = false;
            } else {
                badge.hidden = true;
            }

            document.getElementById('dup-stats').textContent = `${pending} pending`;

            const pairs = data.pairs || [];
            if (!pairs.length) {
                container.innerHTML = '<div class="empty-state">No duplicate pairs to review</div>';
                pagination.innerHTML = '';
                return;
            }

            currentPairId = pairs[0].id;

            container.innerHTML = pairs.map((pair, i) => renderPair(pair, i === 0)).join('');
            attachHandlers(container);

            const total = data.total || 0;
            if (total > limit) {
                const pages = Math.ceil(total / limit);
                const current = Math.floor(offset / limit);
                let html = '';
                if (current > 0) html += `<button class="btn btn-sm page-btn" data-offset="${(current - 1) * limit}">&larr;</button>`;
                html += `<span class="page-info">${current + 1} / ${pages}</span>`;
                if (current < pages - 1) html += `<button class="btn btn-sm page-btn" data-offset="${(current + 1) * limit}">&rarr;</button>`;
                pagination.innerHTML = html;
                pagination.querySelectorAll('.page-btn').forEach(btn => {
                    btn.addEventListener('click', () => { offset = parseInt(btn.dataset.offset); load(); });
                });
            } else {
                pagination.innerHTML = '';
            }
        } catch (err) {
            container.innerHTML = `<div class="empty-state">${err.message}</div>`;
        }
    }

    function qualityScore(t) {
        return ((t.bitrate || 0) * 1000) + (t.size || 0) + ((t.duration || 0) * 10);
    }

    function renderPair(pair, isFirst) {
        let a = pair.track_a || {};
        let b = pair.track_b || {};
        // Ensure higher quality track is always on the left
        let keepLeft = 'keep_a', keepRight = 'keep_b';
        if (qualityScore(b) > qualityScore(a)) {
            [a, b] = [b, a];
            [keepLeft, keepRight] = ['keep_b', 'keep_a'];
        }
        const aBetter = (a.bitrate || 0) > (b.bitrate || 0);
        const bBetter = (b.bitrate || 0) > (a.bitrate || 0);

        return `<div class="dup-pair${isFirst ? ' active-pair' : ''}" data-pair-id="${pair.id}">
            <div class="dup-track">
                <h4>${a.title || 'Unknown'}</h4>
                <div class="dup-meta">
                    <span>Artist: ${a.artist || '—'}</span>
                    <span>Album: ${a.album || '—'}</span>
                    <span>Format: ${a.format || '—'}</span>
                    <span class="${aBetter ? 'better' : ''}">Bitrate: ${a.bitrate ? a.bitrate + ' kbps' : '—'}</span>
                    <span class="${(a.size || 0) > (b.size || 0) ? 'better' : ''}">Size: ${formatSize(a.size)}</span>
                    <span>Duration: ${formatDuration(a.duration)}</span>
                </div>
                <div class="dup-path">${a.path || ''}</div>
            </div>
            <div class="dup-actions">
                <span class="dup-match-type ${pair.match_type}">${pair.match_type} ${pair.similarity_score ? Math.round(pair.similarity_score) + '%' : ''}</span>
                <button class="btn btn-sm btn-green resolve-btn" data-pair="${pair.id}" data-action="${keepLeft}">Keep Left (1)</button>
                <button class="btn btn-sm btn-green resolve-btn" data-pair="${pair.id}" data-action="${keepRight}">Keep Right (2)</button>
                <button class="btn btn-sm resolve-btn" data-pair="${pair.id}" data-action="keep_both">Keep Both (3)</button>
                <button class="btn btn-sm resolve-btn" data-pair="${pair.id}" data-action="skip">Skip (S)</button>
            </div>
            <div class="dup-track">
                <h4>${b.title || 'Unknown'}</h4>
                <div class="dup-meta">
                    <span>Artist: ${b.artist || '—'}</span>
                    <span>Album: ${b.album || '—'}</span>
                    <span>Format: ${b.format || '—'}</span>
                    <span class="${bBetter ? 'better' : ''}">Bitrate: ${b.bitrate ? b.bitrate + ' kbps' : '—'}</span>
                    <span class="${(b.size || 0) > (a.size || 0) ? 'better' : ''}">Size: ${formatSize(b.size)}</span>
                    <span>Duration: ${formatDuration(b.duration)}</span>
                </div>
                <div class="dup-path">${b.path || ''}</div>
            </div>
        </div>`;
    }

    function attachHandlers(container) {
        container.querySelectorAll('.resolve-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                resolve(parseInt(btn.dataset.pair), btn.dataset.action);
            });
        });
        container.querySelectorAll('.dup-pair').forEach(pair => {
            pair.addEventListener('click', () => {
                container.querySelectorAll('.dup-pair').forEach(p => p.classList.remove('active-pair'));
                pair.classList.add('active-pair');
                currentPairId = parseInt(pair.dataset.pairId);
            });
        });
    }

    async function resolve(pairId, action) {
        try {
            await api.post(`/duplicates/${pairId}/resolve`, { action });
            const el = document.querySelector(`[data-pair-id="${pairId}"]`);
            if (el) {
                el.style.opacity = '0';
                el.style.transform = 'scale(.98)';
                el.style.transition = 'all .25s';
                setTimeout(() => { el.remove(); }, 250);
            }
            toast(`Resolved: ${action.replace('_', ' ')}`, 'success');
            const next = document.querySelector('.dup-pair:not([style])');
            if (next) {
                next.classList.add('active-pair');
                currentPairId = parseInt(next.dataset.pairId);
            } else {
                currentPairId = null;
                setTimeout(load, 500);
            }
        } catch (err) { toast(err.message, 'error'); }
    }

    async function autoResolve() {
        if (!confirm('Auto-resolve all duplicates with 95%+ similarity? This will keep the higher-quality version.')) return;
        try {
            const result = await api.post('/duplicates/auto-resolve');
            toast(`Auto-resolved ${result.resolved} pairs`, 'success');
            load();
        } catch (err) { toast(err.message, 'error'); }
    }

    async function resolveAll() {
        if (!confirm('Resolve ALL remaining duplicates? This keeps the higher-quality version for every pair.')) return;
        try {
            const result = await api.post('/duplicates/resolve-all');
            toast(`Resolved ${result.resolved} pairs`, 'success');
            load();
        } catch (err) { toast(err.message, 'error'); }
    }

    return { init, load };
})();
