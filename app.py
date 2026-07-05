"""
LLM Chat - 多模型AI聊天应用
Flask 后端主入口
"""

import json
import logging
import os
import sys
import webbrowser
import threading
from flask import Flask, request, Response, send_from_directory, jsonify
from flask_cors import CORS
from flask_login import login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException

# 初始化模块级 logger
logger = logging.getLogger("sophia_chat")
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
os.environ['PYTHONIOENCODING'] = 'utf-8'  # 对子进程生效
# PyInstaller 无控制台模式时 stdout/stderr 为 None，需判空
for stream_name in ('stdout', 'stderr'):
    s = getattr(sys, stream_name, None)
    if s is not None and hasattr(s, 'encoding') and s.encoding != 'utf-8':
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


# ============================================================
# 路径兼容：PyInstaller 打包后 sys._MEIPASS 指向临时解压目录
# ============================================================
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from providers import PROVIDERS, get_adapter
from config_manager import load_config, update_provider_config, update_settings, get_settings, MAX_UPLOAD_SIZE
from templates import (
    get_all_templates, get_template_by_id, create_template,
    update_template, delete_template, render_system_prompt, get_categories
)
from file_extractor import extract_from_file, is_supported, get_supported_extensions, extract_and_cache_chunks, search_cached_chunks, extract_text_only
from cache_manager import get_exact_cache, get_semantic_cache, get_embedding, cache_stats, clear_all_caches, warmup_embedding_model
from database import (
    create_conversation, get_user_conversations, get_conversation,
    update_conversation, delete_conversation, save_message, get_conversation_messages
)
from auth import init_auth, auth_bp

# ============================================================
# Token 估算工具（与前端 estimateTokens 保持一致）
# ============================================================
import re

