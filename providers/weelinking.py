"""
Weelinking 专属适配器 — 自动路由 chat/completions ↔ responses 双端点
路由规则由模型前缀路由表 _CHAT_COMPLETIONS_PREFIXES 决定，替代硬编码 if-else。
"""

import json
import logging
import time
import requests
from .base import BaseAdapter

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
# 路由表：模型名前缀 → chat/completions 端点
# 不在此表中的模型默认走 /v1/responses
# ----------------------------------------------------------------
_CHAT_COMPLETIONS_PREFIXES = (
    "gemini",
    "claude",
)


def _use_chat_completions(model: str) -> bool:
    """根据路由表判断是否走 chat/completions 端点"""
    lower = model.lower()
    return any(lower.startswith(p) for p in _CHAT_COMPLETIONS_PREFIXES)


class WeelinkingAdapter(BaseAdapter):
    """weelinking 专属适配器 — 通过路由表分发 Gemini/Claude → chat/completions，其余 → responses"""

    def stream_chat(self, model, messages, **kwargs):
        api_key = self._get_provider_config().get("api_key", "")
        if not api_key:
            yield {"error": "weelinking API Key 未设置，请在设置中配置"}
            return

        if _use_chat_completions(model):
            yield from self._stream_chat_completions(api_key, model, messages, **kwargs)
        else:
            yield from self._stream_responses(api_key, model, messages, **kwargs)

    # ---- chat/completions 端点（Gemini / Claude 模型） ----

    def _stream_chat_completions(self, api_key, model, messages, **kwargs):
        final_messages = self._build_final_messages(messages, **kwargs)
        endpoint = f"{self.meta['base_url']}/chat/completions"

        payload = {
            "model": model,
            "messages": final_messages,
            "stream": True,
            "temperature": kwargs.get("temperature", 0.3),
            "max_tokens": kwargs.get("max_tokens", 4096)
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        yield from self._do_stream(endpoint, headers, payload, self._parse_chat_chunk)

    # ---- /v1/responses 端点（GPT / DeepSeek 等） ----

    def _stream_responses(self, api_key, model, messages, **kwargs):
        input_items = []
        for msg in messages:
            input_items.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })

        instructions = self._get_instructions(**kwargs)

        payload = {
            "model": model,
            "instructions": instructions,
            "input": input_items,
            "stream": True,
        }
        temperature = kwargs.get("temperature")
        if temperature is not None:
            payload["temperature"] = temperature
        max_tokens = kwargs.get("max_tokens")
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        yield from self._do_stream(
            "https://api.weelinking.com/v1/responses",
            headers, payload, self._parse_response_chunk
        )

    # ---- 通用流式请求 ----

    def _do_stream(self, endpoint, headers, payload, parse_func):
        # 重试机制：处理 Windows socket 级别错误（如 [Errno 22] Invalid argument）
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(
                    endpoint, headers=headers, json=payload,
                    stream=True, timeout=(10, 120)
                )
                resp.raise_for_status()
                resp.encoding = "utf-8"

                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    data_str = line
                    if line.startswith("data: "):
                        data_str = line[6:]
                    data_str = data_str.strip()
                    if data_str in ("[DONE]", ""):
                        continue
                    try:
                        data = json.loads(data_str)
                        result = parse_func(data)
                        if result:
                            yield result
                    except json.JSONDecodeError:
                        continue

                # 成功完成，跳出重试循环
                break

            except requests.exceptions.HTTPError as e:
                error_body = ""
                if hasattr(e, "response") and e.response is not None:
                    try:
                        ej = e.response.json()
                        error_body = ej.get("error", {}).get("message", str(ej.get("error", "")))
                        if not error_body:
                            error_body = e.response.text[:500]
                    except Exception:
                        error_body = e.response.text[:500]
                    logger.warning("weelinking HTTP 错误响应: %s", error_body)
                yield {"error": f"weelinking API 错误: {error_body or str(e)}"}
                return  # HTTP 错误不重试

            except requests.exceptions.RequestException as e:
                # 网络请求错误（连接超时、DNS 解析失败等）
                if attempt < max_retries:
                    logger.warning("weelinking 请求失败 (尝试 %s/%s): %s", attempt + 1, max_retries + 1, e)
                    time.sleep(1 * (attempt + 1))  # 指数退避
                    continue
                yield {"error": f"weelinking 请求失败: {str(e)}"}
                return

            except OSError as e:
                # Windows socket 级别错误（如 [Errno 22] Invalid argument）
                # 在 Windows 上，urllib3 2.x 处理 SSL/TLS 连接时可能抛出此错误
                if attempt < max_retries:
                    logger.warning("weelinking socket 错误 (尝试 %s/%s): %s", attempt + 1, max_retries + 1, e)
                    time.sleep(1 * (attempt + 1))  # 指数退避
                    continue
                # 提供详细的错误诊断信息
                error_msg = str(e)
                if "[Errno 22]" in error_msg:
                    yield {"error": f"网络连接异常: Windows socket 错误 (EINVAL)。请检查: 1) 网络连接是否稳定 2) 是否有代理/VPN 干扰 3) 防火墙设置。原始错误: {error_msg}"}
                else:
                    yield {"error": f"网络连接异常: {error_msg}"}
                return

            except Exception as e:
                # 其他未预期的错误
                if attempt < max_retries:
                    logger.warning("weelinking 未知错误 (尝试 %s/%s): %s", attempt + 1, max_retries + 1, e)
                    time.sleep(1 * (attempt + 1))
                    continue
                yield {"error": f"weelinking 请求失败: {str(e)}"}
                return

    # ---- 响应解析 ----

    @staticmethod
    def _parse_chat_chunk(data):
        """解析 chat/completions SSE chunk"""
        if data.get("code") and data.get("code") != 0:
            return {"error": f"weelinking API 错误: {data.get('message', '未知错误')}"}
        if data.get("choices") and len(data["choices"]) > 0:
            choice = data["choices"][0]
            delta = choice.get("delta", {})
            content = (
                delta.get("content")
                or choice.get("message", {}).get("content")
                or choice.get("text")
                or choice.get("content")
                or ""
            )
            if not content:
                return None
            return {
                "content": content,
                "reasoning_content": delta.get("reasoning_content") or "",
                "finish_reason": choice.get("finish_reason")
            }
        return None

    @staticmethod
    def _parse_response_chunk(data):
        """解析 responses API SSE chunk"""
        if data.get("error"):
            return {"error": f"weelinking API 错误: {data['error']}"}

        event_type = data.get("type", "")

        # 标准 OpenAI Responses 流式格式
        if event_type == "response.output_text.delta":
            content = data.get("delta", "")
            if content:
                return {"content": content, "reasoning_content": "", "finish_reason": None}
            return None

        if event_type == "response.completed":
            return {"content": "", "reasoning_content": "", "finish_reason": "completed"}

        if event_type in ("response.created", "response.in_progress",
                          "response.output_item.added", "response.content_part.added"):
            return None

        # weelinking 简化格式：output 数组
        if "output" in data:
            for item in data["output"]:
                if item.get("type") == "output_text":
                    text = item.get("text", "")
                    if text:
                        return {"content": text, "reasoning_content": "", "finish_reason": None}
                elif "delta" in item:
                    d = item["delta"]
                    if d:
                        return {"content": d, "reasoning_content": "", "finish_reason": None}
            return None

        # 直接 delta 字段
        if "delta" in data:
            d = data["delta"]
            return {"content": d, "reasoning_content": "", "finish_reason": None} if d else None

        return None
