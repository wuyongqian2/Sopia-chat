/**
 * uiManager.js — 设置/模板/主题/导出/事件绑定/启动
 * 依赖：state.js, utils.js, fileUpload.js, conversationManager.js, messageRenderer.js
 */

// ============================================================
// Prompt 模板管理
// ============================================================

let _templateSearchFilter = '';
let _templateCategoryFilter = '全部';
let _pendingTemplate = null;

async function loadTemplates() {
    try {
        const resp = await fetch('/api/templates');
        const data = await resp.json();
        STATE.templates = data.templates || [];
        STATE.templateCategories = data.categories || ['全部'];
    } catch (e) {
        console.warn('加载模板失败:', e.message);
        STATE.templates = [];
    }
}
window.loadTemplates = loadTemplates;

function openTemplateModal() {
    DOM.templateModal.style.display = 'flex';
    _templateSearchFilter = '';
    _templateCategoryFilter = '全部';
    DOM.templateSearch.value = '';
    loadTemplates().then(() => {
        renderTemplateCategories();
        renderTemplateList();
    });
}
window.openTemplateModal = openTemplateModal;

function closeTemplateModal() {
    DOM.templateModal.style.display = 'none';
}
window.closeTemplateModal = closeTemplateModal;

function renderTemplateCategories() {
    const cats = STATE.templateCategories.length > 0 ? STATE.templateCategories : ['全部'];
    DOM.templateCategories.innerHTML = cats.map(c => `
        <button class="template-category-btn ${c === _templateCategoryFilter ? 'active' : ''}"
                onclick="filterTemplateCategory('${c}')">${c}</button>
    `).join('');
}
window.renderTemplateCategories = renderTemplateCategories;

function filterTemplateCategory(cat) {
    _templateCategoryFilter = cat;
    renderTemplateCategories();
    renderTemplateList();
}
window.filterTemplateCategory = filterTemplateCategory;

function renderTemplateList() {
    let filtered = STATE.templates;

    if (_templateCategoryFilter && _templateCategoryFilter !== '全部') {
        filtered = filtered.filter(t => t.category === _templateCategoryFilter);
    }

    if (_templateSearchFilter) {
        const q = _templateSearchFilter.toLowerCase();
        filtered = filtered.filter(t =>
            t.name.toLowerCase().includes(q) ||
            t.description.toLowerCase().includes(q) ||
            t.category.toLowerCase().includes(q)
        );
    }

    if (filtered.length === 0) {
        DOM.templateList.innerHTML = `
            <div style="grid-column:1/-1;text-align:center;color:var(--text-muted);padding:30px;">
                没有找到匹配的模板
            </div>`;
        return;
    }

    DOM.templateList.innerHTML = filtered.map(t => `
        <div class="template-card" onclick="selectTemplate('${t.id}')">
            <div class="template-icon">${t.icon}</div>
            <div class="template-name">${escapeHtml(t.name)}</div>
            <div class="template-desc">${escapeHtml(t.description)}</div>
            <div style="display:flex;align-items:center;gap:4px;">
                <span class="template-category">${escapeHtml(t.category)}</span>
                ${t.is_builtin ? '<span class="template-badge">内置</span>' : ''}
            </div>
        </div>
    `).join('');
}
window.renderTemplateList = renderTemplateList;

function selectTemplate(templateId) {
    const template = STATE.templates.find(t => t.id === templateId);
    if (!template) return;

    closeTemplateModal();

    if (template.variables && template.variables.length > 0) {
        _pendingTemplate = template;
        openVariablesModal(template);
    } else {
        applyTemplate(template, {});
    }
}
window.selectTemplate = selectTemplate;

function openVariablesModal(template) {
    DOM.variablesModal.style.display = 'flex';
    DOM.variablesForm.innerHTML = template.variables.map(v => `
        <div class="form-group">
            <label>${escapeHtml(v.label || v.name)}</label>
            <input type="text" id="var-${v.name}" placeholder="${escapeHtml(v.label || v.name)}"
                   value="${escapeHtml(v.default || '')}">
        </div>
    `).join('') + `
        <div class="form-hint" style="margin-top:8px;">
            💡 模板预览：<code style="font-size:12px;color:var(--text-muted);">
            ${escapeHtml(template.system_prompt.substring(0, 100))}...</code>
        </div>
    `;
}
window.openVariablesModal = openVariablesModal;

function closeVariablesModal() {
    DOM.variablesModal.style.display = 'none';
    _pendingTemplate = null;
}
window.closeVariablesModal = closeVariablesModal;

