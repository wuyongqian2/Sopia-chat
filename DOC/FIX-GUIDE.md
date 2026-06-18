# Sophia Chat 修改指南

**基于审查报告 REVIEW-REPORT.md，针对 P0 x 3 + P1 x 10 的具体修复方案**
**编写日期**：2026-06-08
**预期工期**：P0 约 1 天，P1 约 3-4 天

---

# P0-1：CSRF 保护

**问题**：Flask-Login session cookie 无 CSRF token，恶意网站可伪造请求。

**方案**：lask-wtf CSRFProtect + 前端 fetch 拦截器自动注入 header。

## 后端改动

requirements.txt 新增：
`
flask-wtf>=1.2.0
`

app.py 新增：
```python
from flask_wtf.csrf import CSRFProtect, generate_csrf
csrf = CSRFProtect(app)

@app.after_request
def inject_csrf_token(response):
    token = generate_csrf()
    response.set_cookie('csrf_token', token, httponly=False, samesite='Lax')
    return response

csrf.exempt(stop_chat)  # SSE 端点豁免
```

## 前端改动

static/js/utils.js 新增 CSRF 封装：
```javascript
function getCsrfToken() {
    const m = document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
}

async function fetchWithCsrf(url, opts = {}) {
    const method = (opts.method || 'GET').toUpperCase();
    if (['POST','PUT','DELETE','PATCH'].includes(method)) {
        opts.headers = opts.headers || {};
        opts.headers['X-CSRFToken'] = getCsrfToken();
    }
    return fetch(url, opts);
}
window.fetchWithCsrf = fetchWithCsrf;
```

