# Sophia Chat 文件上传与对话上下文重构方案

**编写日期**：2026-07-04
**问题来源**：聊天区文件上传未将文件全文直接传递给大模型，而是走了知识库 RAG 分块检索流程，导致用户上传文件后 AI 无法完整"阅读"文件内容
**预期工期**：P0 约 0.5 天，P1 约 2 天，P2 约 3 天，P3 约 2 天
**影响范围**：file_extractor.py, messageRenderer.js, app.py, fileUpload.js

---

# 一、问题诊断

## 1.1 现象描述

用户在聊天区点击 📎 按钮上传一个文件（如 PDF 报告、Word 文档），然后提问"请总结这个文件的核心观点"。AI 的回复往往只涉及文件的某个片段，甚至完全答非所问，给人"没看过文件"的感觉。

## 1.2 根因分析

当前代码中，聊天区上传的文件经历了以下流程：

```
用户拖拽/选择文件
  → handleFileSelect()          [fileUpload.js]
  → uploadPendingFiles()         [persist=false, 不入库]
  → POST /api/upload             [app.py]
  → extract_and_cache_chunks()   [file_extractor.py]
      ├─ 小文件 (<15000字符): 全文存为一个 chunk，返回 extractedText
      └─ 大文件 (≥15000字符): chunker 分块，存入内存 _chunk_cache
          → 返回 file_id，但 extractedText = null
                              → 前端拿不到文件全文
```

发送消息时 (`sendMessage()` in messageRenderer.js)：

```
小文件: extractedText 非空 → 拼入 finalContent → 发给 LLM     ✅ 正确
大文件: extractedText 为空 → 走 /api/search_chunks 检索
    → 用用户问题做 query，向量检索 Top-K 片段
    → 只把匹配的几个片段拼入 finalContent               ❌ 问题所在
```

**核心矛盾**：用户上传文件的意图是"请 AI 读一下这个文件"，但系统把它当成了"把文件存进知识库，然后按关键词检索"。这是两种完全不同的交互模式被混在了一条代码路径里。

## 1.3 影响面

| 场景 | 当前行为 | 用户期望 | 差距 |
|------|---------|---------|------|
| 上传小文件 (<15K字符) + 提问 | 全文注入上下文 | 全文注入上下文 | 无差距 |
| 上传大文件 (≥15K字符) + 提问 | 分块→向量检索→Top-K片段注入 | 全文注入上下文 | **严重差距** |
| 上传大文件 + 问的问题不在Top-K中 | AI 完全不知道文件内容 | AI 至少读过文件 | **致命差距** |
| 上传图片 (OCR) + 提问 | OCR全文注入 | 全文注入 | 无差距 |

## 1.4 受影响的代码路径

```
fileUpload.js
  ├─ handleFileSelect()        — 文件选择入口
  ├─ uploadPendingFiles()      — 上传并解析，persist=false
  └─ uploadDocFiles()          — 知识库上传入口，persist=true (此路径不受影响)

messageRenderer.js
  └─ sendMessage()             — 核心问题所在
      ├─ extractedFiles = STATE.uploadedFiles.filter(f => f.extractedText)
      ├─ smallFiles (小文件): 直接拼入 contextBlocks          ✅
      ├─ dbLargeFiles (大文件+documentId): /api/search_chunks  ❌ 问题代码
      └─ cacheLargeFiles (大文件+fileId): /api/search_chunks   ❌ 问题代码

file_extractor.py
  └─ _build_result()
      ├─ is_small_file(text) == True: 返回 extractedText       ✅
      └─ is_small_file(text) == False: 返回 extractedText=null ❌ 应返回全文
```

---

# 二、大厂方案对比

## 2.1 对话文件上传的两种范式

| 范式 | 代表产品 | 核心思路 | 适用场景 |
|------|---------|---------|---------|
| **全文注入** | ChatGPT, Claude, Gemini | 文件内容完整地进入模型上下文窗口 | 对话中上传文件，期望AI"读"文件 |
| **RAG检索** | 企业知识库, Coze, Dify | 文件分块建索引，按问题检索相关片段 | 知识库管理，大批量文档 |