function applyTemplateWithVariables() {
    if (!_pendingTemplate) return;
    const values = {};
    _pendingTemplate.variables.forEach(v => {
        const el = document.getElementById(`var-${v.name}`);
        values[v.name] = el ? el.value.trim() || v.default : v.default;
    });
    applyTemplate(_pendingTemplate, values);
    closeVariablesModal();
}
window.applyTemplateWithVariables = applyTemplateWithVariables;

function applyTemplate(template, variableValues) {
    let systemPrompt = template.system_prompt;
    if (variableValues && template.variables) {
        template.variables.forEach(v => {
            const val = variableValues[v.name] || v.default || '';
            systemPrompt = systemPrompt.replace(new RegExp(`\\{\\{${v.name}\\}\\}`, 'g'), val);
        });
    }

    STATE.activeTemplate = {
        id: template.id,
        name: template.name,
        icon: template.icon,
        system_prompt: systemPrompt
    };

    createConversation();
    const conv = getActiveConversation();
    if (conv) {
        conv.templateId = template.id;
        conv.templateName = template.name;
        conv.templateIcon = template.icon;
        conv.system_prompt = systemPrompt;
    }

    updateTemplateButton();
    showToast(`已应用模板: ${template.icon} ${template.name}`, 'success');
}
window.applyTemplate = applyTemplate;

function clearTemplate() {
    STATE.activeTemplate = null;
    const conv = getActiveConversation();
    if (conv) {
        conv.templateId = null;
        conv.templateName = null;
        conv.templateIcon = null;
        conv.system_prompt = null;
    }
    updateTemplateButton();
    showToast('已取消模板', 'info');
}
window.clearTemplate = clearTemplate;

function updateTemplateButton() {
    const conv = getActiveConversation();
    const tpl = STATE.activeTemplate || (conv && conv.system_prompt ? {
        name: conv.templateName || '模板',
        icon: conv.templateIcon || '⚡'
    } : null);

    if (tpl && (STATE.activeTemplate || (conv && conv.system_prompt))) {
        DOM.btnTemplate.classList.add('active');
        DOM.btnTemplate.title = `当前模板: ${tpl.name}（点击取消）`;
        let tag = DOM.btnTemplate.parentElement.querySelector('.template-active-tag');
        if (!tag) {
            tag = document.createElement('span');
            tag.className = 'template-active-tag';
            tag.onclick = (e) => { e.stopPropagation(); clearTemplate(); };
            DOM.btnTemplate.parentElement.appendChild(tag);
        }
        tag.textContent = `${tpl.icon} ${tpl.name} ✕`;
        tag.title = '点击取消模板';
    } else {
        DOM.btnTemplate.classList.remove('active');
        DOM.btnTemplate.title = 'Prompt 模板';
        const tag = DOM.btnTemplate.parentElement.querySelector('.template-active-tag');
        if (tag) tag.remove();
    }
}
window.updateTemplateButton = updateTemplateButton;

// ============================================================
// 设置弹窗
// ============================================================

function openSettingsModal(providerKey = null) {
    DOM.settingsModal.style.display = 'flex';

    const providersList = STATE.providers.length > 0 ? STATE.providers : getStaticProviders();

    DOM.providerTabs.innerHTML = providersList.map(p => `
        <button class="btn-provider-tab ${p.key === providerKey ? 'active' : ''}"
                onclick="showProviderForm('${p.key}')"
                style="padding:6px 14px; border:1px solid var(--border-color); border-radius:20px;
                       background:${p.key === providerKey ? 'var(--accent)' : 'transparent'};
                       color:${p.key === providerKey ? 'white' : 'var(--text-secondary)'};
                       cursor:pointer; font-size:12px; transition:all var(--transition);">
            ${p.name}
        </button>
    `).join('');

    const defaultKey = providerKey || providersList[0]?.key || 'deepseek';
    showProviderForm(defaultKey, providersList);

    renderSkinSelector();
    document.getElementById('setting-temperature').value = STATE.settings.temperature;
    document.getElementById('setting-max-tokens').value = STATE.settings.max_tokens;
    const ctxEl = document.getElementById('setting-context-messages');
    if (ctxEl) ctxEl.value = STATE.settings.context_messages || 20;
    const spEl = document.getElementById('setting-system-prompt');
    if (spEl) spEl.value = STATE.settings.system_prompt || '';
}
window.openSettingsModal = openSettingsModal;

