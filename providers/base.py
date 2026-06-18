"""
基础适配器 - 所有服务商适配器的公共基类
提取通用逻辑（System Prompt 优先级、配置读取），消除子类重复代码
"""

from abc import ABC, abstractmethod
from .registry import SYSTEM_PROMPT


class BaseAdapter(ABC):
    """所有适配器的基类"""

    def __init__(self, provider_key, config):
        self.provider_key = provider_key
        from .registry import PROVIDERS
        self.meta = PROVIDERS[provider_key]
        self.config = config

    def _get_provider_config(self):
        """获取当前服务商的配置（config 结构为 {providers: {key: {...}}, settings: {...}}）"""
        return self.config.get("providers", {}).get(self.provider_key, {})

    def _build_final_messages(self, messages, **kwargs):
        """
        统一处理三层 System Prompt 优先级，消除子类重复代码。

        优先级：第2层模板 > 第1层用户自定义 > 第1层硬编码默认
        """
        system_prompt = kwargs.get("system_prompt")
        if system_prompt:
            # 第2层：有模板 → 模板优先
            return [{"role": "system", "content": system_prompt}] + messages

        # 第1层：检查用户自定义全局人设
        custom_prompt = self.config.get("settings", {}).get("system_prompt", "").strip()
        if custom_prompt:
            return [{"role": "system", "content": custom_prompt}] + messages

        # 第1层兜底：硬编码默认
        return [SYSTEM_PROMPT] + messages

    def _get_instructions(self, **kwargs):
        """
        获取指令文本（用于 Weelinking responses API 等非 messages 格式）。
        返回字符串。
        """
        system_prompt = kwargs.get("system_prompt")
        if system_prompt:
            return system_prompt

        custom_prompt = self.config.get("settings", {}).get("system_prompt", "").strip()
        if custom_prompt:
            return custom_prompt

        return SYSTEM_PROMPT["content"]

    @abstractmethod
    def stream_chat(self, model, messages, **kwargs):
        """流式对话，返回生成器"""
        pass

    def upload_file(self, file_obj, filename):
        """上传文件，返回 file_id。默认抛出 NotImplementedError。"""
        raise NotImplementedError(f"{self.meta['name']} 暂不支持文件上传")