关键区别：全文注入是"先读再说"，RAG是"按需检索"。用户在聊天区上传文件时，99%的意图是前者。

## 2.2 各产品具体实现

### ChatGPT
- 文件上传后直接解析全文，作为 message content 的一部分发给模型
- 文本文件：直接读取内容注入
- PDF/Word：解析后全文注入
- 数据文件(CSV/Excel)：通过 Code Interpreter 执行代码分析
- 不做分块、不做向量检索——128K~200K 上下文窗口足够容纳大多数文件

### Claude
- PDF/文档：全量提取文本后作为 message 的一部分发给模型
- 上下文窗口 200K tokens，约 15 万汉字，绝大多数文件能完整放下
- 不做 RAG，直接全文注入

### Gemini
- 原生多模态支持，文件作为 part 直接传入
- 上下文窗口 1M~2M tokens，几乎不需要分块

### Kimi (月之暗面)
- 对话上传：文件全文注入 (200K tokens 窗口)
- 知识库功能：独立的 RAG 检索模式 (与对话上传解耦)

## 2.3 Sophia Chat 应该采用的方案

**双轨制解耦**：

```
聊天区 📎 上传  →  全文注入路径 (FullContext Mode)
                    文件解析后全文拼入消息，直接发给 LLM
                    超出窗口时才降级为摘要/分段

知识库 📚 上传  →  RAG 检索路径 (现有逻辑保持不变)
                    分块 + embedding + 向量检索
                    对话中通过 autoKnowledgeBase 开关自动检索
```

---

# 三、架构设计

## 3.1 目标架构

```
                        ┌─────────────────────────────────────┐
                        │           用户上传文件                │
                        └──────────────┬──────────────────────┘
                                       │
                          ┌────────────┴────────────┐
                          │                         │
                    聊天区 📎                   知识库 📚
                  (临时上下文)               (持久化RAG)
                          │                         │
                          ▼                         ▼
                 ┌─────────────────┐      ┌──────────────────┐
                 │  全文解析路径     │      │  RAG 分块路径     │
                 │  (FullContext)   │      │  (保持现有逻辑)   │
                 └────────┬────────┘      └──────────────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │ Token 预估       │
                 │ file_tokens +    │
                 │ msg_tokens       │
                 └────────┬────────┘
                          │
              ┌───────────┴───────────┐
              │                       │
        < 上下文窗口 80%            > 上下文窗口 80%
              │                       │
              ▼                       ▼
     ┌────────────────┐      ┌────────────────┐
     │ 全文直接注入     │      │ 智能降级        │
     │ finalContent =  │      │ ├─ 超大文件分段 │
     │ 【文件】全文    │      │ ├─ 多文件合并   │
     │ + 用户问题      │      │ └─ 摘要兜底     │
     └────────────────┘      └────────────────┘
```

## 3.2 核心设计决策

1. **聊天区上传不再走 `/api/search_chunks`**：文件解析后直接返回全文，前端拼入消息内容
2. **大文件也返回全文**：`_build_result()` 对大文件也返回 `extractedText`，但同时保留 `is_large` 标记供前端判断
3. **前端做 Token 预估**：发送前估算文件+消息的总 token 数，决定是全文注入还是降级
4. **降级策略而非默认策略**：只有当文件确实超出窗口时才走分块检索，而非所有大文件都走
5. **知识库路径完全不动**：`persist=true` 的上传和 RAG 检索逻辑保持原样

---

# 四、任务拆解与实施计划

## P0：紧急修复 — 聊天上传全文注入（核心痛点）

**收益**：🔥🔥🔥🔥🔥 (最高 — 直接修复核心功能缺陷)
**风险**：🟢 低 (改动集中，不触碰知识库路径)
**工期**：约 0.5 天

### P0-1：后端 `_build_result()` 大文件返回全文

**文件**：`file_extractor.py` → `_build_result()`

**当前问题**：大文件返回 `extractedText = null`，前端只能走检索

**改动**：

