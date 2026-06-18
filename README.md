# Sophia Chat — 多模型 AI 聊天应用

一个支持 **18+ 国内主流大语言模型** 的桌面聊天应用，基于 Flask + 原生前端实现，支持知识库 RAG、文件解析 OCR、多对话管理、SSE 流式输出。

---

## ✨ 功能特性

- 🚀 **多模型支持**：DeepSeek、Kimi、智谱 GLM、通义千问、文心一言、豆包、NVIDIA NIM、数眼智能、腾讯云 MaaS、硅基流动、书生·浦语、小米 MiMo、星火 Pro/X2/X2 Flash、weelinking、tokenDance
- 🔒 **安全可靠**：API Key Fernet 加密存储于 `~/.workbuddy/`，CSRF 防护，API 速率限制，会话安全隔离
- 📚 **知识库 RAG**：上传文档自动分块+向量化，支持语义检索，聊天气泡引用
- 📎 **文件解析**：MarkItDown + RapidOCR，支持 PDF/Word/PPT/Excel/图片等 20+ 格式
- 🔐 **用户认证**：注册/登录/登出，多用户数据隔离，会话持久化
- 💬 **多对话管理**：新建、切换、删除、搜索、重命名对话，自动生成语义标题
- ⚡ **流式输出**：SSE 实时显示 AI 回复，支持中止生成，切换对话不中断流式
- 📋 **代码高亮**：Highlight.js 自动识别并高亮代码块，支持一键复制
- 🔄 **重新生成**：一键重新生成不满意的回复，支持切换模型后重新生成
- ⚡ **Prompt 模板**：三级人设机制（全局 → 模板 → 默认），内置 10 个模板，支持自定义
- 📊 **Token 计数**：输入框实时预估 Token 数，绿/黄/红阈值预警
- 💾 **草稿保存**：切换对话自动保存输入框内容，切回时恢复
- 🔍 **对话搜索**：搜索标题和消息内容，关键词高亮
- 📥 **对话导出**：Markdown 下载 / PDF 打印导出
- 🎨 **双皮肤**：经典深蓝 + 现代设计，支持浅色/深色主题切换

---

## 📦 支持的服务商

| 服务商 | 模型示例 | 认证方式 |
|--------|----------|----------|
| DeepSeek | deepseek-v4-pro, deepseek-v4-flash | Bearer Token |
| Kimi (月之暗面) | kimi-k2.6, kimi-k2-thinking | Bearer Token |
| 智谱 (GLM) | glm-4-plus, glm-4.7, glm-5.1 | Bearer Token |
| 通义千问 (Qwen) | qwen-plus, qwen-max, qwen-turbo | Bearer Token |
| 文心一言 (ERNIE) | ernie-4.0-turbo, minimax-m2.5 | Bearer Token |
| 豆包 (字节) | doubao-seed-2-0-pro, doubao-seed-2-0-mini | HMAC-SHA256 |
| NVIDIA NIM | deepseek-v4-pro, llama-3.1-405b | Bearer Token |
| 数眼智能 | mimo-v2-pro, mimo-v2.5-pro | Bearer Token |
| 腾讯云 MaaS | 聚合多模型（DeepSeek/GLM/Kimi/Hunyuan） | Bearer Token |
| 硅基流动 | GLM-5, DeepSeek-V3.2, Qwen3 全系列 | Bearer Token |
| 书生·浦语 | intern-latest, intern-s1-pro | Bearer Token |
| 小米 MiMo | mimo-v2.5-pro, mimo-v2-pro | Bearer Token |
| 讯飞星火 Pro | generalv3 | Bearer Token |
| 讯飞星火 X2 | spark-x | Bearer Token |
| 讯飞星火 X2 Flash | spark-x-flash | Bearer Token |
| weelinking | gpt-5, claude-sonnet, gemini-2.5 等 | Bearer Token |
| tokenDance | mimo-v2.5-pro, deepseek-v4-pro | Bearer Token |

