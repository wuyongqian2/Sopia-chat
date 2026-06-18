/**
 * state.js — 全局状态 & DOM 引用
 * 最先加载，无外部依赖
 */

// ============================================================
// CDN 降级处理
// ============================================================
(function checkDeps() {
    if (typeof marked === 'undefined') {
        console.warn('marked.js CDN 未加载，使用简化渲染');
        window._markedAvailable = false;
    } else {
        window._markedAvailable = true;
        marked.setOptions({ breaks: true, gfm: true });
    }
    if (typeof hljs === 'undefined') {
        console.warn('highlight.js CDN 未加载，代码高亮不可用');
        window._hljsAvailable = false;
    } else {
        window._hljsAvailable = true;
    }
})();

// ============================================================
// 全局状态
// ============================================================
const STATE = {
    providers: [],
    activeProvider: null,
    activeModel: null,
    conversations: {},
    activeConvId: null,
    isGenerating: false,
    searchQuery: '',
    drafts: {},
    abortController: null,
    uploadedFiles: [],
    autoKnowledgeBase: true,  // 是否启用自动知识库检索
    nativeUploadMode: false,   // 是否使用服务商原生文件上传
    currentProviderSupportsNativeUpload: false,  // 当前服务商是否支持原生上传
    settings: {
        temperature: 0.7,
        max_tokens: 4096,
        context_messages: 20,
        theme: 'dark',
        skin: 'classic'
    },
    config: {},
    templates: [],
    templateCategories: [],
    activeTemplate: null,
};
window.STATE = STATE;

// ============================================================
// 对话数量上限（防内存泄漏 + localStorage 爆满）
// ============================================================
const MAX_CONVERSATIONS = 50;

function pruneConversations() {
    const entries = Object.entries(STATE.conversations);
    if (entries.length <= MAX_CONVERSATIONS) return;

    entries.sort((a, b) => {
        const ta = new Date(a[1].lastAccessed || a[1].createdAt || 0).getTime();
        const tb = new Date(b[1].lastAccessed || b[1].createdAt || 0).getTime();
        return ta - tb;
    });

    const toDelete = entries.slice(0, entries.length - MAX_CONVERSATIONS);
    toDelete.forEach(([id]) => {
        delete STATE.conversations[id];
    });
}
window.pruneConversations = pruneConversations;

// ============================================================
// DOM 引用
// ============================================================
const DOM = {
    providerSelect: document.getElementById('provider-select'),
    modelSelect: document.getElementById('model-select'),
    conversationList: document.getElementById('conversation-list'),
    messagesContainer: document.getElementById('messages-container'),
    emptyState: document.getElementById('empty-state'),
    chatInput: document.getElementById('chat-input'),
    btnSend: document.getElementById('btn-send'),
    btnUpload: document.getElementById('btn-upload'),
    btnKbToggle: document.getElementById('btn-kb-toggle'),
    fileInput: document.getElementById('file-input'),
    filePreviewList: document.getElementById('file-preview-list'),
    inputHint: document.getElementById('input-hint'),
    chatHeaderModel: document.getElementById('chat-header-model'),
    chatHeaderBadge: document.getElementById('chat-header-badge'),
    providerStatusDot: document.getElementById('provider-status-dot'),
    providerStatusText: document.getElementById('provider-status-text'),
    settingsModal: document.getElementById('settings-modal'),
    providerTabs: document.getElementById('provider-tabs'),
    providerForms: document.getElementById('provider-forms'),
    toastContainer: document.getElementById('toast-container'),
    themeIcon: document.getElementById('theme-icon'),
    btnExport: document.getElementById('btn-export'),
    exportMenu: document.getElementById('export-menu'),
    btnTemplate: document.getElementById('btn-template'),
    templateModal: document.getElementById('template-modal'),
    templateSearch: document.getElementById('template-search'),
    templateCategories: document.getElementById('template-categories'),
    templateList: document.getElementById('template-list'),
    variablesModal: document.getElementById('variables-modal'),
    variablesForm: document.getElementById('variables-form'),
    tokenCounter: document.getElementById('token-counter'),
    tokenCount: document.getElementById('token-count'),
    btnNativeUpload: document.getElementById('btn-native-upload'),
};
window.DOM = DOM;