```python
# file_extractor.py, _build_result() 函数，大文件分支
# 当前代码 (约第 260 行):
return {
    "success": True,
    "text": f"(文件较大，已分为 {len(chunks)} 个段落，请描述你想了解的内容)",
    "filename": filename,
    "is_large": True,
    ...
}

# 改为: 同时返回全文和分块信息
return {
    "success": True,
    "text": f"(文件较大，已分为 {len(chunks)} 个段落，请描述你想了解的内容)",
    "extracted_text": text,          # 新增：返回全文
    "is_large": True,
    "document_id": doc_id,
    "chunk_count": len(chunks),
    "preview": preview_text,
    "file_size_chars": len(text),     # 新增：字符数，供前端判断
}
```

**风险点**：大文件全文传输会增加 HTTP 响应体积。需确认 Flask `MAX_CONTENT_LENGTH` 和前端 fetch 没有响应体大小限制。实际上文本文件即使 50MB，解析后的纯文本通常不超过 5MB，JSON 传输无压力。

### P0-2：后端 `/api/upload` 返回 `extracted_text`

**文件**：`app.py` → `upload_file()`

**当前问题**：`local` 模式的响应中没有 `extracted_text` 字段（仅 `native` 模式有）

**改动**：

```python
# app.py, upload_file() 函数, local 模式响应 (约第 825 行)
if result["success"]:
    resp = {
        "success": True,
        "filename": result["filename"],
        "is_large": result.get("is_large", False),
        "preview": result.get("preview", ""),
        "upload_mode": "local",
        "persisted": persist,
        "extracted_text": result.get("extracted_text", ""),  # 新增
        "file_size_chars": result.get("file_size_chars", 0),  # 新增
    }
```

### P0-3：前端 `uploadPendingFiles()` 保存全文

**文件**：`fileUpload.js` → `uploadPendingFiles()`

**当前问题**：`item.extractedText` 对大文件为 null

**改动**：

```javascript
// fileUpload.js, uploadPendingFiles(), 约第 66 行
if (result.success) {
    item.extractedText = result.extracted_text || null;  // 现在大文件也有值
    item.isLarge = result.is_large || false;
    item.fileSizeChars = result.file_size_chars || 0;    // 新增
    // ...其余不变
}
```

### P0-4：前端 `sendMessage()` 改为全文注入

**文件**：`messageRenderer.js` → `sendMessage()`

**当前问题**：大文件走 `/api/search_chunks`，只注入片段

**改动**：

```javascript
// messageRenderer.js, sendMessage(), 约第 470-567 行
// 替换整个 extractedFiles 处理块

if (extractedFiles.length > 0) {
    const contextBlocks = [];

    for (const f of extractedFiles) {
        fileNames.push(f.name);

        if (!f.isLarge) {
            // 小文件：全文注入 (不变)
            contextBlocks.push(`【附件: ${f.name}】\n\n${f.extractedText}`);
        } else {
            // 大文件：先尝试全文注入，超窗口再降级
            const fileTokens = estimateTokens(f.extractedText);
            const msgTokens = estimateTokens(text || '');
            const CONTEXT_LIMIT = 100000; // 约 128K 窗口的 80%

            if (fileTokens + msgTokens < CONTEXT_LIMIT) {
                // 全文注入
                contextBlocks.push(`【附件: ${f.name}】\n\n${f.extractedText}`);
            } else {
                // 降级：向量检索相关片段
                try {
                    const searchBody = {};
                    if (f.documentId) searchBody.document_ids = [f.documentId];
                    else if (f.fileId) searchBody.file_id = f.fileId;
                    searchBody.query = text || '';

                    const resp = await fetch('/api/search_chunks', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(searchBody)
                    });
                    const result = await resp.json();
                    if (result.success && result.context) {
                        contextBlocks.push(`【附件: ${f.name} - 相关内容】\n\n${result.context}`);
                        showToast(`文件 ${f.name} 较大，已注入最相关的内容片段`, 'info');
                    } else if (f.preview) {
                        contextBlocks.push(`【附件: ${f.name} - 前3000字预览】\n\n${f.preview}`);
                    }
                } catch (err) {
                    if (f.preview) {
                        contextBlocks.push(`【附件: ${f.name} - 前3000字预览】\n\n${f.preview}`);
                    }
                }
            }
        }
    }

    if (contextBlocks.length > 0) {
        finalContent = contextBlocks.join('\n\n---\n\n') + '\n\n---\n\n' + (text || '');
    }
}
```

