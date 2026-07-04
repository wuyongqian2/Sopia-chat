/**
 * fileUpload.js — 文件上传相关
 * 依赖：state.js (STATE, DOM), utils.js (showToast, getFileTypeClass, getFileIcon, fetchWithTimeout)
 */

// ============================================================
// 文件上传相关
// ============================================================

function renderFilePreviews() {
    DOM.filePreviewList.innerHTML = STATE.uploadedFiles.map(f => `
        <div class="file-chip ${getFileTypeClass(f.name)}" data-id="${f.id}">
            <span class="chip-name">${getFileIcon(f.name)} ${f.name}</span>
            <button class="chip-remove" onclick="removeFile('${f.id}')" title="移除文件">×</button>
        </div>
    `).join('');
}
window.renderFilePreviews = renderFilePreviews;

function handleFileSelect(e) {
    const files = Array.from(e.target.files);
    if (files.length === 0) return;

    files.forEach(file => {
        if (file.size > 50 * 1024 * 1024) {
            showToast(`文件 ${file.name} 超过 50MB 限制`, 'error');
            return;
        }
        const id = generateId();
        STATE.uploadedFiles.push({
            id, name: file.name, file: file,
            extractedText: null, isLarge: false, fileId: null,
            status: 'pending'
        });
    });

    renderFilePreviews();
    DOM.fileInput.value = '';
    uploadPendingFiles();
}
window.handleFileSelect = handleFileSelect;

async function uploadPendingFiles() {
    const pending = STATE.uploadedFiles.filter(f => f.status === 'pending');
    for (const item of pending) {
        item.status = 'uploading';
        renderFilePreviews();

        const formData = new FormData();
        formData.append('file', item.file);

        // 聊天附件走专用端点（只解析全文，不分块入库）
        // 原生上传模式仍走 /api/upload
        let uploadUrl = '/api/chat/upload';
        if (STATE.nativeUploadMode && STATE.activeProvider) {
            uploadUrl = '/api/upload';
            formData.append('mode', 'native');
            formData.append('provider', STATE.activeProvider);
        }

        try {
            const resp = await fetch(uploadUrl, {
                method: 'POST',
                body: formData
            });
            const result = await resp.json();
            if (result.success) {
                item.extractedText = result.extracted_text || null;
                item.isLarge = result.is_large || false;
                // 优先使用 document_id（持久化），回退到 file_id（内存缓存）
                item.documentId = result.document_id || null;
                item.fileId = result.file_id || null;
                item.preview = result.preview || null;
                item.status = 'done';
                item.uploadMode = result.upload_mode || 'local';
                item.providerFileId = result.provider_file_id || null;
                item.isMultimodal = result.is_multimodal || false;

                // 原生多模态文件（图片/视频）：额外生成 base64 用于后续构造多模态消息
                if (item.uploadMode === 'native' && item.isMultimodal && item.file) {
                    try {
                        item.base64Data = await fileToBase64(item.file);
                    } catch (b64Err) {
                        console.warn('Base64 转换失败:', b64Err.message);
                    }
                }

                if (item.isLarge) {
                    showToast(`文件 ${item.name} 已分为 ${result.chunk_count} 个段落，请描述你想了解的内容`, 'info');
                }
            } else {
                item.status = 'error';
                showToast(`文件 ${item.name} 解析失败: ${result.error || '未知错误'}`, 'error');
            }
        } catch (err) {
            item.status = 'error';
            showToast(`文件 ${item.name} 上传失败: ${err.message}`, 'error');
        }
        renderFilePreviews();
    }
}
window.uploadPendingFiles = uploadPendingFiles;

function removeFile(id) {
    STATE.uploadedFiles = STATE.uploadedFiles.filter(f => f.id !== id);
    renderFilePreviews();
}
window.removeFile = removeFile;

/**
 * 将 File 对象读取为 Base64 Data URL
 * @param {File} file
 * @returns {Promise<string>} data:image/png;base64,xxx
 */
function fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error('文件读取失败'));
        reader.readAsDataURL(file);
    });
}
window.fileToBase64 = fileToBase64;


