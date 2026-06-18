/**
 * messageRenderer.js — 消息渲染 & SSE 流式发送
 * 依赖：state.js (STATE, DOM), utils.js (escapeHtml, showToast, scrollToBottom, getFileTypeClass, getFileIcon)
 *        conversationManager.js (saveConversations, prepareMessages, estimateTokens, etc.)
 */

// ============================================================
// 消息渲染
// ============================================================

function renderMessages() {
    DOM.messagesContainer.innerHTML = '';
    const conv = getActiveConversation();

    if (!conv) {
        DOM.emptyState.style.display = 'flex';
        return;
    }

    if (conv.messages.length === 0 && !conv._streaming) {
        DOM.emptyState.style.display = 'flex';
        return;
    }

    DOM.emptyState.style.display = 'none';
    conv.messages.forEach((msg, idx) => {
        appendMessageBubble(msg);
    });

    // 如果该对话正在流式生成中，恢复流式气泡
    if (conv._streaming) {
        const streamingBubble = createStreamingBubble();
        const contentDiv = streamingBubble.querySelector('.message-content');
        if (conv._streamingContent) {
            contentDiv.innerHTML = renderMarkdown(conv._streamingContent);
            contentDiv.classList.add('typing-cursor');
            highlightCodeBlocks(contentDiv);
            addCopyButtons(contentDiv);
        }
        // 恢复停止按钮状态
        DOM.btnSend.textContent = '■';
        DOM.btnSend.classList.add('stop');
    }

    scrollToBottom();
    updateExportButton();
    updateTokenCounter();
}
window.renderMessages = renderMessages;

