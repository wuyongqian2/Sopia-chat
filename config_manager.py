"""
配置管理器 - 读写 API Key 等配置
配置文件位置: ~/.workbuddy/llm-chat-config.json
敏感字段使用 Fernet 对称加密存储（api_key, secret_key, access_key）
"""

import json
import logging
import os
import threading

from cryptography.fernet import Fernet, InvalidToken

from providers import PROVIDERS

logger = logging.getLogger(__name__)

# ============================================================
# 统一文件上传大小限制（单一配置来源）
# ============================================================
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy")
CONFIG_FILE = os.path.join(CONFIG_DIR, "llm-chat-config.json")
CRYPTO_KEY_FILE = os.path.join(CONFIG_DIR, ".crypto_key")

_lock = threading.RLock()  # RLock 支持同一线程重入，避免 load_config -> save_config 死锁

# 需要加密存储的敏感字段
_ENCRYPTED_FIELDS = {"api_key", "secret_key", "access_key"}
# 加密值前缀，用于区分明文/密文（兼容旧配置平滑迁移）
_ENCRYPT_PREFIX = "enc:"

# 缓存 cipher 实例，避免重复创建
_cipher = None


def _ensure_dir():
    """确保配置目录存在"""
    os.makedirs(CONFIG_DIR, exist_ok=True)


def _get_cipher():
    """懒加载 Fernet cipher，使用 PBKDF2 从密钥文件派生加密密钥"""
    global _cipher
    if _cipher is not None:
        return _cipher

    _ensure_dir()

    if not os.path.exists(CRYPTO_KEY_FILE):
        # 首次运行：生成随机盐 + Fernet 密钥
        fernet_key = Fernet.generate_key()
        with open(CRYPTO_KEY_FILE, "wb") as f:
            f.write(fernet_key)
        try:
            os.chmod(CRYPTO_KEY_FILE, 0o600)  # 仅当前用户可读写
        except OSError:
            pass
        _cipher = Fernet(fernet_key)
    else:
        try:
            os.chmod(CRYPTO_KEY_FILE, 0o600)  # 确保权限安全
        except OSError:
            pass
        with open(CRYPTO_KEY_FILE, "rb") as f:
            fernet_key = f.read()
        _cipher = Fernet(fernet_key)

    return _cipher


def _encrypt_value(value):
    """加密单个敏感值，返回 enc: 前缀的密文"""
    if not value:
        return value
    if value.startswith(_ENCRYPT_PREFIX):
        return value  # 已经加密
    cipher = _get_cipher()
    return _ENCRYPT_PREFIX + cipher.encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_value(value):
    """解密单个值，兼容未加密旧数据"""
    if not value:
        return value
    if not value.startswith(_ENCRYPT_PREFIX):
        # 旧版本明文数据，返回原值（下次保存时会自动加密）
        return value
    cipher = _get_cipher()
    try:
        return cipher.decrypt(value[len(_ENCRYPT_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.warning("API Key 解密失败，可能密钥已变更，返回原值")
        return value


def _encrypt_providers(providers_config):
    """加密所有服务商的敏感字段（修改传入的 dict）"""
    for key, provider_config in providers_config.items():
        for field in _ENCRYPTED_FIELDS:
            if provider_config.get(field):
                provider_config[field] = _encrypt_value(provider_config[field])


def _decrypt_providers(providers_config):
    """解密所有服务商的敏感字段（修改传入的 dict）"""
    for key, provider_config in providers_config.items():
        for field in _ENCRYPTED_FIELDS:
            if provider_config.get(field):
                provider_config[field] = _decrypt_value(provider_config[field])


def _get_default_config():
    """返回默认配置"""
    config = {"providers": {}, "settings": {"theme": "dark", "skin": "classic", "system_prompt": ""}}
    for key, meta in PROVIDERS.items():
        config["providers"][key] = {}
        for field in meta["auth_fields"]:
            config["providers"][key][field] = ""
    return config


def load_config():
    """加载配置文件，不存在则创建默认。敏感字段自动解密。"""
    with _lock:
        _ensure_dir()
        if not os.path.exists(CONFIG_FILE):
            config = _get_default_config()
            save_config(config)
            return config
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            # 解密所有敏感字段（兼容旧明文数据）
            _decrypt_providers(config.get("providers", {}))
            # 合并新添加的服务商配置
            default_cfg = _get_default_config()
            for key in default_cfg.get("providers", {}):
                if key not in config.get("providers", {}):
                    config["providers"][key] = default_cfg["providers"][key]
            if "settings" not in config:
                config["settings"] = default_cfg["settings"]
            else:
                for k, v in default_cfg["settings"].items():
                    if k not in config["settings"]:
                        config["settings"][k] = v
            return config
        except (json.JSONDecodeError, IOError):
            config = _get_default_config()
            save_config(config)
            return config


def save_config(config):
    """保存配置到文件。敏感字段加密后写入磁盘。"""
    with _lock:
        _ensure_dir()
        # 深拷贝 providers 部分再加密，避免修改传入的 config 对象
        providers_section = config.get("providers", {})
        to_save = {**config, "providers": {}}
        for k, v in providers_section.items():
            to_save["providers"][k] = dict(v)
        _encrypt_providers(to_save["providers"])
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)


def get_provider_config(provider_key):
    """获取指定服务商的配置（已解密）"""
    config = load_config()
    return config.get("providers", {}).get(provider_key, {})


def update_provider_config(provider_key, auth_data):
    """更新指定服务商的认证信息"""
    config = load_config()
    if provider_key not in config.get("providers", {}):
        config["providers"][provider_key] = {}
    config["providers"][provider_key].update(auth_data)
    save_config(config)
    return config


def get_settings():
    """获取全局设置"""
    config = load_config()
    return config.get("settings", {"theme": "dark"})


def update_settings(settings_data):
    """更新全局设置"""
    config = load_config()
    config["settings"] = {**config.get("settings", {}), **settings_data}
    save_config(config)
    return config
