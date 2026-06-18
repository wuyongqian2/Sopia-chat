"""
认证蓝图 — 登录 / 注册 / 登出
使用 Flask-Login 管理会话，CSRF 保护，登录防暴力破解
"""

import time
import threading
from collections import defaultdict
from flask import Blueprint, request, jsonify, redirect, url_for, render_template_string
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import generate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_user_by_username, get_user_by_id, create_user

# ============================================================
# 登录防暴力破解
# ============================================================
# 失败计数: {ip_or_username: [attempt_timestamps]}
_failed_attempts = defaultdict(list)
_failed_lock = threading.Lock()
MAX_FAILED_ATTEMPTS = 5       # 最大连续失败次数
FAILED_TIMEOUT = 900           # 失败记录有效期 15 分钟
LOCKOUT_DURATION = 300         # 超过阈值后锁定 5 分钟


def _check_brute_force(identifier):
    """检查是否被锁定。返回 (is_locked, wait_seconds)"""
    now = time.time()
    with _failed_lock:
        attempts = [t for t in _failed_attempts[identifier] if now - t < FAILED_TIMEOUT]
        _failed_attempts[identifier] = attempts
        if len(attempts) >= MAX_FAILED_ATTEMPTS:
            latest = max(attempts)
            wait = int(LOCKOUT_DURATION - (now - latest))
            if wait > 0:
                return True, wait
            # 锁定时间已过，清除记录
            _failed_attempts[identifier] = []
    return False, 0


def _record_failed_attempt(identifier):
    """记录一次失败尝试"""
    with _failed_lock:
        _failed_attempts[identifier].append(time.time())


def _clear_failed_attempts(identifier):
    """登录成功后清除失败记录"""
    with _failed_lock:
        _failed_attempts.pop(identifier, None)


# ============================================================
# User 类（Flask-Login 需要）
# ============================================================

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

    @staticmethod
    def from_db_row(row):
        """从数据库行创建 User 对象"""
        if row is None:
            return None
        return User(id=row["id"], username=row["username"])


# ============================================================
# Flask-Login 初始化
# ============================================================

login_manager = LoginManager()


def init_auth(app):
    """初始化认证系统"""
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "请先登录"

    @login_manager.user_loader
    def load_user(user_id):
        user = get_user_by_id(int(user_id))
        return User.from_db_row(user)

    @login_manager.unauthorized_handler
    def unauthorized():
        # API 请求返回 401 JSON
        if request.path.startswith("/api/"):
            return jsonify({"error": "未登录", "code": 401}), 401
        # 页面请求重定向到登录页
        return redirect(url_for("auth.login"))


# ============================================================
# 认证蓝图
# ============================================================

auth_bp = Blueprint("auth", __name__)