### P0 验证清单

- [ ] 上传 50KB PDF → 提问 → AI 回复内容引用了文件全文
- [ ] 上传 200KB Word → 提问 → AI 回复内容引用了文件全文
- [ ] 上传 5MB PDF → 提问 → 控制台显示"较大，已注入最相关片段"
- [ ] 知识库 📚 上传 → 检索 → 功能不受影响
- [ ] autoKnowledgeBase 自动检索 → 功能不受影响

---

## P1：体验优化 — 多文件合并与智能降级

**收益**：🔥🔥🔥🔥 (高 — 多文件场景体验显著提升)
**风险**：🟡 中 (涉及 Token 预估精度，需调参)
**工期**：约 2 天

### P1-1：多文件 Token 预估与合并策略

**问题**：用户同时上传 3 个文件，每个 40K tokens，单独都不超限但合计 120K 超限。当前逻辑会全部全文注入，导致请求被 LLM 拒绝。

**方案**：

```javascript
// messageRenderer.js, sendMessage() 中新增多文件合并逻辑

if (extractedFiles.length > 0) {
    const CONTEXT_LIMIT = 100000;
    let remainingBudget = CONTEXT_LIMIT - estimateTokens(text || '');

    // 按文件大小排序：小文件优先注入（更容易全部放下）
    const sorted = [...extractedFiles].sort((a, b) =>
        (a.fileSizeChars || 0) - (b.fileSizeChars || 0)
    );

    const contextBlocks = [];
    const overflowFiles = [];

    for (const f of sorted) {
        const fileTokens = estimateTokens(f.extractedText || '');
        if (fileTokens <= remainingBudget) {
            // 预算够：全文注入
            contextBlocks.push(`【附件: ${f.name}】\n\n${f.extractedText}`);
            remainingBudget -= fileTokens;
            fileNames.push(f.name);
        } else {
            // 预算不够：加入溢出列表
            overflowFiles.push(f);
            fileNames.push(f.name);
        }
    }

    // 溢出文件走降级检索
    for (const f of overflowFiles) {
        const searchResult = await searchFileChunks(f, text);
        if (searchResult) {
            contextBlocks.push(`【附件: ${f.name} - 相关内容】\n\n${searchResult}`);
        }
    }

    if (contextBlocks.length > 0) {
        finalContent = contextBlocks.join('\n\n---\n\n') + '\n\n---\n\n' + (text || '');
    }
}
```

### P1-2：服务商上下文窗口感知

**问题**：`CONTEXT_LIMIT = 100000` 是硬编码值。不同模型窗口差异巨大（8K~2M），应动态获取。

**方案**：在 `providers/registry.py` 中为每个服务商/模型标注上下文窗口大小：

```python
# registry.py, PROVIDERS 字典中每个模型补充 context_window
"kimi": {
    "models": ["kimi-k2.6", "kimi-k2.5", ...],
    "model_context_windows": {
        "kimi-k2.6": 200000,
        "kimi-k2.5": 200000,
        "moonshot-v1-8k": 8000,
        "moonshot-v1-128k": 131072,
    },
    ...
}
```

前端在 `sendMessage()` 中从 `STATE.providers` 读取当前模型的窗口大小：

```javascript
const provider = STATE.providers.find(p => p.key === STATE.activeProvider);
const modelMeta = provider?.model_context_windows?.[STATE.activeModel];
const contextWindow = modelMeta || 32768;  // 默认保守值
const CONTEXT_LIMIT = Math.floor(contextWindow * 0.7);  // 留 30% 给回复
```

### P1-3：上传进度与文件状态增强

**问题**：大文件解析慢时用户只看到 "uploading" 状态，不知道进度。