function getStaticProviders() {
    return [
        { key: 'deepseek', name: 'DeepSeek', auth_type: 'bearer', auth_fields: ['api_key'], description: 'DeepSeek V4 系列模型' },
        { key: 'kimi', name: 'Kimi (月之暗面)', auth_type: 'bearer', auth_fields: ['api_key'], description: '月之暗面 Kimi 系列模型' },
        { key: 'zhipu', name: '智谱AI (GLM)', auth_type: 'bearer', auth_fields: ['api_key'], description: '智谱AI GLM 系列模型' },
        { key: 'qwen', name: '通义千问 (Qwen)', auth_type: 'bearer', auth_fields: ['api_key'], description: '阿里云通义千问系列模型' },
        { key: 'ernie', name: '文心一言 (ERNIE)', auth_type: 'bearer', auth_fields: ['api_key'], description: '百度千帆V2新版（兼容OpenAI协议，单API Key认证）' },
        { key: 'doubao', name: '豆包 (字节)', auth_type: 'bearer', auth_fields: ['api_key'], description: '字节跳动豆包 Seed 2.0 系列模型（兼容 OpenAI 协议，单 API Key 认证）' }
    ];
}
window.getStaticProviders = getStaticProviders;

function showProviderForm(providerKey, providersList) {
    const list = providersList || STATE.providers;
    const provider = list.find(p => p.key === providerKey);
    if (!provider) return;

    DOM.providerTabs.querySelectorAll('.btn-provider-tab').forEach(btn => {
        const isActive = btn.textContent.trim() === provider.name;
        btn.style.background = isActive ? 'var(--accent)' : 'transparent';
        btn.style.color = isActive ? 'white' : 'var(--text-secondary)';
    });

    const pc = STATE.config?.providers?.[providerKey] || {};

    let formHtml = `<h4 style="margin-bottom:14px;color:var(--text-secondary);">${provider.name} 认证配置</h4>`;
    formHtml += `<div class="form-hint" style="margin-bottom:14px;">${provider.description}</div>`;

    if (provider.auth_type === 'bearer') {
        formHtml += `
            <div class="form-group">
                <label>API Key</label>
                <input type="password" id="api-key-${providerKey}" placeholder="sk-..." value="${pc.api_key_set ? '***' : ''}">
                <div class="form-hint">
                    获取地址: <a href="#" onclick="return false">各服务商控制台</a>
                </div>
            </div>
        `;
    } else if (provider.auth_type === 'hmac') {
        formHtml += `
            <div class="form-group">
                <label>API Key / Access Key</label>
                <input type="password" id="api-key-${providerKey}" placeholder="AccessKey" value="${pc.api_key_set ? '***' : ''}">
            </div>
            <div class="form-group">
                <label>Secret Key</label>
                <input type="password" id="secret-key-${providerKey}" placeholder="SecretKey" value="${pc.secret_key_set ? '***' : ''}">
            </div>
        `;
    }

    const links = {
        deepseek: 'https://platform.deepseek.com/api_keys',
        kimi: 'https://platform.moonshot.cn/console/api-keys',
        zhipu: 'https://open.bigmodel.cn/usercenter/apikeys',
        qwen: 'https://bailian.console.aliyun.com/#/api-key',
        ernie: 'https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application',
        doubao: 'https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey'
    };

    const link = links[providerKey];
    if (link) {
        formHtml += `<div class="form-hint" style="margin-top:8px;">🔑 <a href="${link}" target="_blank">获取 ${provider.name} API Key →</a></div>`;
    }

    DOM.providerForms.innerHTML = formHtml;
    DOM.providerForms.dataset.activeProvider = providerKey;
}
window.showProviderForm = showProviderForm;

function closeSettingsModal() {
    DOM.settingsModal.style.display = 'none';
}
window.closeSettingsModal = closeSettingsModal;