def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数量（与前端逻辑一致）
    - CJK 字符：~2 tokens/字
    - 英文单词：~1.3 tokens/词
    - 数字：~0.5 tokens/组
    - 其他：~0.5 tokens/字符
    """
    if not text:
        return 0
    cjk = len(re.findall(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', text))
    words = len(re.findall(r'[a-zA-Z]+', text))
    digits = len(re.findall(r'[0-9]+', text))
    other = max(0, len(text) - cjk - len(re.findall(r'[a-zA-Z]', text)) - len(re.findall(r'[0-9]', text)))
    return int(cjk * 2 + words * 1.3 + digits * 0.5 + other * 0.5 + 0.99)  # 向上取整

# 持久化 secret_key，避免每次重启后用户登录态失效
def _get_or_create_secret_key():
    config_dir = os.path.join(os.path.expanduser("~"), ".workbuddy")
    key_file = os.path.join(config_dir, ".secret_key")
    if os.path.exists(key_file):
        try:
            os.chmod(key_file, 0o600)  # 确保仅当前用户可读
        except OSError:
            pass
        with open(key_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    key = os.urandom(24).hex()
    os.makedirs(config_dir, exist_ok=True)
    with open(key_file, "w", encoding="utf-8") as f:
        f.write(key)
    try:
        os.chmod(key_file, 0o600)  # 创建后限制权限
    except OSError:
        pass
    return key

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="")
app.secret_key = _get_or_create_secret_key()  # Flask-Login 需要
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE

# ============================================================
# CSRF 保护（flask-wtf CSRFProtect）
# ============================================================
# CSRFProtect 会为所有 POST/PUT/PATCH/DELETE 请求校验 CSRF token
# - 前端 API: 从 csrf_token cookie 中读取，通过 X-CSRFToken 请求头发送
# - 登录/注册表单: 通过隐藏的 csrf_token 字段提交
csrf = CSRFProtect(app)


@app.after_request
def inject_csrf_cookie(response):
    """每个响应都携带 csrf_token cookie，供前端 JS 读取并注入 X-CSRFToken 请求头"""
    token = generate_csrf()
    response.set_cookie('csrf_token', token, httponly=False, samesite='Lax')
    return response


# ============================================================
# 接口限流（flask-limiter）
# ============================================================
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute", "1000 per hour"],
    storage_uri="memory://",  # 单进程内存存储（Waitress 单服务器适用）
)

CORS(app)
limiter.init_app(app)

# 将统一文件大小暴露为模块属性，供 file_extractor 等模块导入
app.MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE

@app.errorhandler(Exception)
def handle_unhandled_exception(e):
    """全局异常处理器 — 捕获所有未处理的异常"""
    if isinstance(e, HTTPException):
        return e  # 让 Flask 正常处理 404/405 等 HTTP 异常
    logger.exception("未处理的异常")
    return jsonify({"error": "服务器内部错误，请稍后重试"}), 500

# 初始化认证系统
init_auth(app)
app.register_blueprint(auth_bp)

# ============================================================
# 活跃流管理（线程安全，threading.Event 替代裸 dict 布尔标志）
# ============================================================
_active_streams = {}
_streams_lock = threading.Lock()


def _register_stream(key):
    """注册活跃流并返回 Event 对象（线程安全）"""
    with _streams_lock:
        _active_streams[key] = threading.Event()
    return _active_streams[key]


def _is_stopped(key):
    """检查流是否已被标记停止（线程安全）"""
    with _streams_lock:
        e = _active_streams.get(key)
        return e.is_set() if e else False


def _unregister_stream(key):
    """注销活跃流（线程安全）"""
    with _streams_lock:
        _active_streams.pop(key, None)


# ============================================================
# 路由 - 页面
# ============================================================

@app.route("/")
@login_required
def index():
    """返回主聊天页面"""
    return send_from_directory(app.static_folder, "index.html")


# ============================================================
# CSRF Token 端点（前端首次加载时获取）
# ============================================================

@app.route("/api/csrf-token", methods=["GET"])
def csrf_token():
    """返回 CSRF token，前端在登录后可读取 cookie 或调用此端点刷新"""
    token = generate_csrf()
    return jsonify({"csrf_token": token})


# ============================================================
# 路由 - API
# ============================================================

@app.route("/api/providers", methods=["GET"])
@login_required
def get_providers():
    """返回所有可用服务商及模型列表"""
    config = load_config()
    result = []
    for key, meta in PROVIDERS.items():
        provider_info = {
            "key": key,
            "name": meta["name"],
            "models": meta["models"],
            "default_model": meta["default_model"],
            "description": meta["description"],
            "auth_type": meta["auth_type"],
            "auth_fields": meta["auth_fields"],
            "configured": False,
            "supports_native_upload": bool(meta.get("supports_native_upload")),
            "context_window": meta.get("context_window", 32000)
        }
        # 检查是否已配置
        provider_config = config.get("providers", {}).get(key, {})
        if meta["auth_type"] == "bearer":
            provider_info["configured"] = bool(provider_config.get("api_key", ""))
        elif meta["auth_type"] == "hmac":
            provider_info["configured"] = bool(
                provider_config.get("access_key", "") and
                provider_config.get("secret_key", "")
            )
        result.append(provider_info)
    return jsonify(result)


@app.route("/api/config", methods=["GET"])
@login_required
def get_config():
    """获取当前完整配置 (不含敏感信息的完整值，仅返回是否已配置)"""
    config = load_config()
    # 脱敏处理：只返回是否已配置
    safe_config = {"providers": {}, "settings": config.get("settings", {})}
    for key, meta in PROVIDERS.items():
        provider_config = config.get("providers", {}).get(key, {})
        safe_config["providers"][key] = {}
        for field in meta["auth_fields"]:
            val = provider_config.get(field, "")
            safe_config["providers"][key][field] = "***" if val else ""
            safe_config["providers"][key][f"{field}_set"] = bool(val)
    return jsonify(safe_config)


@app.route("/api/config", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def save_config_route():
    """保存配置（带校验）"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "请求体为空"}), 400

        # --- 保存服务商认证 ---
        provider_key = data.get("provider")
        if provider_key:
            # 校验服务商是否存在
            if provider_key not in PROVIDERS:
                return jsonify({"error": f"未知服务商: {provider_key}"}), 400

            auth_data = data.get("auth", {})
            if not isinstance(auth_data, dict):
                return jsonify({"error": "认证数据格式无效，应为 JSON 对象"}), 400

            # 白名单：只允许该服务商定义的认证字段
            allowed_fields = set(PROVIDERS[provider_key]["auth_fields"])
            unknown_fields = set(auth_data.keys()) - allowed_fields
            if unknown_fields:
                return jsonify({"error": f"不允许的字段: {', '.join(unknown_fields)}"}), 400

            # 值类型校验：所有认证字段必须是字符串
            for field, val in auth_data.items():
                if not isinstance(val, str):
                    return jsonify({"error": f"字段 {field} 的值必须是字符串"}), 400

            update_provider_config(provider_key, auth_data)

        # --- 保存全局设置 ---
        settings_data = data.get("settings")
        if settings_data:
            if not isinstance(settings_data, dict):
                return jsonify({"error": "设置数据格式无效，应为 JSON 对象"}), 400

            # 白名单：只允许已知的设置字段
            ALLOWED_SETTINGS = {
                "theme", "skin", "temperature", "max_tokens",
                "context_messages", "system_prompt"
            }
            unknown_settings = set(settings_data.keys()) - ALLOWED_SETTINGS
            if unknown_settings:
                return jsonify({"error": f"不允许的设置项: {', '.join(unknown_settings)}"}), 400

            # 值类型校验
            type_checks = {
                "theme": str,
                "skin": str,
                "temperature": (int, float),
                "max_tokens": int,
                "context_messages": int,
                "system_prompt": str,
            }
            for field, val in settings_data.items():
                expected = type_checks.get(field)
                if expected and not isinstance(val, expected):
                    return jsonify({"error": f"设置 {field} 的类型不正确，期望 {expected}"}), 400

            # 数值范围校验
            if "temperature" in settings_data:
                t = settings_data["temperature"]
                if t < 0 or t > 2:
                    return jsonify({"error": "temperature 应在 0~2 之间"}), 400
            if "max_tokens" in settings_data:
                mt = settings_data["max_tokens"]
                if mt < 1 or mt > 200000:
                    return jsonify({"error": "max_tokens 应在 1~200000 之间"}), 400
            if "context_messages" in settings_data:
                cm = settings_data["context_messages"]
                if cm < 2 or cm > 200:
                    return jsonify({"error": "context_messages 应在 2~200 之间"}), 400

            update_settings(settings_data)

        return jsonify({"success": True})

    except Exception as e:
        logger.error("保存配置失败", exc_info=True)
        return jsonify({"error": "保存配置失败，请稍后重试"}), 500


