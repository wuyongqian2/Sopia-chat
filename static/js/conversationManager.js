/**
 * conversationManager.js — 对话管理（CRUD / 搜索 / Token 估算 / 滑动窗口）
 * 依赖：state.js (STATE, DOM), utils.js (escapeHtml, showToast, generateId, formatDate, scrollToBottom)
 */

// ============================================================
// 配置管理
// ============================================================

async function loadConfig() {
    try {
        const resp = await fetchWithTimeout('/api/config');
        STATE.config = await resp.json();
        STATE.settings.theme = STATE.config.settings?.theme || 'dark';
        STATE.settings.skin = STATE.config.settings?.skin || 'classic';
        STATE.settings.context_messages = STATE.config.settings?.context_messages || 20;
        applyTheme(STATE.settings.theme);
        applySkin(STATE.settings.skin);
    } catch (e) {
        console.warn('加载配置失败:', e.message);
    }
}
window.loadConfig = loadConfig;

async function saveProviderConfig(providerKey, authData) {
    const resp = await fetchWithTimeout('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: providerKey, auth: authData })
    });
    const result = await resp.json();
    if (!result.success) {
        throw new Error(result.error || '保存失败');
    }
}
window.saveProviderConfig = saveProviderConfig;

async function saveSettings(settingsData) {
    await fetchWithTimeout('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: settingsData })
    });
}
window.saveSettings = saveSettings;

// ============================================================
// 服务商 & 模型
// ============================================================

async function loadProviders() {
    try {
        const resp = await fetchWithTimeout('/api/providers');
        STATE.providers = await resp.json();
        const cfgResp = await fetchWithTimeout('/api/config');
        STATE.config = await cfgResp.json();
        renderProviderSelect();
        updateInputState();
    } catch (e) {
        console.error('加载服务商列表失败:', e);
        DOM.providerSelect.innerHTML = '<option value="">加载失败 - 点击重试</option>';
        DOM.providerSelect.onclick = () => { loadProviders(); };
    }
}
window.loadProviders = loadProviders;

function renderProviderSelect() {
    DOM.providerSelect.innerHTML = '<option value="">-- 选择服务商 --</option>';
    STATE.providers.forEach(p => {
        const configured = STATE.config?.providers?.[p.key]?.api_key_set || false;
        DOM.providerSelect.innerHTML += `<option value="${p.key}">${configured ? '✓ ' : ''}${p.name}</option>`;
    });

    if (STATE.activeProvider) {
        DOM.providerSelect.value = STATE.activeProvider;
        onProviderChange();
    }
}
window.renderProviderSelect = renderProviderSelect;

function onProviderChange() {
    const key = DOM.providerSelect.value;
    STATE.activeProvider = key;

    if (!key) {
        DOM.modelSelect.innerHTML = '<option value="">请先选择服务商</option>';
        updateProviderStatus(null);
        updateInputState();
        updateNativeUploadToggle();
        return;
    }

    const provider = STATE.providers.find(p => p.key === key);
    if (!provider) return;

    STATE.currentProviderSupportsNativeUpload = !!provider.supports_native_upload;
    if (!STATE.currentProviderSupportsNativeUpload) {
        STATE.nativeUploadMode = false;
    }
    updateNativeUploadToggle();

    DOM.modelSelect.innerHTML = provider.models.map(m =>
        `<option value="${m}" ${m === provider.default_model ? 'selected' : ''}>${m}</option>`
    ).join('');

    STATE.activeModel = provider.default_model;
    updateProviderStatus(provider);
    updateInputState();
    updateChatHeader();
}
window.onProviderChange = onProviderChange;

function onModelChange() {
    STATE.activeModel = DOM.modelSelect.value;
    updateChatHeader();

    const tempInput = document.getElementById('setting-temperature');
    const tempNotice = document.getElementById('temperature-notice');
    if (tempInput && tempNotice) {
        const isRestricted = STATE.activeProvider === 'tencent' && STATE.activeModel === 'kimi-k2.5';
        if (isRestricted) {
            tempInput.disabled = true;
            tempInput.value = '1.0';
            tempNotice.textContent = '⚠ kimi-k2.5 强制 temperature=1.0（思考模式），不可调整';
            tempNotice.style.display = 'block';
        } else {
            tempInput.disabled = false;
            tempNotice.style.display = 'none';
        }
    }
}
window.onModelChange = onModelChange;