**方案**：后端 `/api/upload` 增加 streaming response（SSE），分阶段返回解析进度：

```
data: {"stage": "parsing", "message": "正在解析 PDF..."}
data: {"stage": "extracting", "message": "正在提取文本..."}
data: {"stage": "done", "extracted_text": "...", "is_large": false}
data: [DONE]
```

---

## P2：深度优化 — 超大文件智能分段与摘要

**收益**：🔥🔥🔥 (中 — 仅影响超大文件场景)
**风险**：🟠 较高 (涉及 LLM 摘要调用，增加延迟和成本)
**工期**：约 3 天

### P2-1：超大文件分段注入

**问题**：文件 500K tokens，模型窗口 128K。降级为 RAG 检索丢失了全局上下文。

**方案**：将文件按章节分段，每段 ≤ 60K tokens，多轮对话中分段注入：

```
第1轮: 用户上传文件 → AI 回复 "已收到文件，正在分段阅读第1部分(章节1-3)..."
第2轮: 自动注入第2部分 → AI 继续阅读
...
第N轮: 全部读完后 → AI 回复 "我已读完整个文件，请问您有什么问题？"
```

这是 Claude 对超长文档的处理方式——不丢内容，而是分多轮读取。

### P2-2：文件摘要兜底

**问题**：用户上传 100MB 日志文件，不可能全文注入。

**方案**：对超过模型窗口 3 倍的文件，先调用 LLM 生成摘要，注入摘要而非全文：

```python
# app.py 新增 /api/file/summarize 端点
@app.route("/api/file/summarize", methods=["POST"])
@login_required
def summarize_file():
    """对超大文件生成摘要"""
    data = request.json
    document_id = data.get("document_id")
    # 从 DB 读取分块，每块生成摘要，再合并
    chunks = get_chunks_by_document(document_id)
    summaries = []
    for chunk in chunks:
        summary = llm_summarize(chunk["text"], max_tokens=500)
        summaries.append(summary)
    final_summary = llm_summarize("\n".join(summaries), max_tokens=2000)
    return jsonify({"summary": final_summary})
```

### P2-3：文件类型感知注入策略

**问题**：不同文件类型应该用不同的注入策略。代码文件应该保留完整结构；表格数据应该转为 Markdown 表格；图片应该走多模态。

**方案**：

| 文件类型 | 策略 | 注入格式 |
|---------|------|---------|
| 纯文本/Markdown | 全文注入 | 原文 |
| PDF | 全文注入 | MarkItDown 输出 |
| Word/PPT | 全文注入 | MarkItDown 输出 |
| Excel/CSV | 按行数决定 | Markdown 表格 (前N行) |
| 代码文件 | 全文注入 | language 代码块 |
| 图片 | 多模态 | base64 → image_url |
| 超大日志 | 摘要+尾部 | 摘要 + 最后 1000 行 |

---

## P3：架构治理 — 上传路径彻底解耦

**收益**：🔥🔥 (低 — 代码整洁度提升，用户无感)
**风险**：🔴 高 (重构核心路径，可能引入回归)
**工期**：约 2 天

### P3-1：上传路径分离为两个独立端点

**当前问题**：`/api/upload` 同时承担聊天附件和知识库入库两个职责，通过 `persist` 参数切换。这导致逻辑耦合，且聊天上传会不必要地执行分块逻辑。

**方案**：

```
/api/chat/upload    — 聊天附件上传 (只解析，不分块，不入库)
/api/kb/upload      — 知识库上传 (解析 + 分块 + embedding + 入库)
```

聊天上传端点简化逻辑：

```python
@app.route("/api/chat/upload", methods=["POST"])
@login_required
def chat_upload():
    """聊天附件上传 — 只解析全文，不做分块/入库"""
    file = request.files['file']
    text = extract_text_only(file)  # 只解析，不分块
    return jsonify({
        "success": True,
        "extracted_text": text,
        "filename": file.filename,
        "file_size_chars": len(text),
    })
```

### P3-2：前端上传函数分离