# ============================================================
# Prompt 模板 API
# ============================================================

@app.route("/api/templates", methods=["GET"])
@login_required
def list_templates():
    """返回所有模板（内置 + 用户自定义）"""
    templates = get_all_templates()
    categories = get_categories()
    return jsonify({"templates": templates, "categories": categories})


@app.route("/api/templates", methods=["POST"])
@login_required
def add_template():
    """创建用户自定义模板"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "请求体为空"}), 400
        if not data.get("name") or not isinstance(data["name"], str):
            return jsonify({"error": "缺少 name（字符串）"}), 400
        if not data.get("system_prompt") or not isinstance(data["system_prompt"], str):
            return jsonify({"error": "缺少 system_prompt（字符串）"}), 400

        template = create_template(
            name=data["name"].strip(),
            system_prompt=data["system_prompt"].strip(),
            category=str(data.get("category", "自定义")).strip()[:20],
            icon=str(data.get("icon", "💡")).strip()[:4],
            description=str(data.get("description", "")).strip()[:200],
            variables=data.get("variables", []) if isinstance(data.get("variables"), list) else []
        )
        return jsonify({"success": True, "template": template})
    except Exception as e:
        logger.error("创建模板失败", exc_info=True)
        return jsonify({"error": "创建模板失败，请稍后重试"}), 500


@app.route("/api/templates/<template_id>", methods=["PUT"])
@login_required
def edit_template(template_id):
    """更新用户自定义模板"""
    try:
        data = request.json
        if not data or not isinstance(data, dict):
            return jsonify({"error": "请求体无效"}), 400

        # 白名单：只允许更新以下字段
        ALLOWED_FIELDS = {"name", "icon", "category", "description", "system_prompt", "variables"}
        unknown = set(data.keys()) - ALLOWED_FIELDS
        if unknown:
            return jsonify({"error": f"不允许的字段: {', '.join(unknown)}"}), 400

        # 过滤并校验
        clean = {}
        for field in ALLOWED_FIELDS:
            if field in data:
                if field == "variables":
                    if not isinstance(data[field], list):
                        return jsonify({"error": "variables 应为数组"}), 400
                    clean[field] = data[field]
                else:
                    if not isinstance(data[field], str):
                        return jsonify({"error": f"{field} 应为字符串"}), 400
                    clean[field] = data[field].strip()

        result = update_template(template_id, **clean)
        if result:
            return jsonify({"success": True, "template": result})
        return jsonify({"error": "模板不存在或为内置模板"}), 404
    except Exception as e:
        logger.error("更新模板失败", exc_info=True)
        return jsonify({"error": "更新模板失败，请稍后重试"}), 500


@app.route("/api/templates/<template_id>", methods=["DELETE"])
@login_required
def remove_template(template_id):
    """删除用户自定义模板"""
    if delete_template(template_id):
        return jsonify({"success": True})
    return jsonify({"error": "模板不存在或为内置模板"}), 404


@app.route("/api/chat", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def chat():
    """发起流式对话（集成分层缓存）"""
    try:
        data = request.json
        if not data:
            raise ValueError("请求体为空")

        provider_key = data.get("provider")
        model = data.get("model")
        messages = data.get("messages", [])
        conv_id = data.get("conversation_id", "default")
        temperature = data.get("temperature", 0.7)
        max_tokens = data.get("max_tokens", 4096)
        system_prompt = data.get("system_prompt", None)
        # 前端可传 disable_cache=true 跳过缓存（如重新生成）
        disable_cache = data.get("disable_cache", False)

        if not provider_key or not model:
            raise ValueError("缺少 provider 或 model 参数")

        # 校验 messages 结构：必须是字典数组
        if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
            raise ValueError("messages 必须是对象数组")

        if provider_key not in PROVIDERS:
            raise ValueError(f"未知服务商: {provider_key}")

        config = load_config()
        adapter = get_adapter(provider_key, config)

        # ---- 后端安全网：检查消息总量，防止超出模型上下文窗口 ----
        context_window = PROVIDERS[provider_key].get("context_window", 32000)
        # 使用精确估算（与前端一致）
        estimated_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages if isinstance(m.get("content"), str))
        if estimated_tokens > context_window:
            # 从最旧的消息开始丢弃，直到估算 token 数在预算内
            budget = int(context_window * 0.85)
            while len(messages) > 1 and estimated_tokens > budget:
                removed = messages.pop(0)
                removed_tokens = estimate_tokens(removed.get("content", "")) if isinstance(removed.get("content"), str) else 0
                estimated_tokens -= removed_tokens
            # 如果单条消息仍然超大，截断它
            if estimated_tokens > budget and messages and isinstance(messages[-1].get("content"), str):
                content = messages[-1]["content"]
                # 按字符截断（假设平均 1.5 tokens/字符用于中文，2 tokens/字符用于英文）
                max_chars = int(budget / 1.5)
                messages[-1]["content"] = content[:max_chars] + "\n\n[上下文过长，已自动截断]"
            logger.warning("消息总量(%d tokens)超出预算(%d)，已自动裁剪", estimated_tokens, budget)

        # 提取用户最后一条消息（用于缓存查询）
        user_question = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # 多模态格式：提取所有 text 片段拼接
                    text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
                    user_question = " ".join(text_parts).strip()
                else:
                    user_question = content.strip()
                break

    except Exception as exc:
        # 同步阶段异常 → 仍然以 SSE 格式返回错误，前端可正常解析
        logger.error("Chat 初始化失败", exc_info=True)
        def error_stream():
            yield f"data: {json.dumps({'error': '请求处理失败，请检查参数后重试'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        return Response(
            error_stream(),
            mimetype="text/event-stream; charset=utf-8",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    # ---- 缓存查询逻辑 ----
    cached_response = None
    cache_source = None  # "l1" | "l2" | None

    try:
        exact_cache = get_exact_cache()
        semantic_cache = get_semantic_cache()

        if not disable_cache and user_question:
            # L1: 精确匹配
            cached_response = exact_cache.get(user_question, model, provider_key)
            if cached_response:
                cache_source = "l1"
                logger.info("Cache L1 命中 | provider=%s model=%s", provider_key, model)

            # L2: 语义缓存（仅 L1 未命中时查询）
            if not cached_response:
                # 使用本地 Embedding 模型（无需 API Key）
                query_vector = get_embedding(user_question)
                if query_vector:
                    cached_response, similarity = semantic_cache.get(query_vector, model, provider_key)
                    if cached_response:
                        cache_source = "l2"
                        logger.info("Cache L2 命中 | similarity=%.3f provider=%s model=%s", similarity, provider_key, model)
    except Exception as cache_exc:
        logger.warning("缓存查询异常，跳过缓存: %s", cache_exc)
        exact_cache = None
        semantic_cache = None
        cached_response = None
        cache_source = None

    # ---- 缓存命中：直接返回 ----
    if cached_response and cache_source:
        def cached_stream():
            try:
                # 模拟 SSE 流式输出（逐块发送，保持前端兼容）
                total = len(cached_response)
                chunk_size = total if total <= 300 else 150
                for i in range(0, total, chunk_size):
                    chunk = {"content": cached_response[i:i+chunk_size]}
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'cache_hit': cache_source}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception:
                yield f"data: {json.dumps({'error': '缓存流输出异常'}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except GeneratorExit:
                pass  # 客户端断开，正常结束

        return Response(
            cached_stream(),
            mimetype="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Cache-Hit": cache_source
            }
        )

    # ---- 缓存未命中：调用 LLM ----
    stream_key = f"{current_user.id}:{conv_id}"

    def generate():
        full_response = ""  # 累积完整响应用于写入缓存
        try:
            for chunk in adapter.stream_chat(
                model, messages,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt
            ):
                if _is_stopped(stream_key):
                    break
                # 累积响应内容
                if chunk.get("content"):
                    full_response += chunk["content"]
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            # 流结束后写入缓存
            if full_response and user_question and not disable_cache:
                # L1 写入
                if exact_cache:
                    exact_cache.put(user_question, model, provider_key, full_response)
                # L2 写入（使用本地 Embedding 模型）
                if semantic_cache:
                    query_vector = get_embedding(user_question)
                    if query_vector:
                        semantic_cache.put(query_vector, user_question, model, provider_key, full_response)
                if exact_cache or semantic_cache:
                    logger.info("Cache 已缓存 | provider=%s model=%s len=%d", provider_key, model, len(full_response))

            yield "data: [DONE]\n\n"

        except Exception:
            logger.exception("LLM 流生成异常")
            yield f"data: {json.dumps({'error': '模型响应异常，请稍后重试'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except GeneratorExit:
            # 客户端断开或流被关闭，正常清理
            pass
        finally:
            _unregister_stream(stream_key)

    _register_stream(stream_key)

    return Response(
        generate(),
        mimetype="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@csrf.exempt
@app.route("/api/chat/stop", methods=["POST"])
@login_required
def stop_chat():
    """中止当前对话生成"""
    data = request.json or {}
    conv_id = data.get("conversation_id", "default")
    stream_key = f"{current_user.id}:{conv_id}"
    event = _active_streams.get(stream_key)
    if event:
        event.set()
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "没有活跃的生成任务"})


# ============================================================
# 缓存管理 API
# ============================================================

@app.route("/api/cache/stats", methods=["GET"])
@login_required
def get_cache_stats():
    """返回缓存统计信息（命中率、条目数等）"""
    return jsonify(cache_stats())


@app.route("/api/cache/clear", methods=["POST"])
@login_required
def clear_cache():
    """清空所有缓存"""
    clear_all_caches()
    return jsonify({"success": True, "message": "缓存已清空"})


# ============================================================
# 会话管理 API
# ============================================================

@app.route("/api/conversations", methods=["GET"])
@login_required
def list_conversations():
    """获取当前用户的会话列表"""
    convs = get_user_conversations(current_user.id)
    return jsonify(convs)


@app.route("/api/conversations", methods=["POST"])
@login_required
def create_conv():
    """创建新会话"""
    data = request.json or {}
    conv_id = create_conversation(
        user_id=current_user.id,
        title=data.get("title", "新对话"),
        provider=data.get("provider"),
        model=data.get("model"),
        system_prompt=data.get("system_prompt")
    )
    return jsonify({"id": conv_id, "success": True})


@app.route("/api/conversations/<conv_id>", methods=["GET"])
@login_required
def get_conv(conv_id):
    """获取会话详情（含消息历史）"""
    conv = get_conversation(conv_id, current_user.id)
    if not conv:
        return jsonify({"error": "会话不存在"}), 404
    messages = get_conversation_messages(conv_id)
    conv["messages"] = messages
    return jsonify(conv)


@app.route("/api/conversations/<conv_id>", methods=["PUT"])
@login_required
def update_conv(conv_id):
    """更新会话（标题、模型等）"""
    if not get_conversation(conv_id, current_user.id):
        return jsonify({"error": "会话不存在"}), 404
    data = request.json
    if not data:
        return jsonify({"error": "请求体为空"}), 400
    update_conversation(conv_id, **data)
    return jsonify({"success": True})


@app.route("/api/conversations/<conv_id>", methods=["DELETE"])
@login_required
def delete_conv(conv_id):
    """删除会话"""
    delete_conversation(conv_id, current_user.id)
    return jsonify({"success": True})


@app.route("/api/conversations/<conv_id>/messages", methods=["POST"])
@login_required
def add_message(conv_id):
    """保存消息到会话"""
    if not get_conversation(conv_id, current_user.id):
        return jsonify({"error": "会话不存在"}), 404
    data = request.json
    if not data or "role" not in data or "content" not in data:
        return jsonify({"error": "缺少 role 或 content"}), 400
    save_message(conv_id, data["role"], data["content"],
                 original_text=data.get("original_text"))
    return jsonify({"success": True})


@app.route("/api/user/info", methods=["GET"])
@login_required
def get_user_info():
    """获取当前用户信息"""
    return jsonify({
        "id": current_user.id,
        "username": current_user.username
    })


@app.route("/api/chat/title", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def generate_title():
    """
    根据用户首条消息生成对话语义标题（非流式，轻量调用）
    请求体: { provider, model, user_message }
    响应体: { title }
    """
    try:
        data = request.json or {}
        provider_key = data.get("provider")
        model = data.get("model")
        user_message = (data.get("user_message") or "").strip()

        if not provider_key or not model or not user_message:
            return jsonify({"error": "缺少必要参数"}), 400

        if provider_key not in PROVIDERS:
            return jsonify({"error": f"未知服务商: {provider_key}"}), 400

        config = load_config()
        adapter = get_adapter(provider_key, config)

        prompt_messages = [
            {
                "role": "user",
                "content": (
                    f"请为以下对话内容生成一个简洁的中文标题，要求：\n"
                    f"1. 不超过15个字\n"
                    f"2. 能准确概括对话主题\n"
                    f"3. 直接输出标题文字，不加引号、序号或任何解释\n\n"
                    f"对话内容：{user_message[:200]}"
                )
            }
        ]

        title_text = ""
        for chunk in adapter.stream_chat(
            model, prompt_messages,
            temperature=0.3,
            max_tokens=30,
            system_prompt="你是一个对话标题生成助手，只输出标题，不做任何解释。"
        ):
            if chunk.get("content"):
                title_text += chunk["content"]
            if chunk.get("error"):
                logger.error("标题生成流错误: %s", chunk["error"])
                return jsonify({"error": "生成标题失败，请稍后重试"}), 500

        # 清理：去除首尾引号/空白，截断到20字保底
        title_text = title_text.strip().strip('"').strip("'").strip("《》【】").strip()
        if not title_text:
            title_text = user_message[:20] + ("..." if len(user_message) > 20 else "")

        return jsonify({"title": title_text[:20]})

    except Exception as e:
        logger.error("生成标题失败", exc_info=True)
        return jsonify({"error": "生成标题失败，请稍后重试"}), 500


# ============================================================
# 聊天附件上传（只解析全文，不分块）

@app.route("/api/chat/upload", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def chat_upload():
    """聊天附件上传 — 只解析全文，不做分块/入库/缓存。知识库路径不受影响。"""
    if 'file' not in request.files:
        return jsonify({"error": "未找到文件"}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "文件名为空"}), 400

    result = extract_text_only(file)
    if result["success"]:
        return jsonify({
            "success": True,
            "filename": result["filename"],
            "extracted_text": result["text"],
            "is_large": False,
            "upload_mode": "local"
        })
    else:
        return jsonify({"error": result["error"]}), 400


# 文件上传 & 解析（MarkItDown 统一处理）
# ============================================================

@app.route("/api/upload", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def upload_file():
    """上传文件并解析为 Markdown 文本。
    mode=local (默认): 本地 MarkItDown + OCR 解析，所有服务商通用。
    mode=native: 调用服务商原生文件上传 API（仅 Kimi 等 supports_native_upload=True 的服务商）。"""
    if 'file' not in request.files:
        return jsonify({"error": "未找到文件"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "文件名为空"}), 400

    overwrite = request.form.get("overwrite", "").lower() == "true"
    mode = request.form.get("mode", "local")
    provider_key = request.form.get("provider", "")

    logger.info("收到文件上传: %s, overwrite=%s, mode=%s, provider=%s", file.filename, overwrite, mode, provider_key)

    # 覆盖模式：先删除旧文档
    if overwrite:
        from database import find_document_by_filename, delete_document
        existing = find_document_by_filename(current_user.id, file.filename)
        if existing:
            logger.info("覆盖旧文档: %s (%s)", existing['id'], existing['filename'])
            delete_document(existing["id"], current_user.id)

    # ---- mode=native：走服务商原生文件上传 API ----
    if mode == "native" and provider_key and PROVIDERS.get(provider_key, {}).get("supports_native_upload"):
        try:
            config = load_config()
            adapter = get_adapter(provider_key, config)

            # 调用适配器的 upload_file()：自动判断 purpose，上传 + 获取提取内容
            result = adapter.upload_file(file, file.filename)

            provider_file_id = result.get("file_id", "")
            is_multimodal = result.get("is_multimodal", False)
            extract_text = result.get("content", "")

            return jsonify({
                "success": True,
                "filename": file.filename,
                "provider_file_id": provider_file_id,
                "extracted_text": extract_text,
                "is_multimodal": is_multimodal,
                "file_size": result.get("bytes", 0),
                "upload_mode": "native",
                "provider": provider_key
            })

        except NotImplementedError:
            return jsonify({"error": f"{PROVIDERS[provider_key]['name']} 暂不支持原生文件上传"}), 400
        except Exception as e:
            logger.exception("Native 上传失败")
            return jsonify({"error": f"原生上传失败: {str(e)}"}), 400

    # ---- mode=local（默认）：本地 MarkItDown + OCR 解析 ----
    persist = request.form.get("persist", "false").lower() == "true"
    if persist:
        result = extract_and_cache_chunks(file, user_id=current_user.id)
    else:
        result = extract_and_cache_chunks(file, user_id=None)

    if result["success"]:
        logger.info("文件解析成功: %s, is_large=%s", result['filename'], result.get('is_large'))
        resp = {
            "success": True,
            "filename": result["filename"],
            "is_large": result.get("is_large", False),
            "preview": result.get("preview", ""),
            "upload_mode": "local",
            "persisted": persist
        }
        # 新版：返回 document_id（优先）
        if result.get("document_id"):
            resp["document_id"] = result["document_id"]
            resp["chunk_count"] = result.get("chunk_count", 0)
        elif result.get("file_id"):
            # 兼容旧版：无 user_id 时走内存缓存
            resp["file_id"] = result["file_id"]
            resp["chunk_count"] = result.get("chunk_count", 0)
        return jsonify(resp)
    else:
        logger.warning("文件解析失败: %s", result['error'])
        resp = {"error": result["error"]}
        if result.get("duplicate"):
            resp["duplicate"] = True
        return jsonify(resp), 400


@app.route("/api/search_chunks", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def search_chunks_route():
    """从已缓存的文件分块中检索与查询相关的内容（支持 document_id(s) 和 file_id）"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "请求体为空"}), 400

        query = data.get("query", "").strip()[:1000]
        file_id = data.get("file_id")
        document_id = data.get("document_id")
        document_ids = data.get("document_ids")  # 数组：批量多文档检索

        if not file_id and not document_id and not document_ids:
            return jsonify({"error": "缺少 file_id、document_id 或 document_ids"}), 400

        # 校验 top_k
        try:
            top_k = max(1, min(int(data.get("top_k", 5)), 50))
        except (TypeError, ValueError):
            top_k = 5

        # 校验 document_ids（限制数量和元素类型）
        valid_doc_ids = None
        if isinstance(document_ids, list):
            valid_doc_ids = [str(d) for d in document_ids if d and isinstance(d, str) and len(d) <= 100][:50]

        context, error = search_cached_chunks(
            file_id=file_id,
            document_id=document_id,
            document_ids=valid_doc_ids,
            query=query,
            user_id=current_user.id,
            top_k=top_k
        )
        if error:
            return jsonify({"error": error}), 400

        return jsonify({"success": True, "context": context})

    except Exception as e:
        logger.error("搜索分块失败", exc_info=True)
        return jsonify({"error": "检索失败，请稍后重试"}), 500