所有 JS 文件中的 etch('/api/... 替换为 etchWithCsrf('/api/...。

---

# P0-2：API Key 加密存储

**问题**：API Key 明文 JSON 存储在 ~/.workbuddy/llm-chat-config.json。

**方案**：Fernet 对称加密，密钥从 Flask secret_key 派生，零停机迁移。

## 新增 crypto_utils.py
```python
import base64, hashlib, os
from cryptography.fernet import Fernet

_SALT = b"llm-chat-config-salt-v1"
_fernet = None

def _derive_key(secret_key):
    dk = hashlib.pbkdf2_hmac('sha256', secret_key.encode(), _SALT, 100000)
    return base64.urlsafe_b64encode(dk)

def get_fernet(secret_key):
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_derive_key(secret_key))
    return _fernet

def encrypt_value(plaintext, secret_key):
    if not plaintext: return ""
    return get_fernet(secret_key).encrypt(plaintext.encode()).decode('ascii')

def decrypt_value(ciphertext, secret_key):
    if not ciphertext: return ""
    try:
        return get_fernet(secret_key).decrypt(ciphertext.encode('ascii')).decode()
    except Exception:
        return ciphertext  # 旧明文兼容

def is_encrypted(value):
    return bool(value) and value.startswith("gAAAA")
```

## 修改 config_manager.py

新增加解密函数，load_config 自动解密，save_config 自动加密：
```python
_app_secret_key = None
_SENSITIVE_FIELDS = {"api_key", "access_key", "secret_key", "token"}

def set_app_secret_key(key):
    global _app_secret_key
    _app_secret_key = key

def _encrypt_config(config):
    if not _app_secret_key: return config
    from crypto_utils import encrypt_value, is_encrypted
    import copy
    config = copy.deepcopy(config)
    for pk, pc in config.get("providers", {}).items():
        for f, v in pc.items():
            if f in _SENSITIVE_FIELDS and v and not is_encrypted(v):
                pc[f] = encrypt_value(v, _app_secret_key)
    return config

def _decrypt_config(config):
    if not _app_secret_key: return config
    from crypto_utils import decrypt_value
    for pk, pc in config.get("providers", {}).items():
        for f, v in pc.items():
            if f in _SENSITIVE_FIELDS and v:
                pc[f] = decrypt_value(v, _app_secret_key)
    return config
```

save_config 中调用 _encrypt_config 后再写文件，load_config 读取后调用 _decrypt_config。

app.py 中初始化：set_app_secret_key(app.secret_key)

requirements.txt 新增：cryptography>=41.0.0

迁移兼容：旧明文 -> decrypt_value 无法解密 -> 原样返回 -> 功能正常。下次保存时自动加密。

---

# P0-3：SQLite 并发写入瓶颈

**问题**：每次操作新建/关闭连接，8 线程下写-写竞争。

**方案**：线程级连接复用 + 写操作自动重试。

## 修改 database.py
```python
import threading, time
from contextlib import contextmanager

_local = threading.local()

def get_db():
    conn = getattr(_local, 'conn', None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn

@contextmanager
def db_transaction():
    conn = get_db()
    for attempt in range(3):
        try:
            yield conn
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < 2:
                conn.rollback()
                time.sleep(0.1 * (attempt + 1))
                continue
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
```

所有写操作改用 with db_transaction() as conn: 包裹，不再手动 commit/close。读操作直接 get_db() 即可。

---

# P1-1：接口限流

新增 lask-limiter>=3.5.0，app.py 初始化：
```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
limiter = Limiter(app=app, key_func=get_remote_address,
                  default_limits=["200/min"], storage_uri="memory://")
```

关键接口装饰器：
- /api/chat -> @limiter.limit("30/minute")
- /api/upload -> @limiter.limit("20/minute")
- /login -> @limiter.limit("10/minute")

---

# P1-2：文件上传 Magic Bytes 校验

新增 python-magic-bin>=0.4.14（Windows 兼容），file_extractor.py 新增：
```python
import magic
_MIME_WHITELIST = {
    '.pdf': ['application/pdf'],
    '.docx': ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
    '.xlsx': ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'],
    '.pptx': ['application/vnd.openxmlformats-officedocument.presentationml.presentation'],
    '.jpg': ['image/jpeg'], '.png': ['image/png'],
    '.txt': ['text/plain'], '.csv': ['text/csv','text/plain'],
    # ... 其他格式
}

def validate_file_content(file_bytes, filename):
    ext = os.path.splitext(filename)[1].lower()
    allowed = _MIME_WHITELIST.get(ext, [])
    if not allowed: return False, f"不支持的格式: {ext}"
    try:
        detected = magic.from_buffer(file_bytes, mime=True)
    except Exception:
        return True, ""
    if detected not in allowed:
        text_types = {'text/plain','text/csv','text/markdown','application/json'}
        if set(allowed) & text_types: return True, ""  # 文本类宽松
        return False, f"文件内容与扩展名不匹配（检测到 {detected}）"
    return True, ""
```

在 extract_and_cache_chunks 中读取 file_bytes 后调用 validate_file_content。

---

# P1-3：配置重复加载

conversationManager.js 的 loadProviders() 中，检查 STATE.config 是否已有数据：
```javascript
async function loadProviders() {
    try {
        const resp = await fetchWithTimeout('/api/providers');
        STATE.providers = await resp.json();
        if (!STATE.config || !STATE.config.providers) {
            const cfgResp = await fetchWithTimeout('/api/config');
            STATE.config = await cfgResp.json();
        }
        renderProviderSelect();
        updateInputState();
    } catch (e) { /* ... */ }
}
```

init() 中保持 loadConfig() 在 loadProviders() 之前调用。

---

# P1-4：标题生成阻塞

app.py generate_title() 添加外层异常兜底，LLM 超时时返回截断的用户消息：
```python
try:
    for chunk in adapter.stream_chat(...):
        if chunk.get("content"): title_text += chunk["content"]
        if chunk.get("error"): break
except Exception:
    pass

title_text = title_text.strip().strip('"').strip()
if not title_text:
    title_text = user_message[:20] + ("..." if len(user_message) > 20 else "")
return jsonify({"title": title_text[:20]})
```

---

# P1-5：L2 语义缓存 O(n) 优化

cache_manager.py SemanticCache.get() 用 numpy 向量化替代 for 循环：
```python
def get(self, query_vector, model, provider):
    import numpy as np
    with self._lock:
        now = time.monotonic()
        valid_keys, vectors = [], []
        for key, entry in self._cache.items():
            if now > entry["expire_at"]: continue
            if entry.get("model") != model or entry.get("provider") != provider: continue
            valid_keys.append(key)
            vectors.append(entry["vector"])
        if not vectors: return None, 0

        q = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0: return None, 0

        matrix = np.array(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1)
        norms = np.where(norms == 0, 1, norms)
        sims = (matrix @ q) / (norms * q_norm)

        best_idx = int(np.argmax(sims))
        if float(sims[best_idx]) >= self._threshold:
            key = valid_keys[best_idx]
            self._cache.move_to_end(key)
            return self._cache[key]["response"], float(sims[best_idx])
        return None, float(sims[best_idx])
```

2000 条目性能：Python for 约 50ms -> numpy 约 0.5ms。

---

# P1-6：Embedding 冷启动静默降级

cache_manager.py encode() 在模型加载中时等待而非直接返回空：
```python
def encode(self, text, timeout=5.0):
    if not text: return []
    self._ensure_loading()
    if self._loaded and self._model:
        try: return self._model.encode(text[:2000], convert_to_tensor=False).tolist()
        except: return []
    if self._loading:
        self._ready.wait(timeout=timeout)
        if self._loaded and self._model:
            try: return self._model.encode(text[:2000], convert_to_tensor=False).tolist()
            except: return []
    return []
```

---

# P1-7：全局共享状态无锁

app.py 用 threading.Event 替代 dict 中的布尔标志：
```python
import threading
_active_streams = {}
_streams_lock = threading.Lock()

def _register_stream(key):
    with _streams_lock:
        _active_streams[key] = threading.Event()
    return _active_streams[key]

def _is_stopped(key):
    with _streams_lock:
        e = _active_streams.get(key)
        return e.is_set() if e else False

def _unregister_stream(key):
    with _streams_lock:
        _active_streams.pop(key, None)

# stop_chat 中：
event = _active_streams.get(stream_key)
if event: event.set(); return jsonify({"success": True})
```

---

# P1-8：向量检索全量加载内存

database.py search_chunks_by_embedding() 用 numpy 批量计算：
```python
def search_chunks_by_embedding(query_vector, document_ids=None, top_k=5):
    import numpy as np, json
    if not query_vector: return []
    q = np.array(query_vector, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0: return []

    # ... SQL 查询同原逻辑，返回 rows ...
    ids_meta, vectors = [], []
    for r in rows:
        v = np.frombuffer(r["embedding"], dtype=np.float32)
        if np.linalg.norm(v) == 0: continue
        ids_meta.append(r); vectors.append(v)
    if not vectors: return []

    matrix = np.stack(vectors)
    norms = np.linalg.norm(matrix, axis=1)
    norms = np.where(norms == 0, 1, norms)
    sims = (matrix @ q) / (norms * q_norm)
    top_idx = np.argsort(sims)[::-1][:top_k]

    results = []
    for i in top_idx:
        r = ids_meta[i]
        results.append({
            "id": r["id"], "document_id": r["document_id"],
            "chunk_index": r["chunk_index"], "text": r["text"],
            "heading": r["heading"],
            "hierarchy": json.loads(r["hierarchy_json"]) if r["hierarchy_json"] else [],
            "score": float(sims[i])
        })
    return results
```

---

# P1-9：文件大小限制统一

三处限制统一到 config_manager 的 settings.max_file_size_mb（默认 50）：

- config_manager.py：settings 默认值新增 max_file_size_mb: 50
- file_extractor.py：MAX_FILE_SIZE 改为从配置读取
- app.py：MAX_CONTENT_LENGTH 从配置读取
- index.html：上传提示改为"最大 50MB"

---

# 修复汇总

| 阶段 | 编号 | 改动 | 工期 |
|------|------|------|------|
| P0 安全 | P0-1 CSRF | app.py + utils.js + 所有 fetch | 3h |
| P0 安全 | P0-2 加密 | crypto_utils.py + config_manager.py | 3h |
| P0 性能 | P0-3 SQLite | database.py 连接复用 | 2h |
| P1 安全 | P1-1 限流 | flask-limiter | 1h |
| P1 安全 | P1-2 Magic | file_extractor.py | 1h |
| P1 交互 | P1-3 配置去重 | conversationManager.js | 0.5h |
| P1 交互 | P1-4 标题阻塞 | app.py 兜底 | 0.5h |
| P1 性能 | P1-5 L2 缓存 | cache_manager.py numpy | 1h |
| P1 正确性 | P1-6 冷启动 | cache_manager.py 等待 | 1h |
| P1 并发 | P1-7 状态锁 | app.py Event | 1h |
| P1 性能 | P1-8 向量检索 | database.py numpy | 1.5h |
| P1 一致性 | P1-9 文件限制 | 三处统一 | 1h |

**总计：P0 约 8h，P1 约 8.5h，合计约 2 个工作日。**

# 新增依赖

`
flask-wtf>=1.2.0
flask-limiter>=3.5.0
cryptography>=41.0.0
python-magic-bin>=0.4.14
`

# 涉及文件

| 文件 | P0 | P1 | 类型 |
|------|----|----|------|
| app.py | CSRF/加密/锁 | 限流/标题 | 修改 |
| config_manager.py | 加解密 | 文件大小 | 修改 |
| database.py | 连接复用 | 向量优化 | 修改 |
| cache_manager.py | - | L2/冷启动 | 修改 |
| file_extractor.py | - | Magic/大小 | 修改 |
| crypto_utils.py | 新增 | - | 新增 |
| utils.js | CSRF封装 | - | 修改 |
| conversationManager.js | fetch替换 | 配置去重 | 修改 |
| messageRenderer.js | fetch替换 | - | 修改 |
| uiManager.js | fetch替换 | - | 修改 |
| index.html | - | 提示文案 | 修改 |
| requirements.txt | 新增依赖 | 新增依赖 | 修改 |

共 12 个文件，1 新增 + 11 修改。