```javascript
// fileUpload.js
// 聊天上传 → /api/chat/upload
async function uploadChatAttachment(file) { ... }

// 知识库上传 → /api/kb/upload
async function uploadKnowledgeBaseDoc(file) { ... }
```

### P3-3：废弃内存缓存路径

**当前问题**：`_chunk_cache` (OrderedDict) 是为 `persist=false` 的大文件设计的内存缓存。P0 改为全文注入后，这条路径不再需要。

**方案**：标记 `_cache_put` / `_cache_get` / `search_cached_chunks` 中的 file_id 路径为 deprecated，下个版本移除。

---

# 五、风险矩阵

| 任务 | 风险等级 | 风险描述 | 缓解措施 |
|------|---------|---------|---------|
| P0-1 | 🟢 低 | 大文件全文传输增加响应体积 | 纯文本50MB→约5MB JSON，在 Flask 限制内 |
| P0-2 | 🟢 低 | API 响应格式变更，旧前端不兼容 | 前后端同步部署，无第三方调用 |
| P0-3 | 🟢 低 | 前端变量名变更 | 仅影响内部状态，不影响 UI |
| P0-4 | 🟡 中 | Token 预估不准导致超限 | 预估值偏保守(80%窗口)，超限时LLM返回错误可重试 |
| P1-1 | 🟡 中 | 多文件排序策略可能不是最优 | 小文件优先是最稳妥策略，后续可优化 |
| P1-2 | 🟡 中 | registry.py 需要维护每个模型的窗口大小 | 先覆盖主流模型，未知模型用保守默认值 |
| P1-3 | 🟠 较高 | SSE 上传进度改造涉及前后端协议变更 | 可选实现，不影响核心功能 |
| P2-1 | 🟠 较高 | 多轮自动注入需要状态管理 | 需要在 conversation 中存储 reading_state |
| P2-2 | 🟠 较高 | 摘要调用增加 LLM 成本和延迟 | 仅对超过窗口3倍的文件触发，用户可跳过 |
| P2-3 | 🟡 中 | 不同文件类型策略需要充分测试 | 分类型逐步上线 |
| P3-1 | 🔴 高 | 端点分离可能影响已有调用方 | 保留 /api/upload 作为兼容入口3个月 |
| P3-2 | 🔴 高 | 前端重构可能引入回归 | 充分回归测试 |
| P3-3 | 🟡 中 | 废弃内存缓存可能影响旧版客户端 | 标记 deprecated，下个大版本移除 |

---

# 六、实施顺序建议

```
Week 1
  ├─ Day 1: P0-1 + P0-2 + P0-3 + P0-4 (紧急修复，0.5天)
  └─ Day 2-3: 回归测试 + P1-1 (多文件合并)

Week 2
  ├─ Day 1-2: P1-2 (模型窗口感知)
  └─ Day 3: P1-3 (上传进度，可选)

Week 3
  ├─ Day 1-3: P2-1 (分段注入) 或 P2-2 (摘要兜底) 二选一
  └─ Day 4-5: P2-3 (文件类型感知)

Week 4 (可选)
  └─ P3-1 + P3-2 + P3-3 (架构解耦，建议大版本迭代时做)
```

---

# 七、回归测试清单

## 7.1 P0 回归测试

| # | 场景 | 预期结果 | 验证方法 |
|---|------|---------|---------|
| 1 | 上传 10KB TXT + 提问 | AI 回复引用全文 | 检查 finalContent 包含全文 |
| 2 | 上传 100KB PDF + 提问 | AI 回复引用全文 | 检查 finalContent 包含全文 |
| 3 | 上传 500KB Word + 提问 | AI 回复引用全文或降级提示 | 检查 Token 预估逻辑 |
| 4 | 上传 5MB PDF + 提问 | 降级为相关片段注入 | 检查 /api/search_chunks 被调用 |
| 5 | 上传图片 + 提问 | OCR 全文注入 | 检查 extractedText 非空 |
| 6 | 知识库上传文档 | 正常入库，分块+embedding | 检查 documents 表 |
| 7 | 知识库搜索 | 跨文档语义检索正常 | 检查返回结果 |
| 8 | autoKnowledgeBase 开关 | 自动检索注入正常 | 检查 finalContent 含【知识库】标记 |
| 9 | native 上传模式 (Kimi) | 云端解析正常 | 检查 provider_file_id |
| 10 | 重复文件上传 | 覆盖/跳过弹窗正常 | 检查 overwrite 逻辑 |