// ============================================================
// 知识库文档管理
// ============================================================

async function openDocumentsModal() {
    document.getElementById('documents-modal').style.display = 'flex';
    document.getElementById('doc-search-results').style.display = 'none';
    document.getElementById('doc-search-input').value = '';
    await loadDocumentList();
}
window.openDocumentsModal = openDocumentsModal;

function closeDocumentsModal() {
    document.getElementById('documents-modal').style.display = 'none';
}
window.closeDocumentsModal = closeDocumentsModal;

// ---- 文档排序状态 ----
let _docSortField = 'created_at'; // created_at | filename | file_size | chunk_count
let _docSortAsc = false; // 默认降序（最新在前）
let _cachedDocs = []; // 缓存文档列表用于排序

async function loadDocumentList() {
    const listEl = document.getElementById('doc-list');
    listEl.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);">加载中...</div>';

    try {
        const resp = await fetch('/api/documents');
        _cachedDocs = await resp.json();

        const selectAllWrap = document.getElementById('doc-select-all-wrap');

        if (!_cachedDocs || _cachedDocs.length === 0) {
            listEl.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted);">暂无已上传文档，上传文件后自动加入知识库</div>';
            if (selectAllWrap) selectAllWrap.style.display = 'none';
            updateSortButtons();
            return;
        }

        // 清空已选集合
        _selectedDocIds.clear();
        updateBatchButtons();
        updateSortButtons();
        if (selectAllWrap) selectAllWrap.style.display = 'inline';

        // 排序
        const docs = sortDocuments([..._cachedDocs]);

        listEl.innerHTML = docs.map(d => {
            const sizeStr = d.file_size > 1024 * 1024
                ? (d.file_size / (1024 * 1024)).toFixed(1) + ' MB'
                : d.file_size > 1024
                    ? (d.file_size / 1024).toFixed(1) + ' KB'
                    : d.file_size + ' B';
            const dateStr = d.created_at ? new Date(d.created_at).toLocaleString('zh-CN') : '';
            const chunkInfo = d.chunk_count > 0 ? `${d.chunk_count} 个分块` : '全文';

            return `<div class="doc-item" data-doc-id="${d.id}">
                <input type="checkbox" class="doc-item-checkbox" data-doc-id="${d.id}"
                       onchange="toggleDocSelection('${d.id}', this)">
                <div class="doc-item-icon">📄</div>
                <div class="doc-item-info">
                    <div class="doc-item-filename" title="${escapeHtml(d.filename)}">
                        ${escapeHtml(d.filename)}
                    </div>
                    <div class="doc-item-meta">
                        <span>📦 ${sizeStr}</span>
                        <span>🧩 ${chunkInfo}</span>
                        <span>🕐 ${dateStr}</span>
                    </div>
                </div>
                <div class="doc-item-actions">
                    <button class="doc-item-action-btn preview" title="预览内容"
                            onclick="previewDocument('${d.id}', '${escapeHtml(d.filename)}')">👁️</button>
                    <button class="doc-item-action-btn rename" title="重命名"
                            onclick="renameDocument('${d.id}', '${escapeHtml(d.filename)}')">✏️</button>
                    <button class="doc-item-action-btn delete" data-doc-id="${d.id}" title="删除文档"
                            onclick="deleteDocument('${d.id}')">🗑️</button>
                </div>
            </div>`;
        }).join('');
    } catch (err) {
        listEl.innerHTML = `<div style="text-align:center;padding:30px;color:var(--danger);">加载失败: ${escapeHtml(err.message)}</div>`;
    }
}
window.loadDocumentList = loadDocumentList;

async function deleteDocument(docId) {
    if (!confirm('确定删除该文档？删除后不可恢复。')) return;

    try {
        const resp = await fetch(`/api/documents/${docId}`, { method: 'DELETE' });
        const result = await resp.json();
        if (result.success) {
            showToast('文档已删除', 'success');
            await loadDocumentList();
        } else {
            showToast(`删除失败: ${result.error}`, 'error');
        }
    } catch (err) {
        showToast(`删除失败: ${err.message}`, 'error');
    }
}
window.deleteDocument = deleteDocument;

