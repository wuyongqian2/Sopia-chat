"""
OpenAI 兼容适配器 — 适用于绝大多数服务商（DeepSeek/Kimi/通义/文心/腾讯云/硅基流动等）
"""

import json
import logging
import mimetypes
import time
import requests
from .base import BaseAdapter

logger = logging.getLogger(__name__)


class OpenAICompatibleAdapter(BaseAdapter):
    """通用的 OpenAI API 兼容适配器"""

    def upload_file(self, file_obj, filename, purpose=None):
        """
        上传文件到服务商 API，返回 {"file_id": "...", "status": "...", "content": "..."}。
        仅 supports_native_upload=True 的服务商可用。

        purpose 自动判断：
        - image/* → "image"   （视觉理解/多模态）
        - video/* → "video"   （视频理解）
        - 其他    → "file-extract"（文档提取）
        """
        if not self.meta.get("supports_native_upload"):
            raise NotImplementedError(f"{self.meta['name']} 暂不支持原生文件上传")

        api_key = self._get_provider_config().get("api_key", "")
        if not api_key:
            raise ValueError(f"{self.meta['name']} 的 API Key 未设置")

        # 自动判断 purpose
        if purpose is None:
            mime, _ = mimetypes.guess_type(filename)
            if mime and mime.startswith("image/"):
                purpose = "image"
            elif mime and mime.startswith("video/"):
                purpose = "video"
            else:
                purpose = "file-extract"

        endpoint = f"{self.meta['base_url']}/files"
        headers = {"Authorization": f"Bearer {api_key}"}

        # 步骤1: 上传文件
        file_obj.seek(0)
        try:
            resp = requests.post(
                endpoint,
                headers=headers,
                files={"file": (filename, file_obj.stream, getattr(file_obj, 'mimetype', 'application/octet-stream'))},
                data={"purpose": purpose},
                timeout=(30, 120)
            )
        finally:
            file_obj.seek(0)

        resp.raise_for_status()
        file_data = resp.json()
        file_id = file_data.get("id")
        if not file_id:
            raise ValueError(f"上传成功但未获取到 file_id: {file_data}")

        result = {
            "file_id": file_id,
            "status": file_data.get("status", "ready"),
            "content": "",
            "bytes": file_data.get("bytes", 0),
            "filename": filename,
            "purpose": purpose,
            "is_multimodal": purpose in ("image", "video")
        }

        # 步骤2: 获取文件内容（仅文档类文件）
        # 图片/视频上传后 content 接口返回的是二进制数据，无需提取文本
        if purpose == "file-extract":
            content_endpoint = f"{self.meta['base_url']}/files/{file_id}/content"
            content_resp = requests.get(
                content_endpoint,
                headers=headers,
                timeout=(10, 60)
            )
            content_resp.raise_for_status()
            extracted_text = content_resp.text

            if not extracted_text.strip():
                raise ValueError(f"文件 {filename} 解析结果为空")

            result["content"] = extracted_text

        return result

    def get_file_content(self, file_id):
        """获取已上传文件的文本内容（GET /v1/files/{id}/content）"""
        if not self.meta.get("supports_native_upload"):
            raise NotImplementedError(f"{self.meta['name']} 暂不支持原生文件上传")

        api_key = self._get_provider_config().get("api_key", "")
        if not api_key:
            raise ValueError(f"{self.meta['name']} 的 API Key 未设置")

        endpoint = f"{self.meta['base_url']}/files/{file_id}/content"
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(endpoint, headers=headers, timeout=(10, 60))
        resp.raise_for_status()
        return resp.text

    def stream_chat(self, model, messages, **kwargs):
        api_key = self._get_provider_config().get("api_key", "")
        if not api_key:
            yield {"error": f"{self.meta['name']} 的 API Key 未设置，请在设置中配置"}
            return

        # 三层 System Prompt 机制（已提取到基类）
        final_messages = self._build_final_messages(messages, **kwargs)

        endpoint = f"{self.meta['base_url']}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        payload = {
            "model": model,
            "messages": final_messages,
            "stream": True,
        }

        # 特殊处理：Kimi K2 系列不支持自定义 temperature / max_tokens
        skip_temperature = (self.provider_key == "kimi")
        # 腾讯云 MaaS 的 kimi-k2.5 强制 temperature=1.0（思考模式默认开启）
        force_t1 = (self.provider_key == "tencent" and model == "kimi-k2.5")

        if self.provider_key == "ernie":
            max_tokens = min(kwargs.get("max_tokens", 2048), 2048)
            payload["max_tokens"] = max_tokens
        elif force_t1:
            payload["temperature"] = 1.0
            max_tokens = kwargs.get("max_tokens", 4096)
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
        elif not skip_temperature:
            temperature = kwargs.get("temperature", 0.3)
            max_tokens = kwargs.get("max_tokens", 4096)
            if temperature is not None:
                payload["temperature"] = temperature
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens

        # 支持 extra_body（NVIDIA 等提供商需要透传额外参数）
        extra_body = kwargs.get("extra_body")
        if extra_body and isinstance(extra_body, dict):
            payload.update(extra_body)

        # 重试机制：处理 Windows socket 级别错误（如 [Errno 22] Invalid argument）
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=(10, 120)
                )
                resp.raise_for_status()
                resp.encoding = "utf-8"

                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)

                        # 部分 API 有 code 字段表示错误状态
                        if data.get("code") and data.get("code") != 0:
                            error_msg = data.get("message", "未知错误")
                            logger.warning("%s API 错误: code=%s, message=%s", self.meta['name'], data.get('code'), error_msg)
                            yield {"error": f"{self.meta['name']} API 错误: {error_msg}"}
                            continue

                        content = ""
                        reasoning = ""

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
                            reasoning = delta.get("reasoning_content") or ""
                        else:
                            content = data.get("content") or ""

                        finish = data.get("choices", [{}])[0].get("finish_reason") if data.get("choices") else None
                        yield {
                            "content": content,
                            "reasoning_content": reasoning,
                            "finish_reason": finish
                        }
                    except (json.JSONDecodeError, IndexError) as e:
                        logger.debug("JSON 解析错误: %s, 原始数据: %s", e, data_str[:200])
                        continue

                # 成功完成，跳出重试循环
                break

            except requests.exceptions.HTTPError as e:
                error_body = ""
                if hasattr(e, "response") and e.response is not None:
                    try:
                        error_json = e.response.json()
                        error_body = error_json.get("error", {}).get("message", e.response.text[:500])
                    except Exception:
                        error_body = e.response.text[:500]
                    logger.warning("%s HTTP 错误响应: %s", self.meta['name'], error_body)
                yield {"error": f"{self.meta['name']} API 错误: {error_body if error_body else str(e)}"}
                return  # HTTP 错误不重试

            except requests.exceptions.RequestException as e:
                # 网络请求错误（连接超时、DNS 解析失败等）
                if attempt < max_retries:
                    logger.warning("%s 请求失败 (尝试 %s/%s): %s", self.meta['name'], attempt + 1, max_retries + 1, e)
                    time.sleep(1 * (attempt + 1))  # 指数退避
                    continue
                yield {"error": f"请求失败: {str(e)}"}
                return

            except OSError as e:
                # Windows socket 级别错误（如 [Errno 22] Invalid argument）
                # 在 Windows 上，urllib3 2.x 处理 SSL/TLS 连接时可能抛出此错误
                if attempt < max_retries:
                    logger.warning("%s socket 错误 (尝试 %s/%s): %s", self.meta['name'], attempt + 1, max_retries + 1, e)
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
                    logger.warning("%s 未知错误 (尝试 %s/%s): %s", self.meta['name'], attempt + 1, max_retries + 1, e)
                    time.sleep(1 * (attempt + 1))
                    continue
                yield {"error": f"请求失败: {str(e)}"}
                return