@app.route("/api/documents", methods=["GET"])
@login_required
def list_documents():
    """获取当前用户的知识库文档列表"""
    from database import get_user_documents
    docs = get_user_documents(current_user.id)
    return jsonify(docs)


@app.route("/api/documents/<doc_id>/chunks", methods=["GET"])
@login_required
def get_document_chunks(doc_id):
    """获取文档的所有分块内容（用于预览）"""
    from database import get_document, get_chunks_by_document
    doc = get_document(doc_id, user_id=current_user.id)
    if not doc:
        return jsonify({"error": "文档不存在或无权限"}), 404
    chunks = get_chunks_by_document(doc_id)
    # 预览时不需要 embedding 向量，移除以减少传输量
    for c in chunks:
        c.pop("embedding", None)
    return jsonify({"chunks": chunks, "filename": doc.get("filename", "")})


@app.route("/api/documents/<doc_id>", methods=["PUT"])
@login_required
def update_document(doc_id):
    """更新文档信息（目前支持重命名）"""
    from database import rename_document, get_document
    data = request.json
    if not data or not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    new_filename = data.get("filename")
    if not new_filename or not isinstance(new_filename, str):
        return jsonify({"error": "缺少 filename 字段"}), 400
    # 验证文档存在
    doc = get_document(doc_id, user_id=current_user.id)
    if not doc:
        return jsonify({"error": "文档不存在或无权限"}), 404
    affected = rename_document(doc_id, current_user.id, new_filename)
    if affected == 0:
        return jsonify({"error": "重命名失败"}), 400
    return jsonify({"success": True, "filename": new_filename.strip()[:500]})