// ---- 搜索分页状态 ----
let _searchCurrentQuery = '';
let _searchCurrentPage = 1;
let _searchTopK = 10;
const _searchPageSize = 5; // 每页显示条数
let _searchAllResults = []; // 缓存全部结果

async function searchAllDocuments(page) {
    const query = (document.getElementById('doc-search-input').value || '').trim();
    // 如果是新搜索（无 page 参数或 page=1 且 query 变了），重置状态
    if (!page || (page === 1 && query !== _searchCurrentQuery)) {
        _searchCurrentQuery = query;
        _searchCurrentPage = 1;
    } else {
        _searchCurrentPage = page;
    }

    if (!_searchCurrentQuery) {
        showToast('请输入搜索内容', 'warning');
        return;
    }

    // top_k 固定为 10（不暴露给用户）
    const resultsEl = document.getElementById('doc-search-results');
    resultsEl.style.display = 'block';
    resultsEl.innerHTML = '<div style="text-align:center;padding:16px;color:var(--text-muted);">搜索中...</div>';

    try {
        const resp = await fetch('/api/documents/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: _searchCurrentQuery, top_k: _searchTopK })
        });
        const data = await resp.json();

        if (data.error) {
            resultsEl.innerHTML = `<div style="padding:12px;color:var(--danger);background:var(--danger-bg, #fef2f2);border-radius:6px;">${escapeHtml(data.error)}</div>`;
            return;
        }

        _searchAllResults = data.results || [];
        if (_searchAllResults.length === 0) {
            resultsEl.innerHTML = '<div style="padding:12px;color:var(--text-muted);text-align:center;">未找到相关内容</div>';
            return;
        }

        renderSearchResults(resultsEl);
    } catch (err) {
        resultsEl.innerHTML = `<div style="padding:12px;color:var(--danger);">搜索失败: ${escapeHtml(err.message)}</div>`;
    }
}
window.searchAllDocuments = searchAllDocuments;

function renderSearchResults(resultsEl) {
    const total = _searchAllResults.length;
    const totalPages = Math.ceil(total / _searchPageSize);
    const currentPage = Math.min(_searchCurrentPage, totalPages);
    _searchCurrentPage = currentPage; // 同步状态
    const startIdx = (currentPage - 1) * _searchPageSize;
    const endIdx = Math.min(startIdx + _searchPageSize, total);
    const pageResults = _searchAllResults.slice(startIdx, endIdx);

    let html = `
        <div class="search-results-header">
            <span>共 ${total} 条结果，第 ${currentPage}/${totalPages} 页</span>
        </div>
        ${pageResults.map(r => `
            <div class="search-result-item">
                <div class="search-result-header">
                    <span class="search-result-filename">
                        📄 ${escapeHtml(r.filename || '未知')}
                        ${r.heading ? ' · ' + escapeHtml(r.heading) : ''}
                    </span>
                    ${r.score !== undefined ? `<span class="search-result-score">相关度: ${(r.score * 100).toFixed(0)}%</span>` : ''}
                </div>
                <div class="search-result-snippet">${highlightText(r.text, _searchCurrentQuery)}</div>
            </div>
        `).join('')}
    `;

    // 翻页控件
    if (totalPages > 1) {
        html += `<div class="search-pagination">
            <button class="btn-secondary" onclick="searchAllDocuments(1)" ${currentPage === 1 ? 'disabled' : ''}>首页</button>
            <button class="btn-secondary" onclick="searchAllDocuments(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>上一页</button>
            <span class="search-page-info">${currentPage} / ${totalPages}</span>
            <button class="btn-secondary" onclick="searchAllDocuments(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>下一页</button>
            <button class="btn-secondary" onclick="searchAllDocuments(${totalPages})" ${currentPage === totalPages ? 'disabled' : ''}>末页</button>
        </div>`;
    }

    resultsEl.innerHTML = html;
}
window.renderSearchResults = renderSearchResults;

// ============================================================
// 知识库文档上传（支持多种格式）
// ============================================================