async function saveAllSettings() {
    const btnSave = document.getElementById('btn-save-settings');
    const originalText = btnSave.textContent;

    btnSave.textContent = '保存中...';
    btnSave.disabled = true;

    try {
        const activeProviderKey = DOM.providerForms.dataset.activeProvider;

        if (activeProviderKey) {
            const providersList = STATE.providers.length > 0 ? STATE.providers : getStaticProviders();
            const provider = providersList.find(p => p.key === activeProviderKey);
            if (provider) {
                const authData = {};
                if (provider.auth_type === 'bearer') {
                    const el = document.getElementById(`api-key-${activeProviderKey}`);
                    const val = el ? el.value.trim() : '';
                    if (val && val !== '***') {
                        authData.api_key = val;
                    }
                } else if (provider.auth_type === 'hmac') {
                    const akEl = document.getElementById(`api-key-${activeProviderKey}`);
                    const skEl = document.getElementById(`secret-key-${activeProviderKey}`);
                    const akVal = akEl ? akEl.value.trim() : '';
                    const skVal = skEl ? skEl.value.trim() : '';
                    if (akVal && akVal !== '***') authData.api_key = akVal;
                    if (skVal && skVal !== '***') authData.secret_key = skVal;
                }

                if (Object.keys(authData).length > 0) {
                    await saveProviderConfig(activeProviderKey, authData);
                    showToast(`${provider.name} 配置已保存`, 'success');
                }
            }
        }

        STATE.settings.temperature = parseFloat(document.getElementById('setting-temperature').value) || 0.7;
        STATE.settings.max_tokens = parseInt(document.getElementById('setting-max-tokens').value) || 4096;
        STATE.settings.context_messages = parseInt(document.getElementById('setting-context-messages')?.value) || 20;
        STATE.settings.system_prompt = document.getElementById('setting-system-prompt')?.value.trim() || '';
        await saveSettings({
            temperature: STATE.settings.temperature,
            max_tokens: STATE.settings.max_tokens,
            context_messages: STATE.settings.context_messages,
            system_prompt: STATE.settings.system_prompt,
            theme: STATE.settings.theme,
            skin: STATE.settings.skin
        });

        closeSettingsModal();
        await loadConfig();
        await loadProviders();

        if (!STATE.activeProvider && activeProviderKey) {
            STATE.activeProvider = activeProviderKey;
            DOM.providerSelect.value = activeProviderKey;
            onProviderChange();
        }

        updateInputState();
        updateProviderStatus(
            STATE.providers.find(p => p.key === STATE.activeProvider) || null
        );

        showToast('设置已保存', 'success');
    } catch (e) {
        console.error('保存设置失败:', e);
        if (e.name === 'AbortError') {
            showToast('保存超时，请检查服务器是否运行', 'error');
        } else {
            showToast('保存失败: ' + (e.message || '网络错误'), 'error');
        }
        closeSettingsModal();
    } finally {
        btnSave.textContent = originalText;
        btnSave.disabled = false;
    }
}
window.saveAllSettings = saveAllSettings;

// ============================================================
// 主题切换
// ============================================================

function toggleTheme() {
    STATE.settings.theme = STATE.settings.theme === 'dark' ? 'light' : 'dark';
    applyTheme(STATE.settings.theme);
    saveSettings({ theme: STATE.settings.theme });
}
window.toggleTheme = toggleTheme;

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    DOM.themeIcon.textContent = theme === 'dark' ? '☀️' : '🌙';
    STATE.settings.theme = theme;
}
window.applyTheme = applyTheme;

// ============================================================
// 皮肤切换
// ============================================================

const SKINS = [
    { id: 'classic', name: 'Classic', desc: '经典深蓝 · 实色背景', colors: ['#1a1a2e', '#3b82f6', '#2563eb'] },
    { id: 'modern',  name: 'Modern',  desc: 'AI Native · 毛玻璃',  colors: ['#0f1117', '#4f8cff', '#a78bfa'] }
];

function applySkin(skinId) {
    const link = document.getElementById('skin-css');
    if (link) {
        link.href = `/skins/${skinId}.css`;
    }
    STATE.settings.skin = skinId;
    // 更新设置面板中的皮肤选择 UI
    document.querySelectorAll('.skin-option').forEach(el => {
        el.classList.toggle('active', el.dataset.skin === skinId);
    });
    // 保存到后端
    saveSettings({ skin: skinId });
}
window.applySkin = applySkin;

function renderSkinSelector() {
    const container = document.getElementById('skin-selector');
    if (!container) return;
    const current = STATE.settings.skin || 'classic';
    container.innerHTML = SKINS.map(s => `
        <div class="skin-option ${s.id === current ? 'active' : ''}" data-skin="${s.id}" onclick="applySkin('${s.id}')">
            <div class="skin-preview">
                <span style="background:${s.colors[0]}"></span>
                <span style="background:${s.colors[1]}"></span>
                <span style="background:${s.colors[2]}"></span>
            </div>
            <div class="skin-name">${s.name}</div>
            <div class="skin-desc">${s.desc}</div>
        </div>
    `).join('');
}
window.renderSkinSelector = renderSkinSelector;