function appendMessageBubble(msg) {
    const div = document.createElement('div');
    div.className = `message ${msg.role}`;
    if (msg.error) div.classList.add('error');

    const avatar = msg.role === 'user' ? '👤' : '🤖';
    div._rawContent = msg.content || '';
    div._userInput = msg._userInput || null;

    let contentHtml = msg.error ? escapeHtml(msg.error) : renderMarkdown(msg.content || '');

    let fileTagsHtml = '';
    if (msg.role === 'user' && msg._fileNames && msg._fileNames.length > 0) {
        fileTagsHtml = msg._fileNames.map(fname =>
            `<span class="msg-file-tag">📎 ${escapeHtml(fname)}</span>`
        ).join('');
        fileTagsHtml = '<div style="margin-bottom:6px;">' + fileTagsHtml + '</div>';
    }

    div.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">
            ${fileTagsHtml}
            ${contentHtml}
        </div>
    `;

    DOM.messagesContainer.appendChild(div);
    highlightCodeBlocks(div);
    addCopyButtons(div);
    return div;
}
window.appendMessageBubble = appendMessageBubble;

function createStreamingBubble() {
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.id = 'streaming-message';
    div.innerHTML = `
        <div class="message-avatar">🤖</div>
        <div class="message-content typing-cursor"></div>
    `;
    DOM.messagesContainer.appendChild(div);
    return div;
}
window.createStreamingBubble = createStreamingBubble;

function renderMarkdown(text) {
    if (!text) return '';
    if (window._markedAvailable) {
        try {
            const rawHtml = marked.parse(text);
            if (window.DOMPurify) {
                return DOMPurify.sanitize(rawHtml);
            }
            console.warn('DOMPurify 未加载，跳过 XSS 净化');
            return rawHtml;
        } catch (e) {
            // fall through to plain text
        }
    }
    return '<pre style="white-space:pre-wrap;font-family:inherit;margin:0;">' + escapeHtml(text) + '</pre>';
}
window.renderMarkdown = renderMarkdown;

function highlightCodeBlocks(container) {
    if (!window._hljsAvailable) return;
    container.querySelectorAll('pre code').forEach(block => {
        if (!block.parentElement.classList.contains('code-block-wrapper')) {
            const pre = block.parentElement;
            const wrapper = document.createElement('div');
            wrapper.className = 'code-block-wrapper';
            pre.parentNode.insertBefore(wrapper, pre);
            wrapper.appendChild(pre);
            pre.classList.add('code-block');
        }
        hljs.highlightElement(block);
    });
}
window.highlightCodeBlocks = highlightCodeBlocks;

function addCopyButtons(container) {
    // 给整条 AI 回复添加复制按钮 + 重新生成按钮（仅 assistant 消息）
    const assistantMsg = container.closest('.message.assistant:not(.error)');
    if (assistantMsg && !assistantMsg.querySelector('.btn-copy-reply')) {
        const rawContent = assistantMsg._rawContent;
        if (rawContent) {
            // 复制按钮
            const btn = document.createElement('button');
            btn.className = 'btn-copy-reply';
            btn.textContent = '📋 复制回复';
            btn.onclick = function() {
                navigator.clipboard.writeText(rawContent).then(() => {
                    btn.textContent = '✅ 已复制';
                    btn.classList.add('copied');
                    setTimeout(() => {
                        btn.textContent = '📋 复制回复';
                        btn.classList.remove('copied');
                    }, 2000);
                }).catch(() => showToast('复制失败', 'error'));
            };
            assistantMsg.querySelector('.message-content').appendChild(btn);

            // 重新生成按钮（仅最后一条 AI 消息）
            const conv = getActiveConversation();
            const allAssistant = DOM.messagesContainer.querySelectorAll('.message.assistant');
            const isLast = allAssistant.length > 0 && allAssistant[allAssistant.length - 1] === assistantMsg;
            if (isLast && conv && conv.messages.length > 0) {
                const regenBtn = document.createElement('button');
                regenBtn.className = 'btn-regenerate';
                regenBtn.textContent = '🔄 重新生成';
                regenBtn.onclick = function() {
                    if (!STATE.isGenerating) regenerateLastMessage();
                };
                assistantMsg.querySelector('.message-content').appendChild(regenBtn);
            }
        }
    }

    // 给用户消息添加复制按钮
    const userMsg = container.closest('.message.user');
    if (userMsg && !userMsg.querySelector('.btn-copy-reply')) {
        // 优先复制用户原始输入，fallback 到完整 content
        const copyContent = userMsg._userInput || userMsg._rawContent;
        if (copyContent) {
            const btn = document.createElement('button');
            btn.className = 'btn-copy-reply user-copy';
            btn.textContent = '📋 复制消息';
            btn.onclick = function() {
                navigator.clipboard.writeText(copyContent).then(() => {
                    btn.textContent = '✅ 已复制';
                    btn.classList.add('copied');
                    setTimeout(() => {
                        btn.textContent = '📋 复制消息';
                        btn.classList.remove('copied');
                    }, 2000);
                }).catch(() => showToast('复制失败', 'error'));
            };
            userMsg.querySelector('.message-content').appendChild(btn);
        }
    }

    // 代码块复制按钮（原有逻辑）
    container.querySelectorAll('.code-block-wrapper').forEach(wrapper => {
        if (wrapper.querySelector('.btn-copy-code')) return;

        const btn = document.createElement('button');
        btn.className = 'btn-copy-code';
        btn.textContent = '复制';
        btn.onclick = function() {
            const code = wrapper.querySelector('code').textContent;
            navigator.clipboard.writeText(code).then(() => {
                btn.textContent = '已复制!';
                btn.classList.add('copied');
                setTimeout(() => {
                    btn.textContent = '复制';
                    btn.classList.remove('copied');
                }, 2000);
            }).catch(() => {
                showToast('复制失败', 'error');
            });
        };
        wrapper.appendChild(btn);
    });
}
window.addCopyButtons = addCopyButtons;

// ============================================================
// 重新生成
// ============================================================

function regenerateLastMessage() {
    const conv = getActiveConversation();
    if (!conv || conv.messages.length === 0 || STATE.isGenerating) return;

    // 找到最后一条 assistant 消息并移除
    const lastIdx = conv.messages.length - 1;
    if (conv.messages[lastIdx].role !== 'assistant') {
        showToast('最后一条消息不是 AI 回复，无法重新生成', 'info');
        return;
    }
    conv.messages.splice(lastIdx, 1);
    saveConversations();
    renderMessages();

    // 重新发送最后一条 user 消息（复用 sendMessage 的核心逻辑）
    const lastUserMsg = conv.messages[conv.messages.length - 1];
    if (!lastUserMsg || lastUserMsg.role !== 'user') {
        showToast('没有找到对应的用户消息', 'info');
        return;
    }

    // 构建消息列表并发送
    _doSend(conv, lastUserMsg.content || ' ');
}
window.regenerateLastMessage = regenerateLastMessage;

function _doSend(conv, text) {
    // 在 conv 对象上存储流式状态（不依赖 DOM）
    conv._streaming = true;
    conv._streamingContent = '';
    conv._streamingReasoning = '';

    // 如果用户正在看这个对话，创建流式气泡
    let streamingBubble = null;
    let contentDiv = null;
    const isViewing = STATE.activeConvId === conv.id;

    if (isViewing) {
        streamingBubble = createStreamingBubble();
        contentDiv = streamingBubble.querySelector('.message-content');
        scrollToBottom();
    }

    STATE.isGenerating = true;
    DOM.btnSend.textContent = '■';
    DOM.btnSend.classList.add('stop');
    DOM.chatInput.disabled = true;
    updateInputState();

    const messages = prepareMessages(conv);

    (async () => {
        try {
            const controller = new AbortController();
            STATE.abortController = controller;

            const payload = {
                provider: STATE.activeProvider,
                model: STATE.activeModel,
                messages,
                conversation_id: conv.id,
                temperature: STATE.settings.temperature,
                max_tokens: STATE.settings.max_tokens,
                system_prompt: conv.system_prompt || STATE.activeTemplate?.system_prompt || undefined
            };
            if (!payload.system_prompt) delete payload.system_prompt;

            const resp = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                signal: controller.signal
            });

            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const dataStr = line.slice(6).trim();
                    if (dataStr === '[DONE]') break;

                    try {
                        const data = JSON.parse(dataStr);
                        if (data.error) throw new Error(data.error);

                        if (data.content) {
                            // 内容永远存到数据层
                            conv._streamingContent += data.content;
                            // 只有用户正在看这个对话时才更新 DOM
                            if (STATE.activeConvId === conv.id) {
                                if (!contentDiv) {
                                    streamingBubble = createStreamingBubble();
                                    contentDiv = streamingBubble.querySelector('.message-content');
                                }
                                // 使用 requestAnimationFrame 节流 DOM 更新，避免逐 chunk 重排重绘
                                if (conv._rafId) cancelAnimationFrame(conv._rafId);
                                conv._rafId = requestAnimationFrame(() => {
                                    contentDiv.innerHTML = renderMarkdown(conv._streamingContent);
                                    contentDiv.classList.add('typing-cursor');
                                    scrollToBottom();
                                });
                            }
                        }

                        if (data.reasoning_content) {
                            conv._streamingReasoning += data.reasoning_content;
                            if (contentDiv && STATE.activeConvId === conv.id) {
                                updateReasoningBlock(contentDiv, conv._streamingReasoning);
                            }
                        }
                    } catch (parseErr) {
                        if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr;
                    }
                }
            }

            // 流结束：取消节流的 RAF，执行完整最终渲染
            if (conv._rafId) { cancelAnimationFrame(conv._rafId); conv._rafId = null; }
            const finalContent = conv._streamingContent || '(无回复内容)';
            conv.messages.push({ role: 'assistant', content: finalContent });
            // 保存助手回复到后端
            saveMessageToBackend(conv.id, 'assistant', finalContent);

            // 如果用户正在看，更新最终 DOM
            if (STATE.activeConvId === conv.id && contentDiv) {
                contentDiv.classList.remove('typing-cursor');
                streamingBubble._rawContent = finalContent;
                contentDiv.innerHTML = renderMarkdown(finalContent);
                highlightCodeBlocks(contentDiv);
                addCopyButtons(contentDiv);
            }

        } catch (err) {
            if (err.name === 'AbortError') {
                // 取消节流的 RAF
                if (conv._rafId) { cancelAnimationFrame(conv._rafId); conv._rafId = null; }
                const content = conv._streamingContent || '';
                if (content) {
                    conv.messages.push({ role: 'assistant', content });
                    // 保存中断的助手回复到后端
                    saveMessageToBackend(conv.id, 'assistant', content);
                    if (STATE.activeConvId === conv.id && contentDiv) {
                        streamingBubble._rawContent = content;
                        contentDiv.classList.remove('typing-cursor');
                        contentDiv.innerHTML = renderMarkdown(content);
                        highlightCodeBlocks(contentDiv);
                        addCopyButtons(contentDiv);
                    }
                } else {
                    if (STATE.activeConvId === conv.id && contentDiv) {
                        contentDiv.textContent = '(已中止)';
                    }
                }
            } else {
                const errorText = `请求失败: ${err.message}`;
                if (STATE.activeConvId === conv.id && contentDiv) {
                    contentDiv.textContent = errorText;
                    streamingBubble.classList.add('error');
                }
                showToast(errorText, 'error');
            }
        } finally {
            // 清除流式状态
            if (conv._rafId) { cancelAnimationFrame(conv._rafId); conv._rafId = null; }
            conv._streaming = false;
            conv._streamingContent = null;
            conv._streamingReasoning = null;

            STATE.uploadedFiles = [];
            renderFilePreviews();
            STATE.isGenerating = false;
            STATE.abortController = null;
            DOM.btnSend.textContent = '➤';
            DOM.btnSend.classList.remove('stop');
            DOM.chatInput.disabled = false;
            DOM.chatInput.focus();
            updateInputState();
            saveConversations();
            if (conv) conv.lastAccessed = new Date().toISOString();
            renderConversationList();
            updateExportButton();
            updateTokenCounter();
            scrollToBottom();
        }
    })();
}
window._doSend = _doSend;

function updateReasoningBlock(contentDiv, reasoning) {
    let block = contentDiv.querySelector('.thinking-block');
    if (!block) {
        block = document.createElement('div');
        block.className = 'thinking-block';
        block.innerHTML = `
            <div class="thinking-header" onclick="this.nextElementSibling.classList.toggle('open')">
                💭 思考过程
            </div>
            <div class="thinking-body open"></div>
        `;
        contentDiv.insertBefore(block, contentDiv.firstChild);
    }
    block.querySelector('.thinking-body').textContent = reasoning;
}
window.updateReasoningBlock = updateReasoningBlock;

// ============================================================
// 消息发送 & 流式接收
// ============================================================

async function sendMessage() {
    const text = DOM.chatInput.value.trim();
    if ((!text && STATE.uploadedFiles.length === 0) || STATE.isGenerating) return;

    const provider = STATE.providers.find(p => p.key === STATE.activeProvider);
    if (!provider?.configured) {
        showToast('请先配置 API Key', 'error');
        return;
    }

    let conv = getActiveConversation();
    if (!conv || (conv.provider !== STATE.activeProvider)) {
        conv = STATE.conversations[createConversation()];
    }
    conv.model = STATE.activeModel || conv.model;

    const pendingFiles = STATE.uploadedFiles.filter(f => f.status !== 'done' && f.status !== 'error');
    if (pendingFiles.length > 0) {
        DOM.inputHint.textContent = '正在解析文件...';
        await uploadPendingFiles();
    }

    // 分离原生多模态文件（图片/视频）和文本文件
    const nativeMultimodal = STATE.uploadedFiles.filter(f =>
        f.uploadMode === 'native' && f.isMultimodal && f.base64Data
    );
    const extractedFiles = STATE.uploadedFiles.filter(f => f.extractedText);
    let finalContent = text || ' ';
    const fileNames = [];

    if (extractedFiles.length > 0) {
        const smallFiles = extractedFiles.filter(f => !f.isLarge);
        const dbLargeFiles = extractedFiles.filter(f => f.isLarge && f.documentId);
        const cacheLargeFiles = extractedFiles.filter(f => f.isLarge && !f.documentId && f.fileId);

        let contextBlocks = [];

        // 小文件：直接注入全文
        for (const f of smallFiles) {
            fileNames.push(f.name);
            contextBlocks.push(`【附件: ${f.name}】\n\n${f.extractedText}`);
        }

        // 数据库大文件：批量向量检索（一次请求）
        if (dbLargeFiles.length > 0) {
            const docIds = dbLargeFiles.map(f => f.documentId);
            for (const f of dbLargeFiles) fileNames.push(f.name);

            try {
                const resp = await fetch('/api/search_chunks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        document_ids: docIds,
                        query: text || ''
                    })
                });
                const result = await resp.json();
                if (result.success && result.context) {
                    const fnames = dbLargeFiles.map(f => f.name).join('、');
                    contextBlocks.push(`【附件: ${fnames} - 相关内容】\n\n${result.context}`);
                } else {
                    // 检索未返回结果，使用预览文本兜底
                    const fallbackBlocks = dbLargeFiles
                        .filter(f => f.preview)
                        .map(f => `【附件: ${f.name} - 前3000字预览】\n\n${f.preview}`);
                    if (fallbackBlocks.length > 0) {
                        contextBlocks.push(...fallbackBlocks);
                    } else {
                        const fnames = dbLargeFiles.map(f => f.name).join('、');
                        contextBlocks.push(`【附件: ${fnames} - 未能检索到相关内容，请尝试更具体的问题】`);
                        showToast(`文件 ${fnames} 内容检索未返回结果`, 'warning');
                    }
                }
            } catch (err) {
                console.warn('批量分块检索失败:', err.message);
                // 检索异常，使用预览文本兜底
                const fallbackBlocks = dbLargeFiles
                    .filter(f => f.preview)
                    .map(f => `【附件: ${f.name} - 前3000字预览】\n\n${f.preview}`);
                if (fallbackBlocks.length > 0) {
                    contextBlocks.push(...fallbackBlocks);
                } else {
                    const fnames = dbLargeFiles.map(f => f.name).join('、');
                    contextBlocks.push(`【附件: ${fnames} - 检索服务异常，请稍后重试】`);
                    showToast(`文件 ${fnames} 内容检索失败: ${err.message}`, 'error');
                }
            }
        }

        // 内存缓存大文件：逐个检索（兼容旧逻辑）
        for (const lf of cacheLargeFiles) {
            fileNames.push(lf.name);
            try {
                const resp = await fetch('/api/search_chunks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        file_id: lf.fileId,
                        query: text || ''
                    })
                });
                const result = await resp.json();
                if (result.success && result.context) {
                    contextBlocks.push(`【附件: ${lf.name} - 相关内容】\n\n${result.context}`);
                } else if (lf.preview) {
                    contextBlocks.push(`【附件: ${lf.name} - 前3000字预览】\n\n${lf.preview}`);
                } else {
                    contextBlocks.push(`【附件: ${lf.name} - 未能检索到相关内容，请尝试更具体的问题】`);
                }
            } catch (err) {
                console.warn('分块检索失败:', err.message);
                if (lf.preview) {
                    contextBlocks.push(`【附件: ${lf.name} - 前3000字预览】\n\n${lf.preview}`);
                } else {
                    contextBlocks.push(`【附件: ${lf.name} - 检索服务异常，请稍后重试】`);
                    showToast(`文件 ${lf.name} 内容检索失败: ${err.message}`, 'error');
                }
            }
        }

        // 拼合所有上下文
        if (contextBlocks.length > 0) {
            finalContent = contextBlocks.join('\n\n---\n\n') + '\n\n---\n\n' + (text || '');
        }
    }

    // 自动检索知识库（当没有附件且启用自动检索时）
    if (STATE.autoKnowledgeBase && extractedFiles.length === 0 && text) {
        try {
            DOM.inputHint.textContent = '正在检索知识库...';
            const resp = await fetch('/api/documents/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: text, top_k: 5 })
            });
            const data = await resp.json();
            if (data.results && data.results.length > 0) {
                const kbBlocks = data.results.map(r => {
                    const filename = r.filename || '未知文件';
                    const score = r.score ? ` (相关度: ${(r.score * 100).toFixed(0)}%)` : '';
                    return `【知识库: ${filename}${score}】\n\n${r.text}`;
                });
                finalContent = kbBlocks.join('\n\n---\n\n') + '\n\n---\n\n' + (text || '');
                fileNames.push('知识库自动检索');
                showToast(`已从知识库检索到 ${data.results.length} 条相关内容`, 'info');
            }
        } catch (err) {
            console.warn('知识库自动检索失败:', err.message);
            // 静默失败，不影响正常对话
        } finally {
            DOM.inputHint.textContent = '';
        }
    }

    // 构造用户消息：有多模态图片时使用数组格式 content
    let userMsgContent = finalContent;
    if (nativeMultimodal.length > 0) {
        const contentParts = [{ type: "text", text: finalContent }];
        for (const img of nativeMultimodal) {
            fileNames.push(img.name);
            contentParts.push({
                type: "image_url",
                image_url: { url: img.base64Data }
            });
        }
        userMsgContent = contentParts;
    }

    const userMsg = { 
        role: 'user', 
        content: userMsgContent,
        _userInput: text || undefined,
        _fileNames: fileNames.length > 0 ? fileNames : undefined
    };

    conv.messages.push(userMsg);
    // 保存用户消息到后端（含原始输入）
    saveMessageToBackend(conv.id, 'user', finalContent, text || null);
    DOM.chatInput.value = '';
    DOM.chatInput.style.height = 'auto';
    DOM.emptyState.style.display = 'none';
    // 发送成功，清除该对话的草稿
    delete STATE.drafts[conv.id];

    appendMessageBubble(userMsg);
    scrollToBottom();

    if (conv.title === '新对话' && conv.messages.length === 1) {
        const titleSrc = text || `附件: ${STATE.uploadedFiles.map(f => f.name).join(', ')}`;
        // 先用截断文本作临时标题，防止页面标题空白
        conv.title = titleSrc.substring(0, 20) + (titleSrc.length > 20 ? '...' : '');
        renderConversationList();
        // 异步请求模型生成语义标题
        _generateSemanticTitle(conv, titleSrc);
    }

    // 复用 _doSend 处理 SSE 流式请求
    _doSend(conv, finalContent);
}
window.sendMessage = sendMessage;

/**
 * 异步调用后端 /api/chat/title 生成语义标题
 * 成功后更新 conv.title 并重新渲染对话列表
 */
async function _generateSemanticTitle(conv, userMessage) {
    if (!STATE.activeProvider || !STATE.activeModel) return;
    try {
        const resp = await fetch('/api/chat/title', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                provider: STATE.activeProvider,
                model: STATE.activeModel,
                user_message: userMessage
            })
        });
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.title && data.title.trim()) {
            conv.title = data.title.trim();
            renderConversationList();
            // 更新后端会话标题
            updateConversationTitle(conv.id, data.title.trim());
        }
    } catch (e) {
        // 静默失败：保留截断标题，不干扰主对话流
        console.warn('[title] 语义标题生成失败:', e.message);
    }
}

function stopGeneration() {
    if (STATE.isGenerating) {
        const conv = getActiveConversation();
        fetch('/api/chat/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conversation_id: conv?.id || 'default' })
        }).catch(() => {});
        if (STATE.abortController) {
            STATE.abortController.abort();
        }
    }
}
window.stopGeneration = stopGeneration;