const DOC_ALLOWED_EXTENSIONS = [
    '.pdf', '.txt', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx',
    '.csv', '.json', '.html', '.htm', '.md', '.xml', '.rtf', '.epub',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'
];

function handleDocUploadClick() {
    document.getElementById('doc-file-input').click();
}
window.handleDocUploadClick = handleDocUploadClick;

async function handleDocFileSelect(e) {
    const files = Array.from(e.target.files);
    if (files.length === 0) return;
    await uploadDocFiles(files);
    e.target.value = '';
}
window.handleDocFileSelect = handleDocFileSelect;

async function uploadDocFiles(files) {
    const statusEl = document.getElementById('doc-upload-status');
    const allowedFiles = [];
    const rejectedFiles = [];
    const duplicateFiles = [];

    // 构建已有文件名校验集合
    const existingNames = new Set((_cachedDocs || []).map(d => d.filename));

    files.forEach(file => {
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (!DOC_ALLOWED_EXTENSIONS.includes(ext)) {
            rejectedFiles.push(file.name);
        } else if (file.size > 50 * 1024 * 1024) {
            showToast(`文件 ${file.name} 超过 50MB 限制`, 'error');
        } else if (existingNames.has(file.name)) {
            duplicateFiles.push(file);
        } else {
            allowedFiles.push(file);
        }
    });

    if (rejectedFiles.length > 0) {
        showToast(`不支持的文件格式: ${rejectedFiles.join(', ')}`, 'error');
    }

    // 处理重复文件：询问用户是否覆盖
    let overwriteFlags = {};
    if (duplicateFiles.length > 0) {
        const overwriteList = await showDuplicateConfirmDialog(duplicateFiles);
        for (const f of duplicateFiles) {
            if (overwriteList.includes(f.name)) {
                allowedFiles.push(f);
                overwriteFlags[f.name] = true;
            }
        }
    }

    if (allowedFiles.length === 0) return;

    statusEl.style.display = 'block';
    statusEl.innerHTML = `
        <div class="doc-upload-status-info" id="upload-file-info">正在上传 0/${allowedFiles.length} 个文件...</div>
        <div class="progress-bar" id="upload-progress-bar-wrap" style="display:none;">
            <div class="progress-fill" id="upload-progress-bar"></div>
        </div>
        <div class="doc-upload-status-text" id="upload-progress-text"></div>
    `;

    const fileInfoEl = document.getElementById('upload-file-info');
    const progressWrap = document.getElementById('upload-progress-bar-wrap');
    const progressBar = document.getElementById('upload-progress-bar');
    const progressText = document.getElementById('upload-progress-text');

    let successCount = 0;
    let failCount = 0;
    let skipCount = 0;

    for (let i = 0; i < allowedFiles.length; i++) {
        const file = allowedFiles[i];
        fileInfoEl.textContent = `正在上传 (${i + 1}/${allowedFiles.length}): ${file.name}`;

        const over = overwriteFlags[file.name] || false;
        try {
            const result = await uploadSingleFileWithProgress(file, progressBar, progressWrap, progressText, over);
            if (result.success) {
                successCount++;
            } else if (result.duplicate) {
                skipCount++;
                showToast(`文件 ${file.name} 已存在，已跳过`, 'info');
            } else {
                failCount++;
                showToast(`文件 ${file.name} 上传失败: ${result.error || '未知错误'}`, 'error');
            }
        } catch (err) {
            failCount++;
            showToast(`文件 ${file.name} 上传失败: ${err.message}`, 'error');
        }
    }

    let msg = `上传完成: ${successCount} 个成功`;
    if (failCount > 0) msg += `，${failCount} 个失败`;
    if (skipCount > 0) msg += `，${skipCount} 个跳过`;
    if (successCount > 0) showToast(msg, 'success');

    fileInfoEl.innerHTML = `<span class="upload-success">${msg}</span>`;
    progressWrap.style.display = 'none';
    progressText.style.display = 'none';
    setTimeout(() => { statusEl.style.display = 'none'; }, 3000);

    await loadDocumentList();
}

