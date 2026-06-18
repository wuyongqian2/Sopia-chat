/**
 * utils.js — 工具函数
 * 依赖：state.js（DOM）
 */

// ============================================================
// 工具函数
// ============================================================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
window.escapeHtml = escapeHtml;

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    DOM.toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
window.showToast = showToast;

function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2, 6);
}
window.generateId = generateId;

function scrollToBottom() {
    DOM.messagesContainer.scrollTop = DOM.messagesContainer.scrollHeight;
}
window.scrollToBottom = scrollToBottom;

function formatDate(isoStr) {
    const d = new Date(isoStr);
    const now = new Date();
    const diffDays = Math.floor((now - d) / (1000 * 60 * 60 * 24));
    if (diffDays === 0) return '今天 ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    if (diffDays === 1) return '昨天';
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}
window.formatDate = formatDate;

function getFileTypeClass(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'].includes(ext)) return 'type-image';
    if (['pdf'].includes(ext)) return 'type-pdf';
    if (['txt', 'md', 'log', 'csv', 'json', 'xml', 'yaml', 'yml'].includes(ext)) return 'type-text';
    if (['py', 'js', 'ts', 'html', 'css', 'java', 'c', 'cpp', 'go', 'rs'].includes(ext)) return 'type-code';
    return 'type-other';
}
window.getFileTypeClass = getFileTypeClass;

function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'].includes(ext)) return '\uD83D\uDCF7';
    if (['pdf'].includes(ext)) return '\uD83D\uDCC4';
    if (['txt', 'md', 'log'].includes(ext)) return '\uD83D\uDCDD';
    if (['csv', 'xlsx', 'xls'].includes(ext)) return '\uD83D\uDCCA';
    if (['docx', 'doc'].includes(ext)) return '\uD83D\uDCC4';
    if (['pptx', 'ppt'].includes(ext)) return '\uD83D\uDCD1';
    return '\uD83D\uDCCE';
}
window.getFileIcon = getFileIcon;

// ============================================================
// 网络请求（带超时 + CSRF 保护）
// ============================================================

function getCsrfToken() {
    // 优先从 cookie 读取（后端 after_request 钩子每次响应刷新）
    const match = document.cookie.match(/(?:^|;\s*)csrf_token\s*=\s*([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
}
window.getCsrfToken = getCsrfToken;

// ============================================================
// 全局 fetch 拦截：自动为同源 POST/PUT/PATCH/DELETE 注入 CSRF Token
// ============================================================
(function() {
    const _fetch = window.fetch;
    window.fetch = function(url, options = {}) {
        const method = (options.method || 'GET').toUpperCase();
        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
            const urlStr = typeof url === 'string' ? url : (url.url || '');
            // 仅同源请求注入 CSRF token（避免跨域泄露）
            if (urlStr.startsWith('/') || urlStr.startsWith(window.location.origin)) {
                const headers = { ...(options.headers || {}) };
                if (!headers['X-CSRFToken']) {
                    const token = getCsrfToken();
                    if (token) {
                        headers['X-CSRFToken'] = token;
                    } else {
                        console.warn('[CSRF] Token is empty, POST request may fail:', urlStr);
                    }
                }
                return _fetch(url, { ...options, headers });
            }
        }
        return _fetch(url, options);
    };
})();

async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    // 对所有状态变更请求自动注入 CSRF token
    const method = (options.method || 'GET').toUpperCase();
    const headers = { ...(options.headers || {}) };
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        const token = getCsrfToken();
        if (token && !headers['X-CSRFToken']) {
            headers['X-CSRFToken'] = token;
        } else if (!token) {
            console.warn('[CSRF] Token is empty in fetchWithTimeout, POST request may fail:', url);
        }
    }

    try {
        const resp = await fetch(url, {
            ...options,
            headers,
            signal: controller.signal
        });
        return resp;
    } finally {
        clearTimeout(timer);
    }
}
window.fetchWithTimeout = fetchWithTimeout;