function updateProviderStatus(provider) {
    if (!provider) {
        DOM.providerStatusDot.className = 'provider-status not-configured';
        DOM.providerStatusText.textContent = '未选择服务商';
        return;
    }
    if (provider.configured) {
        DOM.providerStatusDot.className = 'provider-status configured';
        DOM.providerStatusText.textContent = '已配置 ✓';
    } else {
        DOM.providerStatusDot.className = 'provider-status not-configured';
        DOM.providerStatusText.textContent = '未配置 API Key - 请在设置中配置';
    }
}
window.updateProviderStatus = updateProviderStatus;

function updateNativeUploadToggle() {
    if (!DOM.btnNativeUpload) return;
    if (STATE.currentProviderSupportsNativeUpload) {
        DOM.btnNativeUpload.style.display = '';
        DOM.btnNativeUpload.classList.toggle('active', STATE.nativeUploadMode);
        const provider = STATE.providers.find(p => p.key === STATE.activeProvider);
        const pname = provider ? provider.name : 'Kimi';
        DOM.btnNativeUpload.title = STATE.nativeUploadMode
            ? `原生上传（${pname} 云端解析）`
            : '本地解析上传';
    } else {
        DOM.btnNativeUpload.style.display = 'none';
        STATE.nativeUploadMode = false;
    }
}
window.updateNativeUploadToggle = updateNativeUploadToggle;

function updateInputState() {
    const provider = STATE.providers.find(p => p.key === STATE.activeProvider);
    const configured = provider?.configured || false;

    DOM.chatInput.disabled = !configured || STATE.isGenerating;
    DOM.btnSend.disabled = !configured;

    if (!STATE.activeProvider) {
        DOM.inputHint.textContent = '请先选择服务商';
    } else if (!configured) {
        DOM.inputHint.textContent = '⚠ 请先在设置中配置 API Key';
    } else if (STATE.isGenerating) {
        DOM.inputHint.textContent = 'AI 正在生成回复...';
    } else {
        DOM.inputHint.textContent = 'Enter 发送 · Shift+Enter 换行 · 支持 Markdown';
    }
}
window.updateInputState = updateInputState;

function updateChatHeader() {
    const provider = STATE.providers.find(p => p.key === STATE.activeProvider);
    if (provider && STATE.activeModel) {
        DOM.chatHeaderModel.textContent = provider.name;
        DOM.chatHeaderBadge.textContent = STATE.activeModel;
        DOM.chatHeaderBadge.style.display = 'inline';
    } else {
        DOM.chatHeaderModel.textContent = '选择一个模型开始';
        DOM.chatHeaderBadge.style.display = 'none';
    }
}
window.updateChatHeader = updateChatHeader;

// ============================================================
// 对话管理（支持后端持久化）
// ============================================================

async function loadConversations() {
    try {
        const resp = await fetch('/api/conversations');
        if (resp.status === 401) {
            window.location = '/login';
            return;
        }
        const convs = await resp.json();
        STATE.conversations = {};
        convs.forEach(c => {
            STATE.conversations[c.id] = {
                id: c.id,
                title: c.title || '新对话',
                messages: [],  // 消息列表延迟加载
                provider: c.provider,
                model: c.model,
                createdAt: c.created_at,
                updatedAt: c.updated_at
            };
        });
    } catch (e) {
        console.warn('从后端加载会话失败，尝试本地缓存:', e);
        try {
            const data = localStorage.getItem('llm-chat-conversations');
            STATE.conversations = data ? JSON.parse(data) : {};
        } catch (e2) {
            STATE.conversations = {};
        }
    }
}
window.loadConversations = loadConversations;

function saveConversations() {
    // 本地缓存作为降级方案
    pruneConversations();
    localStorage.setItem('llm-chat-conversations', JSON.stringify(STATE.conversations));
}
window.saveConversations = saveConversations;