// ============================================================
// 导出功能
// ============================================================

function updateExportButton() {
    const conv = getActiveConversation();
    if (DOM.btnExport) {
        DOM.btnExport.style.display = (conv && conv.messages.length > 0) ? 'flex' : 'none';
    }
}
window.updateExportButton = updateExportButton;

function exportAsMarkdown() {
    const conv = getActiveConversation();
    if (!conv || conv.messages.length === 0) {
        showToast('当前没有对话内容', 'error');
        return;
    }

    let md = `# ${conv.title || '对话'}\n\n`;
    md += `> **模型**: ${conv.provider} / ${conv.model}\n`;
    md += `> **时间**: ${conv.createdAt}\n\n---\n\n`;

    conv.messages.forEach(msg => {
        const role = msg.role === 'user' ? '👤 **用户**' : '🤖 **AI**';
        md += `### ${role}\n\n${msg.content}\n\n---\n\n`;
    });

    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${conv.title || '对话'}.md`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Markdown 已导出', 'success');
    DOM.exportMenu.style.display = 'none';
}
window.exportAsMarkdown = exportAsMarkdown;

function exportAsPDF() {
    const conv = getActiveConversation();
    if (!conv || conv.messages.length === 0) {
        showToast('当前没有对话内容', 'error');
        return;
    }

    const printWin = window.open('', '_blank');
    let html = `<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>${escapeHtml(conv.title || '对话')}</title>
<style>
    body { font-family: "PingFang SC","Microsoft YaHei","Segoe UI",sans-serif;
           max-width: 720px; margin: 40px auto; padding: 0 20px;
           color: #1e293b; line-height: 1.7; }
    h1 { font-size: 22px; border-bottom: 2px solid #3b82f6;
         padding-bottom: 8px; }
    .meta { color: #64748b; font-size: 13px; margin-bottom: 24px; }
    .msg { margin: 16px 0; padding: 12px 16px; border-radius: 8px;
           border-left: 3px solid #e2e8f0; }
    .msg.user { background: #eff6ff; border-left-color: #3b82f6; }
    .msg.assistant { background: #f8fafc; border-left-color: #10b981; }
    .role { font-weight: 700; font-size: 13px; margin-bottom: 6px; }
    pre { background: #f1f5f9; padding: 12px; border-radius: 6px;
          overflow-x: auto; font-size: 13px; }
    code { font-family: "Consolas","JetBrains Mono",monospace; font-size: 0.9em; }
    hr { border: none; border-top: 1px solid #e2e8f0; margin: 24px 0; }
    blockquote { border-left: 3px solid #3b82f6; padding: 8px 14px;
                 margin: 8px 0; background: #f8fafc; color: #475569; }
    table { border-collapse: collapse; width: 100%; margin: 8px 0; }
    th, td { border: 1px solid #e2e8f0; padding: 6px 12px; text-align: left; font-size: 13px; }
    th { background: #f1f5f9; font-weight: 600; }
    ul, ol { padding-left: 20px; }
</style></head><body>
<h1>${escapeHtml(conv.title || '对话')}</h1>
<div class="meta">模型: ${conv.provider} / ${conv.model} · ${conv.createdAt}</div>
<hr>`;

    conv.messages.forEach(msg => {
        const roleLabel = msg.role === 'user' ? '👤 用户' : '🤖 AI';
        const msgHtml = renderMarkdown(msg.content || '');
        html += `<div class="msg ${msg.role}">
            <div class="role">${roleLabel}</div>
            ${msgHtml}
        </div>`;
    });

    html += '</body></html>';
    printWin.document.write(html);
    printWin.document.close();
    printWin.onload = () => { printWin.print(); };
    showToast('请在打印对话框中选择"另存为 PDF"', 'info');
    DOM.exportMenu.style.display = 'none';
}
window.exportAsPDF = exportAsPDF;

// ============================================================
// 事件绑定
// ============================================================

function initEvents() {
    DOM.providerSelect.addEventListener('change', onProviderChange);
    DOM.modelSelect.addEventListener('change', onModelChange);

    DOM.btnUpload.addEventListener('click', () => DOM.fileInput.click());
    DOM.fileInput.addEventListener('change', handleFileSelect);

    // 知识库自动检索开关
    DOM.btnKbToggle.addEventListener('click', () => {
        STATE.autoKnowledgeBase = !STATE.autoKnowledgeBase;
        DOM.btnKbToggle.classList.toggle('active', STATE.autoKnowledgeBase);
        DOM.btnKbToggle.title = STATE.autoKnowledgeBase ? '自动检索知识库（已开启）' : '自动检索知识库（已关闭）';
        showToast(STATE.autoKnowledgeBase ? '已开启自动知识库检索' : '已关闭自动知识库检索', 'info');
    });

    // 原生上传模式开关
    if (DOM.btnNativeUpload) {
        DOM.btnNativeUpload.addEventListener('click', () => {
            STATE.nativeUploadMode = !STATE.nativeUploadMode;
            DOM.btnNativeUpload.classList.toggle('active', STATE.nativeUploadMode);
            const provider = STATE.providers.find(p => p.key === STATE.activeProvider);
            const pname = provider ? provider.name : 'Kimi';
            DOM.btnNativeUpload.title = STATE.nativeUploadMode
                ? `原生上传（${pname} 云端解析）`
                : '本地解析上传';
            showToast(STATE.nativeUploadMode ? `已切换到${pname}原生上传（云端解析）` : '已切换到本地解析上传', 'info');
        });
    }

    DOM.chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (STATE.isGenerating) {
                stopGeneration();
            } else {
                sendMessage();
            }
        }
    });

    DOM.chatInput.addEventListener('input', () => {
        DOM.chatInput.style.height = 'auto';
        DOM.chatInput.style.height = Math.min(DOM.chatInput.scrollHeight, 160) + 'px';
        updateTokenCounter();
    });

    DOM.btnSend.addEventListener('click', () => {
        if (STATE.isGenerating) {
            stopGeneration();
        } else {
            sendMessage();
        }
    });

    document.getElementById('btn-new-chat').addEventListener('click', () => {
        if (!STATE.activeProvider) {
            showToast('请先选择服务商', 'info');
            return;
        }
        const provider = STATE.providers.find(p => p.key === STATE.activeProvider);
        if (!provider?.configured) {
            openSettingsModal(STATE.activeProvider);
            return;
        }
        createConversation();
        DOM.chatInput.focus();
    });

    // 对话搜索
    const btnSearch = document.getElementById('btn-conv-search');
    const searchBar = document.getElementById('conv-search-bar');
    const searchInput = document.getElementById('conv-search-input');
    const searchClear = document.getElementById('btn-conv-search-clear');

    btnSearch.addEventListener('click', () => {
        const isVisible = searchBar.style.display !== 'none';
        searchBar.style.display = isVisible ? 'none' : 'block';
        if (!isVisible) {
            searchInput.focus();
        } else {
            STATE.searchQuery = '';
            searchInput.value = '';
            renderConversationList();
        }
    });

    searchInput.addEventListener('input', (e) => {
        STATE.searchQuery = e.target.value.trim();
        renderConversationList();
    });

    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            STATE.searchQuery = '';
            searchInput.value = '';
            searchBar.style.display = 'none';
            renderConversationList();
        }
    });

    searchClear.addEventListener('click', () => {
        STATE.searchQuery = '';
        searchInput.value = '';
        searchBar.style.display = 'none';
        renderConversationList();
    });

    document.getElementById('btn-open-settings').addEventListener('click', () => {
        openSettingsModal(STATE.activeProvider);
    });
    document.getElementById('btn-close-settings').addEventListener('click', closeSettingsModal);
    document.getElementById('btn-cancel-settings').addEventListener('click', closeSettingsModal);
    document.getElementById('btn-save-settings').addEventListener('click', saveAllSettings);
    DOM.settingsModal.addEventListener('click', (e) => {
        if (e.target === DOM.settingsModal) closeSettingsModal();
    });

    document.getElementById('btn-toggle-theme').addEventListener('click', toggleTheme);

    // 知识库弹窗
    document.getElementById('btn-documents').addEventListener('click', openDocumentsModal);
    document.getElementById('btn-close-documents').addEventListener('click', closeDocumentsModal);
    document.getElementById('btn-doc-search').addEventListener('click', searchAllDocuments);
    document.getElementById('btn-doc-refresh').addEventListener('click', loadDocumentList);
    document.getElementById('btn-doc-upload').addEventListener('click', handleDocUploadClick);
    document.getElementById('doc-file-input').addEventListener('change', handleDocFileSelect);
    document.getElementById('doc-search-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') searchAllDocuments();
    });
    document.getElementById('documents-modal').addEventListener('click', (e) => {
        if (e.target === document.getElementById('documents-modal')) closeDocumentsModal();
    });
    // 文档预览弹窗
    document.getElementById('btn-close-doc-preview').addEventListener('click', closeDocPreviewModal);
    document.getElementById('doc-preview-modal').addEventListener('click', (e) => {
        if (e.target === document.getElementById('doc-preview-modal')) closeDocPreviewModal();
    });
    // 批量操作
    document.getElementById('doc-select-all').addEventListener('change', toggleSelectAll);
    document.getElementById('btn-doc-batch-delete').addEventListener('click', batchDeleteDocuments);
    // 拖拽上传
    initDocDropZone();

    // 皮肤切换按钮（循环切换）
    document.getElementById('btn-toggle-skin').addEventListener('click', () => {
        const currentIdx = SKINS.findIndex(s => s.id === (STATE.settings.skin || 'classic'));
        const nextIdx = (currentIdx + 1) % SKINS.length;
        applySkin(SKINS[nextIdx].id);
        showToast(`皮肤: ${SKINS[nextIdx].name} — ${SKINS[nextIdx].desc}`, 'info');
    });

    // 导出菜单
    DOM.btnExport.addEventListener('click', (e) => {
        e.stopPropagation();
        DOM.exportMenu.style.display = DOM.exportMenu.style.display === 'block' ? 'none' : 'block';
    });
    document.addEventListener('click', () => {
        DOM.exportMenu.style.display = 'none';
    });

    // Prompt 模板
    DOM.btnTemplate.addEventListener('click', () => {
        if (STATE.activeTemplate) {
            clearTemplate();
        } else {
            openTemplateModal();
        }
    });
    document.getElementById('btn-close-template').addEventListener('click', closeTemplateModal);
    DOM.templateModal.addEventListener('click', (e) => {
        if (e.target === DOM.templateModal) closeTemplateModal();
    });
    DOM.templateSearch.addEventListener('input', (e) => {
        _templateSearchFilter = e.target.value.trim();
        renderTemplateList();
    });

    // 变量填写弹窗
    document.getElementById('btn-close-variables').addEventListener('click', closeVariablesModal);
    document.getElementById('btn-cancel-variables').addEventListener('click', closeVariablesModal);
    document.getElementById('btn-apply-template').addEventListener('click', applyTemplateWithVariables);
    DOM.variablesModal.addEventListener('click', (e) => {
        if (e.target === DOM.variablesModal) closeVariablesModal();
    });

    // 全局键盘快捷键
    document.addEventListener('keydown', handleGlobalShortcut);
}
window.initEvents = initEvents;

// ============================================================
// 键盘快捷键系统
// ============================================================

const SHORTCUTS = {
    'n':    { ctrl: true,  shift: false, desc: '新建对话' },
    's':    { ctrl: true,  shift: false, desc: '导出当前对话 (Markdown)' },
    '/':    { ctrl: true,  shift: false, desc: '打开设置' },
    'k':    { ctrl: true,  shift: false, desc: '搜索对话' },
    'Enter': { ctrl: true, shift: false, desc: '发送消息' },
};
window.SHORTCUTS = SHORTCUTS;

function handleGlobalShortcut(e) {
    const key = e.key;
    const ctrl = e.ctrlKey || e.metaKey;  // Windows: Ctrl, macOS: Cmd
    const shift = e.shiftKey;

    // Ctrl+Enter / Cmd+Enter → 已在 textarea 的 keydown 中处理（Enter 即发送）
    // 此处仅处理非输入框中的快捷键

    // 如果焦点在输入框/搜索框中，不拦截普通字母快捷键（让用户正常输入）
    const tag = document.activeElement?.tagName?.toLowerCase();
    const isInput = tag === 'input' || tag === 'textarea' || document.activeElement?.isContentEditable;

    // Ctrl+N → 新建对话（输入框中也要触发）
    if (key === 'n' && ctrl && !shift) {
        e.preventDefault();
        if (!STATE.activeProvider) {
            showToast('请先选择服务商', 'info');
            return;
        }
        const provider = STATE.providers.find(p => p.key === STATE.activeProvider);
        if (!provider?.configured) {
            openSettingsModal(STATE.activeProvider);
            return;
        }
        createConversation();
        DOM.chatInput.focus();
        return;
    }

    // 以下快捷键仅在非输入框时触发
    if (isInput) return;

    // Ctrl+S → 导出当前对话
    if (key === 's' && ctrl && !shift) {
        e.preventDefault();
        const conv = getActiveConversation();
        if (!conv || conv.messages.length === 0) {
            showToast('当前没有对话内容', 'info');
            return;
        }
        exportAsMarkdown();
        return;
    }

    // Ctrl+/ → 打开设置
    if (key === '/' && ctrl && !shift) {
        e.preventDefault();
        openSettingsModal(STATE.activeProvider);
        return;
    }

    // Ctrl+K → 搜索对话（切换搜索栏）
    if (key === 'k' && ctrl && !shift) {
        e.preventDefault();
        const searchBar = document.getElementById('conv-search-bar');
        const searchInput = document.getElementById('conv-search-input');
        const isVisible = searchBar.style.display !== 'none';
        searchBar.style.display = isVisible ? 'none' : 'block';
        if (!isVisible) {
            STATE.searchQuery = '';
            searchInput.value = '';
            searchInput.focus();
        } else {
            STATE.searchQuery = '';
            searchInput.value = '';
            renderConversationList();
        }
        return;
    }

    // Esc → 中止生成 / 关闭弹窗
    if (key === 'Escape') {
        if (STATE.isGenerating) {
            stopGeneration();
            return;
        }
        // 关闭各类弹窗
        if (DOM.settingsModal.style.display === 'flex') {
            closeSettingsModal();
            return;
        }
        if (DOM.templateModal.style.display === 'flex') {
            closeTemplateModal();
            return;
        }
        if (DOM.variablesModal.style.display === 'flex') {
            closeVariablesModal();
            return;
        }
        if (document.getElementById('documents-modal').style.display === 'flex') {
            closeDocumentsModal();
            return;
        }
        if (document.getElementById('doc-preview-modal').style.display === 'flex') {
            closeDocPreviewModal();
            return;
        }
        if (DOM.exportMenu.style.display === 'block') {
            DOM.exportMenu.style.display = 'none';
            return;
        }
        // 关闭搜索栏
        const searchBar = document.getElementById('conv-search-bar');
        if (searchBar && searchBar.style.display !== 'none') {
            STATE.searchQuery = '';
            document.getElementById('conv-search-input').value = '';
            searchBar.style.display = 'none';
            renderConversationList();
            return;
        }
        // 输入框失焦
        if (document.activeElement === DOM.chatInput) {
            DOM.chatInput.blur();
        }
    }
}
window.handleGlobalShortcut = handleGlobalShortcut;

// ============================================================
// 启动
// ============================================================

async function init() {
    loadConversations();
    initEvents();
    renderConversationList();
    
    // 初始化知识库自动检索开关状态
    DOM.btnKbToggle.classList.toggle('active', STATE.autoKnowledgeBase);
    DOM.btnKbToggle.title = STATE.autoKnowledgeBase ? '自动检索知识库（已开启）' : '自动检索知识库（已关闭）';
    updateNativeUploadToggle();
    renderMessages();
    updateChatHeader();
    updateInputState();
    updateExportButton();
    updateTemplateButton();
    updateTokenCounter();

    try {
        await loadConfig();
        await loadProviders();
        await loadTemplates();

        const convKeys = Object.keys(STATE.conversations);
        if (convKeys.length > 0) {
            const lastConv = STATE.conversations[convKeys[convKeys.length - 1]];
            STATE.activeProvider = lastConv.provider || STATE.providers[0]?.key;
            STATE.activeModel = lastConv.model;
            STATE.activeConvId = lastConv.id;
            DOM.providerSelect.value = STATE.activeProvider || '';
            onProviderChange();
            DOM.modelSelect.value = STATE.activeModel || '';
            // 恢复模板状态
            STATE.activeTemplate = lastConv.system_prompt ? {
                id: lastConv.templateId,
                name: lastConv.templateName || '模板',
                icon: lastConv.templateIcon || '⚡',
                system_prompt: lastConv.system_prompt
            } : null;
        }

        updateChatHeader();
        updateInputState();
        updateTemplateButton();
        console.log('Sophia Chat 已就绪（在线模式）');
    } catch (e) {
        console.warn('服务器连接失败，配置功能不可用:', e.message);
        DOM.providerSelect.innerHTML = '<option value="">服务器未连接 - 点击设置按钮配置</option>';
        DOM.providerStatusDot.className = 'provider-status not-configured';
        DOM.providerStatusText.textContent = '服务器未连接';
        console.log('Sophia Chat 已就绪（离线模式，仅配置可用）');
    }

    updateInputState();
}
window.init = init;