---

## 📁 项目结构

```
llm-chat/
│
├── app.py                   # Flask 主入口（路由/SSE/文件API/安全中间件）
├── auth.py                  # 用户认证（注册/登录/登出）
├── database.py              # SQLite CRUD（用户/会话/消息/知识库文档）
├── config_manager.py        # 配置管理 + API Key Fernet 加密持久化
├── cache_manager.py         # 双层缓存（L1 精确 + L2 语义相似度 / ONNX Runtime）
├── templates.py             # Prompt 模板管理器
├── file_extractor.py        # MarkItDown + OCR 文件解析
├── chunker.py               # Markdown 语义分块 + 关键词检索
├── ocr_engine.py            # RapidOCR 封装（图片/扫描版 PDF）
├── desktop.py               # pywebview 桌面版入口
├── convert_model.py         # Embedding 模型导出为 ONNX 格式（打包前执行一次）
├── backfill_embeddings.py   # 知识库 embedding 历史数据补算脚本
├── requirements.txt         # 生产依赖
├── README.md                # 本文件
├── LICENSE                  # MIT 开源协议
├── sophia_chat.spec         # PyInstaller 打包配置
├── build.bat                # Windows 一键打包构建脚本
│
├── providers/               # LLM 服务商适配器
│   ├── __init__.py          # 包入口
│   ├── registry.py          # 18+ 服务商元数据配置
│   ├── base.py              # BaseAdapter 抽象基类
│   ├── openai_compat.py     # OpenAI 兼容协议通用适配
│   └── weelinking.py        # Weelinking 专用适配器
│
└── static/                  # 前端静态资源
    ├── index.html           # 主页面
    ├── style.css            # 全局样式
    ├── app.js               # 前端入口
    ├── manifest.json        # PWA 清单
    ├── logo.jpg             # Logo 图片
    ├── icon.ico / favicon.ico
    ├── images/              # PWA 图标（72~512px，11 个）
    ├── js/                  # 前端 JS 模块
    │   ├── state.js         # 全局状态 & DOM 引用
    │   ├── utils.js         # 工具函数（toast/fetch/markdown）
    │   ├── conversationManager.js  # 对话 CRUD + Token 估算
    │   ├── fileUpload.js    # 文件上传 + 知识库管理
    │   ├── messageRenderer.js     # SSE 流式 + Markdown 渲染
    │   └── uiManager.js     # 设置/主题/模板/事件初始化
    └── skins/               # CSS 皮肤
        ├── classic.css      # 经典深蓝风格
        └── modern.css       # 现代设计风格
```

---

## 🏗️ 架构说明

### 系统架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                      浏览器 / 桌面端                          │
│          Vanilla JS (无框架) + Marked.js + Highlight.js       │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP/SSE (EventStream)
┌──────────────────────────▼──────────────────────────────────┐
│                     Flask 后端 (app.py)                       │
│  ┌─────────┬──────────┬──────────┬──────────┬─────────────┐ │
│  │ 认证模块 │ CSRF防护  │ 速率限制 │ 会话管理  │ 活跃流管理   │ │
│  │ auth.py │ flask-wtf│flask-limiter│login│ threading.Event│ │
│  └─────────┴──────────┴──────────┴──────────┴─────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│  LLM 适配器层  │ │  知识库 RAG    │ │  文件解析层    │
│ providers/    │ │ chunker.py    │ │ file_extractor │
│ 18+ 服务商    │ │ cache_manager │ │ ocr_engine.py  │
└───────┬───────┘ └───────┬───────┘ └───────┬───────┘
        │                 │                  │
        ▼                 ▼                  ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ 外部 LLM API  │ │  SQLite WAL   │ │  ONNX Runtime │