async function createConversation() {
    try {
        const resp = await fetch('/api/conversations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: '新对话',
                provider: STATE.activeProvider,
                model: STATE.activeModel
            })
        });
        if (resp.status === 401) {
            window.location = '/login';
            return null;
        }
        const data = await resp.json();
        const id = data.id;

        STATE.conversations[id] = {
            id,
            title: '新对话',
            messages: [],
            provider: STATE.activeProvider,
            model: STATE.activeModel,
            createdAt: new Date().toISOString()
        };
        STATE.activeConvId = id;
        STATE.searchQuery = '';
        saveConversations();
        renderConversationList();
        renderMessages();
        return id;
    } catch (e) {
        console.error('创建会话失败:', e);
        showToast('创建会话失败', 'error');
        return null;
    }
}
window.createConversation = createConversation;

async function deleteConversation(id) {
    try {
        await fetch(`/api/conversations/${id}`, { method: 'DELETE' });
    } catch (e) {
        console.warn('删除后端会话失败:', e);
    }
    delete STATE.conversations[id];
    delete STATE.drafts[id];
    if (STATE.activeConvId === id) {
        const keys = Object.keys(STATE.conversations);
        STATE.activeConvId = keys.length > 0 ? keys[keys.length - 1] : null;
    }
    saveConversations();
    renderConversationList();
    renderMessages();
    updateExportButton();
}
window.deleteConversation = deleteConversation;

async function switchConversation(id) {
    if (STATE.activeConvId && DOM.chatInput.value.trim()) {
        STATE.drafts[STATE.activeConvId] = DOM.chatInput.value;
    }

    STATE.activeConvId = id;
    const conv = STATE.conversations[id];
    if (conv) {
        conv.lastAccessed = new Date().toISOString();
        STATE.activeProvider = conv.provider;
        STATE.activeModel = conv.model;
        if (DOM.providerSelect.value !== conv.provider) {
            DOM.providerSelect.value = conv.provider;
            onProviderChange();
        }
        DOM.modelSelect.value = conv.model;
        STATE.activeModel = conv.model;
        STATE.activeTemplate = conv.system_prompt ? {
            id: conv.templateId,
            name: conv.templateName || '模板',
            icon: conv.templateIcon || '⚡',
            system_prompt: conv.system_prompt
        } : null;

        // 如果消息列表为空，从后端加载
        if (conv.messages.length === 0) {
            try {
                const resp = await fetch(`/api/conversations/${id}`);
                if (resp.ok) {
                    const data = await resp.json();
                    conv.messages = (data.messages || []).map(m => ({
                        role: m.role,
                        content: m.content,
                        _userInput: m.original_text || undefined
                    }));
                }
            } catch (e) {
                console.warn('加载消息历史失败:', e);
            }
        }
    }

    DOM.chatInput.value = STATE.drafts[id] || '';
    DOM.chatInput.style.height = 'auto';
    DOM.chatInput.style.height = Math.min(DOM.chatInput.scrollHeight, 160) + 'px';

    renderConversationList();
    renderMessages();
    updateChatHeader();
    updateInputState();
    updateExportButton();
    updateTemplateButton();
    updateTokenCounter();
}
window.switchConversation = switchConversation;

function getActiveConversation() {
    if (!STATE.activeConvId || !STATE.conversations[STATE.activeConvId]) {
        return null;
    }
    return STATE.conversations[STATE.activeConvId];
}
window.getActiveConversation = getActiveConversation;

/**
 * 保存消息到后端数据库
 * @param {string} convId - 会话ID
 * @param {string} role - 'user' 或 'assistant'
 * @param {string} content - 消息内容
 * @param {string|null} originalText - 用户原始输入（仅 user 角色）
 */
async function saveMessageToBackend(convId, role, content, originalText) {
    if (!convId) return;
    try {
        const body = { role, content };
        if (originalText) body.original_text = originalText;
        await fetch(`/api/conversations/${convId}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
    } catch (e) {
        console.warn('保存消息到后端失败:', e);
    }
}
window.saveMessageToBackend = saveMessageToBackend;

/**
 * 更新后端会话标题
 * @param {string} convId - 会话ID
 * @param {string} title - 新标题
 */
async function updateConversationTitle(convId, title) {
    if (!convId) return;
    try {
        await fetch(`/api/conversations/${convId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
        });
    } catch (e) {
        console.warn('更新会话标题失败:', e);
    }
}
window.updateConversationTitle = updateConversationTitle;