@app.route("/api/documents/<doc_id>", methods=["DELETE"])
@login_required
def remove_document(doc_id):
    """删除知识库文档（级联删除分块）"""
    from database import delete_document
    affected = delete_document(doc_id, user_id=current_user.id)
    if affected == 0:
        return jsonify({"success": False, "error": "文档不存在或无权限"}), 404
    return jsonify({"success": True})


@app.route("/api/documents/search", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def search_all_documents():
    """跨文档混合搜索：FAISS 语义检索 + FTS5 全文检索 + RRF 融合"""
    try:
        data = request.json or {}
        query = (data.get("query") or "").strip()[:500]
        if not query:
            return jsonify({"error": "缺少查询内容"}), 400

        # 校验 top_k
        try:
            top_k = max(1, min(int(data.get("top_k", 5)), 50))
        except (TypeError, ValueError):
            top_k = 5

        from database import get_user_documents, search_chunks_hybrid
        from cache_manager import get_embedding

        # 获取用户所有文档ID
        docs = get_user_documents(current_user.id)
        doc_ids = [d["id"] for d in docs]
        if not doc_ids:
            return jsonify({"results": [], "message": "暂无已上传的文档"})

        query_vector = get_embedding(query)

        # 混合检索：同时传入原始文本和向量
        results = search_chunks_hybrid(
            query_text=query,
            query_vector=query_vector,
            document_ids=doc_ids,
            top_k=top_k
        )

        # 补充文件名
        doc_map = {d["id"]: d["filename"] for d in docs}
        for r in results:
            r["filename"] = doc_map.get(r.get("document_id", ""), "未知文件")
            r["score"] = round(r.get("score", 0), 4)

        return jsonify({"results": results})

    except Exception as e:
        logger.error("跨文档搜索失败", exc_info=True)
        return jsonify({"error": "搜索失败，请稍后重试"}), 500


@app.route("/api/settings/theme", methods=["GET"])
@login_required
def get_theme():
    """获取主题设置"""
    settings = get_settings()
    return jsonify({"theme": settings.get("theme", "dark")})


# ============================================================
# 启动
# ============================================================

def open_browser():
    """延迟打开浏览器"""
    import time
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    from waitress import serve

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))

    logger.info("=" * 60)
    logger.info("  Sophia Chat - 多模型AI聊天")
    logger.info("  支持: DeepSeek | Kimi | 智谱GLM | 通义千问 | 文心一言 | 豆包 | NVIDIA | 数眼智能 | 腾讯云 MaaS | 硅基流动 | 书生·浦语 | 小米 MiMo | 星火 Pro | 星火 X2 | 星火 X2 Flash | weelinking")
    logger.info("=" * 60)
    logger.info("  服务器: Waitress (生产模式)")
    logger.info("  浏览器访问: http://%s:%s", host, port)
    logger.info("  API文档:   http://%s:%s/api/providers", host, port)
    logger.info("  按 Ctrl+C 停止服务")

    # 预热本地 Embedding 模型（可选，失败不影响主功能）
    try:
        logger.info("[Cache] 正在预热本地 Embedding 模型...")
        warmup_embedding_model()
    except Exception as e:
        logger.warning("[Cache] Embedding 模型不可用，L2 语义缓存已禁用: %s", e)

    # 加载 FAISS 向量索引（可选，失败不影响主功能）
    try:
        from vector_store import init_vector_store
        logger.info("[VectorStore] 正在加载 FAISS 索引...")
        init_vector_store()
    except Exception as e:
        logger.warning("[VectorStore] FAISS 索引加载失败，使用降级模式: %s", e)

    # MAX_CONTENT_LENGTH 已在模块顶部通过 MAX_UPLOAD_SIZE 统一配置

    # 桌面模式：由 desktop.py 接管，此处不启动服务器
    if "--desktop" not in sys.argv:
        serve(app, host=host, port=port, threads=8, channel_timeout=300)