│ DeepSeek/Kimi │ │ 用户/会话/文档 │ │ Embedding+OCR │
│ GLM/Qwen/...  │ │   + 向量存储   │ │ 本地推理引擎  │
└───────────────┘ └───────────────┘ └───────────────┘
```

**核心数据流**：用户发送消息 → 缓存查询 (L1→L2) → 命中则直接返回，未命中 → 知识库检索注入上下文 → LLM 流式生成 → 写入缓存。

### 文件解析流水线

项目对上传文件采用**格式分流 + OCR 兜底**策略，覆盖 20+ 种文件格式：

```
上传文件
  │
  ├─ 图片 (.jpg/.png/...) ──► RapidOCR (ONNX Runtime) ──► 文本
  │
  ├─ PDF (.pdf)
  │    ├─ 1) MarkItDown 提取文本 ──► 有内容 → 文本
  │    └─ 2) 结果为空 → 检测扫描版 → OCR 兜底
  │
  └─ 其他 (.docx/.pptx/.xlsx/.html/.csv/.json/.md/.txt/...)
       └─► MarkItDown ──► 文本
            │
            ├─ 小文件 (≤15KB) → 全文注入
            └─ 大文件 (>15KB) → 语义分块 → 关键词/向量检索
```

| 引擎 | 技术 | 处理对象 | 打包体积 |
|------|------|---------|---------|
| MarkItDown | Microsoft 开源文档转换 | Word/PPT/Excel/HTML/CSV/JSON/PDF等 | ~2 MB |
| RapidOCR | ONNX Runtime + PP-OCRv4 | 图片、扫描版 PDF | ~28 MB |

### 知识库 RAG 流水线

```
文档上传                查询时检索
────────               ────────
  │                      │
  ▼                      ▼
文件解析              用户提问
  │ (MarkItDown/OCR)     │
  ▼                      ▼
Markdown 文本         get_embedding()
  │ (chunker.py)         │ (ONNX Runtime + CLS Token)
  ▼                      ▼
语义分块             向量 (512维)
  │                      │
  ▼                      ▼
save_chunks()        search_chunks_by_embedding()
  │ (ONNX batch infer)   │ (余弦相似度 + 向量检索)
  ▼                      ▼
向量 (512维)          匹配 Top-K 分块
  │                      │
  ▼                      ▼
SQLite chunks 表      注入 LLM 上下文
                       (多文档标注来源)
```

**分块策略**：
- 小文件（≤15,000 字符）：全文存储为单块
- 大文件：按 Markdown 标题层级切分，单块上限 8,000 字符
- 超大块：按段落二次拆分，携带上下文锚点句避免信息断裂
- 代码块保护：切分时保留完整代码块不被截断

### 分层响应缓存

减少重复 LLM 调用，节省 Token 和延迟：

```
用户提问
  │
  ▼
L1 精确匹配 (ExactCache)
  │  MD5(provider:model:question) → 内存 OrderedDict
  │  容量: 500条 | TTL: 2小时 | 零额外成本
  │
  ├─ 命中 → 模拟 SSE 流式返回 (X-Cache-Hit: l1)
  │
  └─ 未命中
       │
       ▼
L2 语义相似度 (SemanticCache)
  │  ONNX 本地向量化 → numpy 批量余弦相似度 → 阈值 0.93
  │  容量: 2000条 | TTL: 24小时 | < 0.5ms 全量检索
  │
  ├─ 命中 → 模拟 SSE 流式返回 (X-Cache-Hit: l2)
  │
  └─ 未命中 → 调用 LLM → 同时写入 L1 + L2