function uploadSingleFileWithProgress(file, progressBar, progressWrap, progressText, overwrite) {
    return new Promise((resolve, reject) => {
        const formData = new FormData();
        if (overwrite) {
            formData.append('overwrite', 'true');
        }
        formData.append('file', file);
        formData.append('persist', 'true');  // 知识库管理页面上传保持入库

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/upload');
        xhr.setRequestHeader('X-CSRFToken', getCsrfToken());

        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                progressWrap.style.display = 'block';
                progressText.style.display = 'block';
                progressBar.style.width = pct + '%';
                const loadedMB = (e.loaded / (1024 * 1024)).toFixed(1);
                const totalMB = (e.total / (1024 * 1024)).toFixed(1);
                progressText.textContent = `${loadedMB} MB / ${totalMB} (${pct}%)`;
            }
        });

        xhr.addEventListener('load', () => {
            try {
                const result = JSON.parse(xhr.responseText);
                resolve(result);
            } catch (e) {
                reject(new Error('响应解析失败'));
            }
        });

        xhr.addEventListener('error', () => reject(new Error('网络错误')));
        xhr.addEventListener('abort', () => reject(new Error('上传已取消')));

        xhr.send(formData);
    });
}

// ============================================================
// 重复文件确认对话框
// ============================================================