# 登录页面 HTML
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录 - Sophia Chat</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f1a;
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .auth-container {
            background: #1a1a2e;
            border-radius: 16px;
            padding: 40px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        }
        .auth-title {
            text-align: center;
            margin-bottom: 32px;
        }
        .auth-title h1 {
            font-size: 24px;
            background: linear-gradient(135deg, #6366f1, #8b5cf6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }
        .auth-title p {
            color: #888;
            font-size: 14px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-size: 14px;
            color: #aaa;
        }
        .form-group input {
            width: 100%;
            padding: 12px 16px;
            background: #16162a;
            border: 1px solid #333;
            border-radius: 8px;
            color: #e0e0e0;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }
        .form-group input:focus {
            border-color: #6366f1;
        }
        .btn-submit {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #6366f1, #8b5cf6);
            border: none;
            border-radius: 8px;
            color: #fff;
            font-size: 16px;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .btn-submit:hover {
            opacity: 0.9;
        }
        .auth-link {
            text-align: center;
            margin-top: 20px;
            font-size: 14px;
        }
        .auth-link a {
            color: #6366f1;
            text-decoration: none;
        }
        .auth-link a:hover {
            text-decoration: underline;
        }
        .error-msg {
            background: #ff444420;
            border: 1px solid #ff444440;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 20px;
            color: #ff6b6b;
            font-size: 14px;
            text-align: center;
        }
        .success-msg {
            background: #44ff4420;
            border: 1px solid #44ff4440;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 20px;
            color: #6bff6b;
            font-size: 14px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="auth-container">
        <div class="auth-title">
            <h1>{{ title }}</h1>
            <p>{{ subtitle }}</p>
        </div>

        {% if error %}
        <div class="error-msg">{{ error }}</div>
        {% endif %}

        {% if success %}
        <div class="success-msg">{{ success }}</div>
        {% endif %}

        <form method="POST">
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <div class="form-group">
                <label>用户名</label>
                <input type="text" name="username" placeholder="请输入用户名" required autofocus
                       value="{{ username or '' }}">
            </div>
            <div class="form-group">
                <label>密码</label>
                <input type="password" name="password" placeholder="请输入密码" required>
            </div>
            {% if is_register %}
            <div class="form-group">
                <label>确认密码</label>
                <input type="password" name="password2" placeholder="请再次输入密码" required>
            </div>
            {% endif %}
            <button type="submit" class="btn-submit">{{ btn_text }}</button>
        </form>

        <div class="auth-link">
            {{ link_text | safe }}
        </div>
    </div>
</body>
</html>
"""


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """登录（含 CSRF 保护和防暴力破解）"""
    if current_user.is_authenticated:
        return redirect("/")

    csrf_token = generate_csrf()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return render_template_string(LOGIN_HTML,
                title="登录", subtitle="Sophia Chat 多模型AI助手",
                btn_text="登录", is_register=False,
                error="用户名和密码不能为空",
                csrf_token=csrf_token,
                link_text='没有账号？<a href="/register">立即注册</a>')

        # 检查是否被锁定（基于 IP + 用户名）
        client_ip = request.remote_addr or "unknown"
        lock_identifiers = [client_ip, f"user:{username}"]
        for ident in lock_identifiers:
            is_locked, wait = _check_brute_force(ident)
            if is_locked:
                return render_template_string(LOGIN_HTML,
                    title="登录", subtitle="Sophia Chat 多模型AI助手",
                    btn_text="登录", is_register=False,
                    error=f"登录尝试次数过多，请 {wait} 秒后重试",
                    csrf_token=csrf_token,
                    username=username,
                    link_text='没有账号？<a href="/register">立即注册</a>')

        user = get_user_by_username(username)
        if user and check_password_hash(user["password_hash"], password):
            _clear_failed_attempts(client_ip)
            _clear_failed_attempts(f"user:{username}")
            login_user(User.from_db_row(user))
            return redirect("/")
        else:
            _record_failed_attempt(client_ip)
            _record_failed_attempt(f"user:{username}")
            return render_template_string(LOGIN_HTML,
                title="登录", subtitle="Sophia Chat 多模型AI助手",
                btn_text="登录", is_register=False,
                error="用户名或密码错误",
                csrf_token=csrf_token,
                username=username,
                link_text='没有账号？<a href="/register">立即注册</a>')

    return render_template_string(LOGIN_HTML,
        title="登录", subtitle="Sophia Chat 多模型AI助手",
        btn_text="登录", is_register=False,
        csrf_token=csrf_token,
        link_text='没有账号？<a href="/register">立即注册</a>')


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """注册（含 CSRF 保护）"""
    if current_user.is_authenticated:
        return redirect("/")

    csrf_token = generate_csrf()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        # 验证
        if not username or not password:
            return render_template_string(LOGIN_HTML,
                title="注册", subtitle="创建新账号",
                btn_text="注册", is_register=True,
                error="用户名和密码不能为空",
                csrf_token=csrf_token,
                link_text='已有账号？<a href="/login">立即登录</a>')

        if len(username) < 3 or len(username) > 50:
            return render_template_string(LOGIN_HTML,
                title="注册", subtitle="创建新账号",
                btn_text="注册", is_register=True,
                error="用户名长度需在 3-50 之间",
                csrf_token=csrf_token,
                link_text='已有账号？<a href="/login">立即登录</a>')

        if len(password) < 6:
            return render_template_string(LOGIN_HTML,
                title="注册", subtitle="创建新账号",
                btn_text="注册", is_register=True,
                error="密码长度不能少于 6 位",
                csrf_token=csrf_token,
                username=username,
                link_text='已有账号？<a href="/login">立即登录</a>')

        if password != password2:
            return render_template_string(LOGIN_HTML,
                title="注册", subtitle="创建新账号",
                btn_text="注册", is_register=True,
                error="两次输入的密码不一致",
                csrf_token=csrf_token,
                username=username,
                link_text='已有账号？<a href="/login">立即登录</a>')

        # 创建用户
        password_hash = generate_password_hash(password)
        user_id = create_user(username, password_hash)

        if user_id is None:
            return render_template_string(LOGIN_HTML,
                title="注册", subtitle="创建新账号",
                btn_text="注册", is_register=True,
                error="用户名已被占用",
                csrf_token=csrf_token,
                link_text='已有账号？<a href="/login">立即登录</a>')

        # 注册成功，自动登录
        login_user(User(id=user_id, username=username))
        return redirect("/")

    return render_template_string(LOGIN_HTML,
        title="注册", subtitle="创建新账号",
        btn_text="注册", is_register=True,
        csrf_token=csrf_token,
        link_text='已有账号？<a href="/login">立即登录</a>')


@auth_bp.route("/logout")
@login_required
def logout():
    """登出"""
    logout_user()
    return redirect("/login")
