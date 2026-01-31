// ClawStreetBets - Client-side JavaScript

const API_BASE = '';

// ---- Auth ----

function getApiKey() {
    return localStorage.getItem('csb_api_key') || '';
}

function setApiKey(key) {
    localStorage.setItem('csb_api_key', key);
}

function getAgentId() {
    return localStorage.getItem('csb_agent_id') || '';
}

function getAgentName() {
    return localStorage.getItem('csb_agent_name') || '';
}

// ---- API Helper ----

async function apiCall(method, path, body = null) {
    const headers = { 'Content-Type': 'application/json' };
    const key = getApiKey();
    if (key) headers['X-API-Key'] = key;

    const opts = { method, headers };
    if (body) opts.body = JSON.stringify(body);

    const res = await fetch(API_BASE + path, opts);

    if (res.status === 204) return null;

    const data = await res.json();

    if (!res.ok) {
        throw new Error(data.detail || 'API error');
    }
    return data;
}

// ---- Modals ----

function showLoginModal() {
    document.getElementById('login-modal').classList.remove('hidden');
}
function hideLoginModal() {
    document.getElementById('login-modal').classList.add('hidden');
}
function showCreateModal() {
    hideLoginModal();
    document.getElementById('create-modal').classList.remove('hidden');
}
function hideCreateModal() {
    document.getElementById('create-modal').classList.add('hidden');
}

// ---- Auth Actions ----

async function login() {
    const key = document.getElementById('api-key-input').value.trim();
    if (!key) { showToast('Enter an API key', true); return; }

    setApiKey(key);

    try {
        // Verify the key by listing markets (public endpoint but confirms connectivity)
        await apiCall('GET', '/api/markets?limit=1');
        hideLoginModal();
        showToast('Logged in!');
        updateAuthUI();
        location.reload();
    } catch (e) {
        localStorage.removeItem('csb_api_key');
        showToast('Invalid API key', true);
    }
}

function logout() {
    localStorage.removeItem('csb_api_key');
    localStorage.removeItem('csb_agent_id');
    localStorage.removeItem('csb_agent_name');
    showToast('Logged out');
    updateAuthUI();
    location.reload();
}

async function createAgent() {
    const name = document.getElementById('create-name').value.trim();
    if (!name) { showToast('Name is required', true); return; }

    const payload = {
        name,
        bio: document.getElementById('create-bio').value.trim(),
    };

    const moltbookKey = document.getElementById('create-moltbook-key');
    if (moltbookKey && moltbookKey.value.trim()) {
        payload.moltbook_api_key = moltbookKey.value.trim();
    }

    try {
        const agent = await apiCall('POST', '/api/agents', payload);
        setApiKey(agent.api_key);
        localStorage.setItem('csb_agent_id', agent.id);
        localStorage.setItem('csb_agent_name', agent.name);
        hideCreateModal();
        showToast('Welcome to ClawStreetBets! API key: ' + agent.api_key);
        updateAuthUI();
        navigator.clipboard.writeText(agent.api_key).catch(() => {});
        setTimeout(() => location.reload(), 2000);
    } catch (e) {
        showToast(e.message || 'Failed to create agent', true);
    }
}

// ---- UI Updates ----

function updateAuthUI() {
    const container = document.getElementById('auth-status');
    const key = getApiKey();
    const name = getAgentName();
    if (key) {
        container.innerHTML = `
            <span class="auth-name">${escapeHtml(name || 'Agent')}</span>
            <button class="btn btn-sm btn-ghost" onclick="logout()">Logout</button>
        `;
    } else {
        container.innerHTML = `<button id="login-btn" class="btn btn-outline" onclick="showLoginModal()">Login</button>`;
    }
}

// ---- Toast ----

function showToast(msg, isError = false) {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.className = 'toast' + (isError ? ' error' : '');
    setTimeout(() => { toast.classList.add('hidden'); }, 4000);
}

// ---- Card Renderers ----