function showDuplicateConfirmDialog(duplicateFiles) {
    return new Promise((resolve) => {
        // 创建遮罩
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;justify-content:center;';

        // 创建对话框
        const fileListHTML = duplicateFiles.map(f =>
            `<div style="display:flex;align-items:center;padding:6px 0;border-bottom:1px solid var(--border-color, #333);">
                <span style="flex:1;font-size:13px;">📄 ${escapeHtml(f.name)}</span>
                <label style="display:flex;align-items:center;gap:4px;font-size:12px;cursor:pointer;">
                    <input type="checkbox" checked data-filename="${escapeHtml(f.name)}"> 覆盖
                </label>
            </div>`
        ).join('');

        const dialog = document.createElement('div');
        dialog.style.cssText = 'background:var(--bg-card, #1a1a2e);border-radius:12px;padding:24px;max-width:420px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.5);';
        dialog.innerHTML = `
            <h3 style="margin:0 0 12px 0;font-size:16px;">⚠️ 检测到重复文件</h3>
            <p style="margin:0 0 16px 0;font-size:13px;color:var(--text-muted, #888);">
                以下 ${duplicateFiles.length} 个文件已存在于知识库中，请选择处理方式：
            </p>
            <div style="margin-bottom:16px;">${fileListHTML}</div>
            <div style="display:flex;gap:8px;justify-content:flex-end;">
                <button id="dup-skip-all" style="padding:8px 16px;border:1px solid var(--border-color,#444);border-radius:6px;background:transparent;color:var(--text-primary,#e0e0e0);cursor:pointer;font-size:13px;">全部跳过</button>
                <button id="dup-confirm" style="padding:8px 16px;border:none;border-radius:6px;background:var(--accent,#6366f1);color:white;cursor:pointer;font-size:13px;">确认上传</button>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // 全部跳过
        dialog.querySelector('#dup-skip-all').onclick = () => {
            document.body.removeChild(overlay);
            resolve([]);
        };

        // 确认上传（只覆盖选中的文件）
        dialog.querySelector('#dup-confirm').onclick = () => {
            const checkboxes = dialog.querySelectorAll('input[type="checkbox"]');
            const overwriteList = [];
            checkboxes.forEach(cb => {
                if (cb.checked) overwriteList.push(cb.dataset.filename);
            });
            document.body.removeChild(overlay);
            resolve(overwriteList);
        };

        // 点击遮罩关闭 = 全部跳过
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                document.body.removeChild(overlay);
                resolve([]);
            }
        });
    });
}

// ============================================================
// 拖拽上传
// ============================================================

function initDocDropZone() {
    const modal = document.getElementById('documents-modal');
    const dropZone = document.getElementById('doc-drop-zone');
    let dragCounter = 0;

    modal.addEventListener('dragenter', (e) => {
        e.preventDefault();
        dragCounter++;
        dropZone.style.display = 'block';
        dropZone.style.borderColor = 'var(--accent)';
        dropZone.style.background = 'var(--bg-hover)';
    });

    modal.addEventListener('dragleave', (e) => {
        e.preventDefault();
        dragCounter--;
        if (dragCounter === 0) {
            dropZone.style.borderColor = 'var(--border-color)';
            dropZone.style.background = 'var(--bg-card)';
            setTimeout(() => { dropZone.style.display = 'none'; }, 200);
        }
    });

    modal.addEventListener('dragover', (e) => {
        e.preventDefault();
    });

    modal.addEventListener('drop', async (e) => {
        e.preventDefault();
        dragCounter = 0;
        dropZone.style.borderColor = 'var(--border-color)';
        dropZone.style.background = 'var(--bg-card)';
        dropZone.style.display = 'none';

        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) {
            await uploadDocFiles(files);
        }
    });
}
window.initDocDropZone = initDocDropZone;

// ============================================================
// 文档内容预览
// ============================================================

async function previewDocument(docId, filename) {
    const modal = document.getElementById('doc-preview-modal');
    const titleEl = document.getElementById('doc-preview-title');
    const metaEl = document.getElementById('doc-preview-meta');
    const contentEl = document.getElementById('doc-preview-content');

    titleEl.textContent = `📄 ${filename}`;
    metaEl.textContent = '加载中...';
    contentEl.textContent = '';
    modal.style.display = 'flex';

    try {
        const resp = await fetch(`/api/documents/${docId}/chunks`);
        const data = await resp.json();

        if (data.error) {
            metaEl.textContent = '';
            contentEl.innerHTML = `<div style="color:var(--danger);">加载失败: ${escapeHtml(data.error)}</div>`;
            return;
        }

        const chunks = data.chunks || [];
        metaEl.textContent = `共 ${chunks.length} 个分块`;

        if (chunks.length === 0) {
            contentEl.textContent = '暂无内容';
            return;
        }

        contentEl.innerHTML = chunks.map((c, i) => `
            <div style="margin-bottom:16px;padding:12px;border:1px solid var(--border-color);border-radius:6px;background:var(--bg-card);">
                ${c.heading ? `<div style="font-size:12px;color:var(--accent);margin-bottom:6px;font-weight:600;">${escapeHtml(c.heading)}</div>` : ''}
                <div style="font-size:13px;line-height:1.6;white-space:pre-wrap;">${escapeHtml(c.text)}</div>
            </div>
        `).join('');
    } catch (err) {
        metaEl.textContent = '';
        contentEl.innerHTML = `<div style="color:var(--danger);">加载失败: ${escapeHtml(err.message)}</div>`;
    }
}
window.previewDocument = previewDocument;

function closeDocPreviewModal() {
    document.getElementById('doc-preview-modal').style.display = 'none';
}
window.closeDocPreviewModal = closeDocPreviewModal;

// ============================================================
// 批量操作
// ============================================================

let _selectedDocIds = new Set();

function toggleDocSelection(docId, checkbox) {
    if (checkbox.checked) {
        _selectedDocIds.add(docId);
    } else {
        _selectedDocIds.delete(docId);
    }
    updateBatchButtons();
}
window.toggleDocSelection = toggleDocSelection;

function toggleSelectAll() {
    const selectAllCheckbox = document.getElementById('doc-select-all');
    const checkboxes = document.querySelectorAll('.doc-item-checkbox');
    checkboxes.forEach(cb => {
        cb.checked = selectAllCheckbox.checked;
        const docId = cb.dataset.docId;
        if (selectAllCheckbox.checked) {
            _selectedDocIds.add(docId);
        } else {
            _selectedDocIds.delete(docId);
        }
    });
    updateBatchButtons();
}
window.toggleSelectAll = toggleSelectAll;

function updateBatchButtons() {
    const batchDeleteBtn = document.getElementById('btn-doc-batch-delete');
    const selectAllWrap = document.getElementById('doc-select-all-wrap');
    const count = _selectedDocIds.size;
    batchDeleteBtn.style.display = count > 0 ? 'inline-flex' : 'none';
    batchDeleteBtn.textContent = `🗑️ 批量删除 (${count})`;
}

async function batchDeleteDocuments() {
    const count = _selectedDocIds.size;
    if (count === 0) return;
    if (!confirm(`确定删除选中的 ${count} 个文档？删除后不可恢复。`)) return;

    let successCount = 0;
    for (const docId of _selectedDocIds) {
        try {
            const resp = await fetch(`/api/documents/${docId}`, { method: 'DELETE' });
            const result = await resp.json();
            if (result.success) successCount++;
        } catch (err) {
            console.error(`删除文档 ${docId} 失败:`, err);
        }
    }

    showToast(`已删除 ${successCount} 个文档`, 'success');
    _selectedDocIds.clear();
    updateBatchButtons();
    await loadDocumentList();
}
window.batchDeleteDocuments = batchDeleteDocuments;

// ============================================================
// 文档排序
// ============================================================

function sortDocuments(docs) {
    const field = _docSortField;
    const asc = _docSortAsc;
    return docs.sort((a, b) => {
        let va = a[field], vb = b[field];
        if (field === 'filename') {
            va = (va || '').toLowerCase();
            vb = (vb || '').toLowerCase();
            return asc ? va.localeCompare(vb) : vb.localeCompare(va);
        }
        // 数值字段
        va = va || 0;
        vb = vb || 0;
        return asc ? va - vb : vb - va;
    });
}

function setDocSort(field) {
    if (_docSortField === field) {
        _docSortAsc = !_docSortAsc;
    } else {
        _docSortField = field;
        _docSortAsc = (field === 'filename'); // 文件名默认升序，其余默认降序
    }
    updateSortButtons();
    loadDocumentList();
}
window.setDocSort = setDocSort;

function updateSortButtons() {
    const fields = ['created_at', 'filename', 'file_size', 'chunk_count'];
    fields.forEach(f => {
        const btn = document.getElementById(`sort-doc-${f}`);
        if (!btn) return;
        const isActive = _docSortField === f;
        btn.style.background = isActive ? 'var(--accent)' : 'transparent';
        btn.style.color = isActive ? 'white' : 'var(--text-muted)';
        const arrows = { created_at: '🕐', filename: '🔤', file_size: '📦', chunk_count: '🧩' };
        const arrow = isActive ? (_docSortAsc ? ' ↑' : ' ↓') : '';
        btn.textContent = (arrows[f] || '') + arrow;
    });
}

// ============================================================
// 文档重命名
// ============================================================

async function renameDocument(docId, currentName) {
    const newName = prompt('请输入新的文件名：', currentName);
    if (!newName || newName.trim() === '' || newName.trim() === currentName) return;

    try {
        const resp = await fetch(`/api/documents/${docId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: newName.trim() })
        });
        const result = await resp.json();
        if (result.success) {
            showToast('重命名成功', 'success');
            await loadDocumentList();
        } else {
            showToast(`重命名失败: ${result.error}`, 'error');
        }
    } catch (err) {
        showToast(`重命名失败: ${err.message}`, 'error');
    }
}
window.renameDocument = renameDocument;

// ============================================================
// 搜索结果高亮
// ============================================================

function highlightText(text, query) {
    if (!query || !text) return escapeHtml(text);
    const escaped = escapeHtml(text);
    const queryTerms = query.trim().split(/\s+/).filter(t => t.length > 0);
    if (queryTerms.length === 0) return escaped;

    let result = escaped;
    queryTerms.forEach(term => {
        const escapedTerm = escapeHtml(term);
        const regex = new RegExp(`(${escapedTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
        result = result.replace(regex, '<mark style="background:var(--warning-bg,#fef3c7);color:var(--text-primary);padding:0 2px;border-radius:2px;">$1</mark>');
    });
    return result;
}
window.highlightText = highlightText;

function escapeHtml(str) {
    if (!str || typeof str !== 'string') return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/`/g, '&#96;');
}
window.escapeHtml = escapeHtml;