```

### Embedding 向量化优化

| 方案 | 依赖 | 模型大小 | 打包体积 |
|------|------|---------|---------|
| ~~sentence-transformers~~ | torch (~2.5GB) + transformers (~500MB) | 90MB | +420 MB |
| **ONNX Runtime + tokenizers** | onnxruntime (~28MB) + tokenizers (~3MB) | 90MB → ONNX | **共享 OCR 运行时** |

- 使用 `bge-small-zh-v1.5` 导出为 ONNX 格式，512 维向量
- 取 `[CLS]` token 的 hidden state 并 L2 归一化
- 支持批量推理（batch_size=32），大幅优于逐条编码
- 启动时后台异步预热，不阻塞服务可用

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- pip

### 安装与启动

```bash
cd llm-chat
pip install -r requirements.txt
python app.py
```

浏览器访问 http://127.0.0.1:5000

> 后端基于 **Waitress** 生产级 WSGI 服务器。可通过环境变量自定义地址/端口：
> ```bash
> HOST=0.0.0.0 PORT=8080 python app.py
> ```

### 桌面模式

```bash
# pywebview 已包含在 requirements.txt 中
python app.py --desktop
```

### 打包为独立 EXE（Windows）

```bash
# 1. 先导出 Embedding 模型为 ONNX 格式（打包前执行一次）
python convert_model.py

# 2. 一键打包
build.bat

