"""
providers 包 — 多模型 API 适配器
对外暴露：PROVIDERS、get_adapter、各适配器类
"""

from .registry import PROVIDERS, SYSTEM_PROMPT
from .base import BaseAdapter
from .openai_compat import OpenAICompatibleAdapter
from .weelinking import WeelinkingAdapter

# 修改 get_adapter()
def get_adapter(provider_key, config):
    if provider_key not in PROVIDERS:
        raise ValueError(f"未知的服务商: {provider_key}")
    if provider_key == "weelinking":
        return WeelinkingAdapter(provider_key, config)
    else:
        return OpenAICompatibleAdapter(provider_key, config)  # 所有其他都走通用适配器