// ============================================================
// 对话搜索
// ============================================================

function filterConversations(convs, query) {
    if (!query) return convs;
    const q = query.toLowerCase();
    return convs.filter(c =>
        (c.title || '').toLowerCase().includes(q) ||
        (c.messages || []).some(m => (m.content || '').toLowerCase().includes(q))
    );
}

function highlightMatch(text, query) {
    if (!query) return escapeHtml(text);
    const safe = escapeHtml(text);
    const safeQ = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return safe.replace(new RegExp(safeQ, 'gi'),
        match => `<mark style="background:var(--warning);color:#000;padding:0 2px;border-radius:2px;">${match}</mark>`);
}

function renderConversationList() {
    const list = DOM.conversationList;
    let convs = Object.values(STATE.conversations).sort(
        (a, b) => new Date(b.createdAt) - new Date(a.createdAt)
    );

    convs = filterConversations(convs, STATE.searchQuery);

    if (convs.length === 0) {
        list.innerHTML = STATE.searchQuery
            ? `<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">没有找到匹配的对话</div>`
            : `<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">暂无对话历史</div>`;
        return;
    }

    const q = STATE.searchQuery;
    list.innerHTML = convs.map(c => `
        <div class="conv-item ${c.id === STATE.activeConvId ? 'active' : ''}"
             onclick="switchConversation('${c.id}')">
            <div style="flex:1;min-width:0;">
                <div class="conv-item-title">${highlightMatch(c.title || '新对话', q)}</div>
                <div class="conv-item-meta">${formatDate(c.createdAt)}</div>
            </div>
            <button class="conv-item-delete" onclick="event.stopPropagation();deleteConversation('${c.id}')">×</button>
        </div>
    `).join('');
}
window.renderConversationList = renderConversationList;

// ============================================================
// Token 估算 & 滑动窗口
// ============================================================

function estimateTokens(text) {
    if (!text) return 0;
    const cjk = (text.match(/[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/g) || []).length;
    const words = (text.match(/[a-zA-Z]+/g) || []).length;
    const digits = (text.match(/[0-9]+/g) || []).length;
    const other = Math.max(0, text.length - cjk - (text.match(/[a-zA-Z]/g) || []).length - (text.match(/[0-9]/g) || []).length);
    return Math.ceil(cjk * 2 + words * 1.3 + digits * 0.5 + other * 0.5);
}
window.estimateTokens = estimateTokens;

function getTotalConversationTokens(conv) {
    if (!conv || !conv.messages) return 0;
    let total = 0;
    conv.messages.forEach(m => { total += estimateTokens(m.content || ''); });
    return total;
}
window.getTotalConversationTokens = getTotalConversationTokens;

function updateTokenCounter() {
    if (!DOM.tokenCounter || !DOM.tokenCount) return;
    const conv = getActiveConversation();
    if (!conv || conv.messages.length === 0) {
        DOM.tokenCounter.style.display = 'none';
        return;
    }
    let total = getTotalConversationTokens(conv);
    total += estimateTokens(DOM.chatInput.value);
    DOM.tokenCounter.style.display = 'inline';
    DOM.tokenCount.textContent = total >= 1000 ? (total / 1000).toFixed(1) + 'K' : total;
    const limit = 32000;
    DOM.tokenCounter.className = 'token-counter ' +
        (total < limit * 0.5 ? 'safe' : total < limit * 0.8 ? 'warn' : 'danger');
}
window.updateTokenCounter = updateTokenCounter;

function prepareMessages(conv) {
    const maxMessages = STATE.settings.context_messages || 20;
    const allMessages = conv.messages.map(m => ({ role: m.role, content: m.content }));
    if (allMessages.length <= maxMessages) return allMessages;
    const firstUserIdx = allMessages.findIndex(m => m.role === 'user');
    const firstMsg = firstUserIdx >= 0 ? [allMessages[firstUserIdx]] : [];
    const recent = allMessages.slice(-maxMessages);
    if (firstMsg.length > 0 && recent.some(m => m === firstMsg[0])) return recent;
    return [...firstMsg, ...recent];
}
window.prepareMessages = prepareMessages;