# 或手动打包
pip install pyinstaller
pyinstaller sophia_chat.spec --clean --noconfirm
```

> 打包输出目录：`dist/Sophia Chat/`，主程序：`dist/Sophia Chat/Sophia Chat.exe`

---

## 🔧 配置说明

### 首次使用

1. 访问首页 → **注册**账号 → **登录**
2. 左侧边栏选择**服务商** → 点击 ⚙️ **设置**
3. 填写 **API Key**（豆包需 Access Key ID + Secret Key）
4. 保存后即可开始聊天

### Prompt 模板

点击输入框 ⚡ 按钮快速选择模板：

- **代码助手** — 代码审查、Bug 修复、架构设计
- **文本处理** — 翻译、润色、总结、摘要
- **学习辅导** — 概念解释、学习计划、知识问答
- **分析决策** — 数据分析、方案对比、决策辅助
- **创意写作** — 故事、营销文案、朋友圈文案

支持创建自定义模板和变量替换。

### 知识库

点击 📚 按钮打开知识库弹窗：

- **上传文档**：支持 PDF/Word/PPT/Excel/图片等 20+ 格式
- **自动去重**：重复文件名自动检测并提示覆盖或跳过
- **语义搜索**：输入自然语言搜索文档内容
- **分块预览**：点击 👁️ 查看文档分块详情
- **批量删除**：勾选多个文档一键删除
- **排序筛选**：按时间/文件名/大小/分块数排序

聊天气泡中上传的文件也会自动加入知识库。

### 高级设置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| Temperature | 0 = 精确，2 = 创造性 | 0.7 |
| Max Tokens | 单次回复最大长度 | 4096 |
| 上下文消息数 | 历史消息条数 (2~200) | 20 |
| 全局人设 | 自定义 System Prompt | — |

---

## 🔒 安全机制

| 防护层 | 实现方式 | 说明 |
|--------|---------|------|
| API Key 加密 | `cryptography.fernet` + PBKDF2 | 敏感字段持久化前加密，密钥随机生成存于本地 |
| CSRF 防护 | `flask-wtf CSRFProtect` | 所有 POST/PUT/PATCH/DELETE 请求校验 CSRF Token |
| 速率限制 | `flask-limiter` | 聊天 20次/分，登录 10次/分，注册 5次/分，上传 20次/分 |
| 会话安全 | `flask-login` | HttpOnly Cookie + 登录态管理，多用户数据隔离 |
| 文件上传校验 | 扩展名白名单 + 常见头魔数校验 | 防止恶意文件上传 |
| SQLite WAL 模式 | `PRAGMA journal_mode=WAL` | 并发安全 + 性能优化 |

---

## 📝 使用技巧

| 操作 | 方式 |
|------|------|
| 新建对话 | 点击 "＋ 新建对话" |
| 发送消息 | Enter（Shift+Enter 换行） |
| 中止生成 | 点击 ■ 按钮 |
| 重新生成 | 点击 🔄 重新生成 |
| 复制代码 | 点击代码块右上角 📋 |
| 复制回复 | 点击 AI 回复底部 📋 |
| 复制用户消息 | 点击用户气泡底部 📋 |
| 切换主题 | 点击左下角 ☀️/🌙 |
| 上传文件 | 点击 📎 按钮 |
| 搜索对话 | 点击 🔍 图标 |
| 导出对话 | 点击 📥 按钮 |
| 知识库 | 点击 📚 按钮 |

---

## 🔒 API Key 申请地址

| 服务商 | 申请地址 |
|--------|----------|
| DeepSeek | https://platform.deepseek.com/ |
| Kimi | https://platform.moonshot.cn/ |
| 智谱 | https://open.bigmodel.cn/ |
| 通义千问 | https://bailian.console.aliyun.com/ |
| 文心一言 | https://console.bce.baidu.com/ |
| 豆包 | https://console.volcengine.com/ |
| 硅基流动 | https://cloud.siliconflow.cn/ |
| 书生·浦语 | https://chat.intern-ai.org.cn/ |
| 小米 MiMo | https://api.xiaomimimo.com/ |
| 讯飞星火 | https://console.xfyun.cn/ |
| weelinking | https://www.weelinking.com/ |
| tokenDance | https://tokendance.space/ |

---

## ❓ 常见问题

### 启动失败：端口 5000 被占用
设置环境变量换端口：`PORT=8080 python app.py`

### 发送消息后无响应
- 检查 API Key 是否正确
- 确认网络可访问对应服务商
- 登录服务商官网查看账户余额
- 查看终端 `[DEBUG]` 日志

### 代码高亮不显示
CDN 加载失败会**自动降级**为纯文本显示，不影响使用。

### 知识库检索无结果
确保已运行 `python convert_model.py` 生成 ONNX embedding 模型文件至 `models/` 目录。历史数据需执行 `python backfill_embeddings.py` 补算向量。

### 配置文件位置
- **Windows**：`C:\Users\<用户名>\.workbuddy\llm-chat-config.json`
- **macOS/Linux**：`~/.workbuddy/llm-chat-config.json`

> 迁移配置：复制该文件到新电脑对应位置即可。API Key 已加密，迁移后可直接使用。

---

## 🛠️ 技术栈

**后端**
- Flask 3.x — Web 框架
- Flask-Login — 用户会话管理
- Flask-WTF — CSRF 防护
- Flask-Limiter — API 速率限制
- SQLite (WAL mode) — 数据持久化
- Waitress — 生产级 WSGI 服务器
- Cryptography (Fernet) — API Key 加密存储
- MarkItDown — 多格式文件解析
- RapidOCR (ONNX Runtime) — 图片/扫描版 PDF 文字识别
- ONNX Runtime + Tokenizers — Embedding 向量化（轻量替代 sentence-transformers，省 420 MB 依赖）
- PyInstaller — Windows 桌面端打包

**前端**
- Vanilla JavaScript — 无框架，模块化组织
- Marked.js — Markdown 渲染（CDN 加载）
- Highlight.js — 代码高亮（CDN 加载）
- DOMPurify — XSS 防护（CDN 加载）
- CSS3 变量 — 主题/皮肤系统

---

## 📄 开源协议

MIT License — 可自由使用、修改和分发。

---

## 🙏 致谢

- [DeepSeek](https://www.deepseek.com/) · [Kimi](https://kimi.moonshot.cn/) · [智谱 AI](https://www.zhipuai.cn/) · [通义千问](https://tongyi.aliyun.com/) · [文心一言](https://yiyan.baidu.com/)
- [豆包](https://www.doubao.com/) · [硅基流动](https://cloud.siliconflow.cn/) · [书生·浦语](https://chat.intern-ai.org.cn/) · [小米 MiMo](https://api.xiaomimimo.com/)
- [讯飞星火](https://xinghuo.xfyun.cn/) · [tokenDance](https://tokendance.space/) · [MarkItDown](https://github.com/microsoft/markitdown)

---

**作者**：Evan
**最后更新**：2026-06-17