## 7.2 P1 回归测试

| # | 场景 | 预期结果 |
|---|------|---------|
| 1 | 同时上传 3 个小文件 | 全部全文注入 |
| 2 | 上传 1 小 + 1 超大文件 | 小文件全文 + 大文件降级 |
| 3 | 切换不同模型 | CONTEXT_LIMIT 随模型窗口变化 |
| 4 | 使用 8K 窗口模型 | 小文件也可能触发降级 |

## 7.3 P2 回归测试

| # | 场景 | 预期结果 |
|---|------|---------|
| 1 | 上传 500K tokens 文件 | 分段注入，多轮对话 |
| 2 | 上传 100MB 日志文件 | 摘要注入 |
| 3 | 上传 Excel 文件 | Markdown 表格注入 |
| 4 | 上传 .py 代码文件 | 代码块注入 |

---

# 八、附录

## 8.1 当前代码路径关键行号

| 文件 | 函数 | 行号 | 说明 |
|------|------|------|------|
| file_extractor.py | `_build_result()` | 168-283 | 大文件返回 extractedText=null 的位置 |
| file_extractor.py | `extract_and_cache_chunks()` | 290-358 | 上传主入口，分流逻辑 |
| app.py | `upload_file()` | 760-849 | /api/upload 端点 |
| app.py | `search_chunks_route()` | 852-896 | /api/search_chunks 端点 |
| fileUpload.js | `uploadPendingFiles()` | 43-99 | 前端上传逻辑 |
| messageRenderer.js | `sendMessage()` | 443-642 | 消息发送主逻辑 |
| messageRenderer.js | `sendMessage()` | 470-567 | extractedFiles 处理块 (核心改动区域) |
| messageRenderer.js | `_doSend()` | 248-419 | SSE 流式请求 |
| chunker.py | `SMALL_FILE_THRESHOLD` | 9 | 小文件阈值=15000字符 |
| cache_manager.py | `_L2_SIMILARITY_THRESHOLD` | 27 | 语义缓存相似度阈值=0.93 |

## 8.2 Token 预估公式

当前代码中的 `estimateTokens()` (conversationManager.js):

```javascript
function estimateTokens(text) {
    const cjk = (text.match(/[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/g) || []).length;
    const words = (text.match(/[a-zA-Z]+/g) || []).length;
    const digits = (text.match(/[0-9]+/g) || []).length;
    const other = Math.max(0, text.length - cjk - ...);
    return Math.ceil(cjk * 2 + words * 1.3 + digits * 0.5 + other * 0.5);
}
// 粗略公式：中文 ~2 token/字，英文 ~1.3 token/词
// 15000 字符中文 ≈ 30000 tokens
// 15000 字符英文 ≈ ~10000 tokens
// 这个阈值在 128K 窗口下过于保守，P1-2 中改为动态窗口后自动适配
```

## 8.3 各模型上下文窗口参考

| 模型 | 上下文窗口 (tokens) | 约等于汉字数 |
|------|-------------------|------------|
| moonshot-v1-8k | 8,000 | ~4,000 字 |
| deepseek-v4-pro | 128,000 | ~64,000 字 |
| kimi-k2.6 | 200,000 | ~100,000 字 |
| moonshot-v1-128k | 131,072 | ~65,000 字 |
| gemini-2.5-pro | 1,000,000 | ~500,000 字 |
| gpt-5.3-codex | 200,000 | ~100,000 字 |
| claude-haiku-4.5 | 200,000 | ~100,000 字 |

注：当前 `SMALL_FILE_THRESHOLD = 15000` 字符，对应约 30K tokens (中文)。在 8K 窗口模型下已经超限，但在 128K+ 窗口模型下远未达到上限。这也是 P1-2 (模型窗口感知) 需要解决的核心问题。