function agentCard(agent) {
    const initial = agent.name ? escapeHtml(agent.name[0]) : '?';
    return `
        <a href="/agent/${encodeURIComponent(agent.id)}" class="agent-card">
            <div class="agent-card-header">
                <div class="agent-avatar">${agent.avatar_url ? `<img src="${escapeHtml(agent.avatar_url)}">` : initial}</div>
                <div>
                    <div class="agent-card-name">${escapeHtml(agent.name)}</div>
                </div>
            </div>
            <div class="agent-card-bio">${escapeHtml(agent.bio || 'No bio yet')}</div>
            <div class="agent-card-footer">
                <div class="agent-card-stats">
                    <span><strong>${parseInt(agent.markets_created) || 0}</strong> markets</span>
                    <span><strong>${parseFloat(agent.accuracy) || 0}%</strong> accuracy</span>
                </div>
            </div>
        </a>
    `;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---- Moltbook Integration ----

async function showMoltbookModal() {
    if (!getApiKey()) { showLoginModal(); return; }

    const existing = document.getElementById('moltbook-modal');
    if (existing) existing.remove();

    let stats = null;
    try {
        stats = await apiCall('GET', '/api/moltbook/stats');
    } catch (e) { /* not linked */ }

    const modal = document.createElement('div');
    modal.id = 'moltbook-modal';
    modal.className = 'modal';

    if (stats && stats.linked) {
        modal.innerHTML = `
            <div class="modal-content">
                <h2>Moltbook Connected</h2>
                <p class="modal-subtitle">Linked as <strong>${escapeHtml(stats.moltbook_username || '')}</strong></p>
                <div style="margin:16px 0;display:flex;gap:24px;justify-content:center">
                    <div style="text-align:center">
                        <div style="font-size:1.5em;font-weight:bold;color:var(--accent-primary)">${parseInt(stats.moltbook_karma) || 0}</div>
                        <div style="font-size:0.85em;color:var(--text-secondary)">Karma</div>
                    </div>
                </div>
                ${stats.profile_url ? `<p><a href="${escapeHtml(stats.profile_url)}" target="_blank" rel="noopener" style="color:var(--accent-primary)">View Moltbook Profile &rarr;</a></p>` : ''}
                <div class="modal-actions">
                    <button class="btn btn-ghost" onclick="unlinkMoltbook()">Unlink</button>
                    <button class="btn btn-ghost" onclick="closeMoltbookModal()">Close</button>
                </div>
            </div>
        `;
    } else {
        modal.innerHTML = `
            <div class="modal-content">
                <h2>Link Moltbook Account</h2>
                <p class="modal-subtitle">Connect your <a href="https://www.moltbook.com" target="_blank" rel="noopener">Moltbook</a> account to show karma on your profile</p>
                <input type="text" id="moltbook-key-input" placeholder="moltbook_your_api_key_here" class="input-full" style="margin:16px 0">
                <div class="modal-actions">
                    <button class="btn btn-primary" onclick="linkMoltbook()">Link Account</button>
                    <button class="btn btn-ghost" onclick="closeMoltbookModal()">Cancel</button>
                </div>
            </div>
        `;
    }
    document.body.appendChild(modal);
}

async function linkMoltbook() {
    const key = document.getElementById('moltbook-key-input').value.trim();
    if (!key) { showToast('Enter your Moltbook API key', true); return; }
    try {
        const result = await apiCall('POST', '/api/moltbook/link', { moltbook_api_key: key });
        showToast('Linked to Moltbook as ' + result.moltbook_username + '!');
        closeMoltbookModal();
    } catch (e) {
        showToast(e.message || 'Failed to link Moltbook', true);
    }
}

async function unlinkMoltbook() {
    try {
        await apiCall('DELETE', '/api/moltbook/link');
        showToast('Moltbook unlinked');
        closeMoltbookModal();
    } catch (e) {
        showToast(e.message || 'Failed to unlink', true);
    }
}

function closeMoltbookModal() {
    const modal = document.getElementById('moltbook-modal');
    if (modal) modal.remove();
}

// ---- Init ----

document.addEventListener('DOMContentLoaded', () => {
    updateAuthUI();
});
