"""
服务商元数据配置 + 全局 System Prompt
纯数据模块，不含业务逻辑
"""

# ============================================================
# 全局固定 System Prompt
# ============================================================

SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "你是一个全能 AI 助手，能够帮助用户完成写作、编程、分析、问答、翻译、数学推导等各类任务。\n"
        "#### 工作原则\n"
        "- 直接回应用户需求，避免冗余开场白。\n"
        "- 优先给出具体、可执行的答案，必要时提供多种方案供用户选择。\n"
        "- 在信息不足时，主动询问关键细节，而非凭空猜测。\n"
        "#### 输出格式\n"
        "- 使用 Markdown 组织回答：标题、列表、代码块、表格按需使用。\n"
        "- 代码片段须标明语言类型，关键步骤附加注释。\n"
        "- 重要结论或警告用 **粗体** 或 > 引用块标注。\n"
        "#### 回答风格\n"
        "- 语气专业、简洁，避免过度口语化。\n"
        "- 尊重用户已有知识，不做过度解释；对初学者则补充必要背景。\n"
        "- 遇到不确定的事实，坦诚说明并建议用户核实。"
    )
}

# ============================================================
# 服务商元数据
# ============================================================

PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "context_window": 1048565,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "deepseek-v4-pro",
        "description": "DeepSeek V4 系列模型，支持 1M 上下文"
    },
    "kimi": {
        "name": "Kimi (月之暗面)",
        "base_url": "https://api.moonshot.cn/v1",
        "models": [
            "kimi-k2.6",
            "kimi-k2.5",
            "kimi-k2-thinking",
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
            "moonshot-v1-8k-vision-preview",
            "moonshot-v1-32k-vision-preview",
            "moonshot-v1-128k-vision-preview"
        ],
        "context_window": 8192,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "kimi-k2.6",
        "description": "月之暗面 Kimi 系列模型（K2.6/K2.5/K2-Thinking/Moonshot V1）｜API文档: https://platform.kimi.com/docs/api/overview",
        "supports_native_upload": True
    },
    "zhipu": {
        "name": "智谱AI (GLM)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-plus", "glm-4-flash", "glm-4.7", "glm-5.1"],
        "context_window": 131072,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "glm-5.1",
        "description": "智谱AI GLM-5 系列模型"
    },
    "qwen": {
        "name": "通义千问 (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo"],
        "context_window": 32768,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "qwen-plus",
        "description": "阿里云通义千问系列模型"
    },
    "ernie": {
        "name": "文心一言 (ERNIE)",
        "base_url": "https://qianfan.baidubce.com/v2",
        "models": [
            "ernie-4.0-turbo-8k",
            "ernie-4.0-8k",
            "ernie-3.5-8k",
            "ernie-3.5-128k",
            "ernie-speed-pro-128k",
            "ernie-x1-turbo-32k",
            "ernie-4.5-turbo-128k",
            "minimax-m2.5"
        ],
        "context_window": 8192,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "ernie-4.0-turbo-8k",
        "description": "百度千帆V2新版（兼容OpenAI协议，单API Key认证，最大输出2048 tokens）"
    },
    "doubao": {
        "name": "豆包 (字节跳动)",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": ["doubao-seed-2-0-code-preview-260215", "doubao-seed-2-0-lite-260215", "doubao-seed-2-0-mini-260215", "doubao-seed-2-0-pro-260215"],
        "context_window": 32768,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "doubao-seed-2-0-mini-260215",
        "description": "字节跳动豆包 Seed 2.0 系列模型（兼容 OpenAI 协议，单 API Key 认证）"
    },
    "nvidia": {
        "name": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "models": [
            "deepseek-ai/deepseek-v4-pro",
            "meta/llama-3.1-405b-instruct",
            "google/gemma-4-31b-it"
        ],
        "context_window": 131072,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "deepseek-ai/deepseek-v4-pro",
        "description": "NVIDIA NIM 推理微服务，支持多种开源模型 | 获取 Key: https://build.nvidia.com"
    },
    "shuyan": {
        "name": "数眼智能",
        "base_url": "https://platform.shuyanai.com/v1",
        "models": [
            "mimo-v2-pro",
            "mimo-v2.5-pro",
            "MiniMax-M2.7"
        ],
        "context_window": 131072,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "mimo-v2-pro",
        "description": "数眼智能 Mimo 系列模型（国内：platform.shuyanai.com，国际：cloud.shuyanai.com）"
    },
    "tencent": {
        "name": "腾讯云 MaaS",
        "base_url": "https://tokenhub.tencentmaas.com/v1",
        "models": [
            "glm-5v-turbo",
            "deepseek-v3-0324",
            "glm-5.1",
            "deepseek-v3.2",
            "kimi-k2.5",
            "hunyuan-2.0-thinking-20251109",
            "hunyuan-2.0-instruct-20251111",
            "deepseek-v3.1-terminus",
            "kimi-k2.6",
            "minimax-m2.7",
            "glm-5",
            "hunyuan-role-latest",
            "minimax-m2.5",
            "deepseek-v4-flash",
            "hy3-preview",
            "deepseek-v4-pro"
        ],
        "context_window": 32768,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "deepseek-v4-pro",
        "description": "腾讯云 MaaS 统一接口，聚合多种开源/第三方模型 | 获取 Key: https://console.cloud.tencent.com"
    },
    "siliconflow": {
        "name": "硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": [
            "Pro/zai-org/GLM-5",
            "Pro/zai-org/GLM-4.7",
            "deepseek-ai/DeepSeek-V3.2",
            "Pro/deepseek-ai/DeepSeek-V3.2",
            "deepseek-ai/DeepSeek-V4-Flash",
            "zai-org/GLM-4.6",
            "Qwen/Qwen3-8B",
            "Qwen/Qwen3-14B",
            "Qwen/Qwen3-32B",
            "Qwen/Qwen3-30B-A3B",
            "tencent/Hunyuan-A13B-Instruct",
            "zai-org/GLM-4.5V",
            "deepseek-ai/DeepSeek-V3.1-Terminus",
            "Pro/deepseek-ai/DeepSeek-V3.1-Terminus",
            "Qwen/Qwen3.5-397B-A17B",
            "Qwen/Qwen3.5-122B-A10B",
            "Qwen/Qwen3.5-35B-A3B",
            "Qwen/Qwen3.5-27B",
            "Qwen/Qwen3.5-9B",
            "Qwen/Qwen3.5-4B"
        ],
        "context_window": 32768,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "Qwen/Qwen3-14B",
        "description": "硅基流动 SiliconFlow 平台，支持 GLM / DeepSeek / Qwen / Hunyuan 等模型 | 获取 Key: https://cloud.siliconflow.cn"
    },
    "intern": {
        "name": "书生·浦语 (Intern)",
        "base_url": "https://chat.intern-ai.org.cn/api/v1",
        "models": [
            "intern-latest",
            "internvl3.5-latest",
            "intern-s1-pro",
            "intern-s1",
            "intern-s1-mini",
            "internvl3.5-241b-a28b"
        ],
        "context_window": 32768,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "intern-latest",
        "description": "上海人工智能实验室书生·浦语 InternLM 系列模型，支持长上下文和多模态 | 获取 Key: https://chat.intern-ai.org.cn"
    },
    "xiaomi": {
        "name": "小米 MiMo",
        "base_url": "https://api.xiaomimimo.com/v1",
        "models": [
            "mimo-v2.5-pro",
            "mimo-v2.5",
            "mimo-v2-pro",
            "mimo-v2-omni"
        ],
        "context_window": 32768,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "mimo-v2.5-pro",
        "description": "小米 MiMo 系列模型，小米官方 AI 服务 | 获取 Key: https://api.xiaomimimo.com"
    },
    "xinghuo_pro": {
        "name": "星火 Pro",
        "base_url": "https://spark-api-open.xf-yun.com/v1",
        "models": ["generalv3"],
        "context_window": 8192,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "generalv3",
        "description": "讯飞星火 Pro 版（generalv3）｜密钥独立 | 获取 Key: https://console.xfyun.cn"
    },
    "xinghuo_x2": {
        "name": "星火 X2",
        "base_url": "https://spark-api-open.xf-yun.com/x2",
        "models": ["spark-x"],
        "context_window": 32768,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "spark-x",
        "description": "讯飞星火 X2 版本｜密钥独立 | 获取 Key: https://console.xfyun.cn"
    },
    "xinghuo_x2_flash": {
        "name": "星火 X2 Flash",
        "base_url": "https://spark-api-open.xf-yun.com/agent/v1",
        "models": ["spark-x"],
        "context_window": 32768,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "spark-x",
        "description": "讯飞星火 spark-x 快速版｜密钥独立 | 获取 Key: https://console.xfyun.cn"
    },
    "weelinking": {
        "name": "weelinking",
        "base_url": "https://api.weelinking.com/v1",
        "models": [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3-flash-preview",
            "gpt-5.3-codex",
            "gpt-5.2",
            "gpt-5.4",
            "gpt-5.4-mini",
            "claude-haiku-4-5-20251001",
            "claude-haiku-4-5-20251001-thinking",
        ],
        "context_window": 32768,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "gpt-5.3-codex",
        "description": "weelinking 模型聚合（Gemini/Claude→chat/completions | GPT→responses）| 获取 Key: https://api.weelinking.com/"
    },
    "tokendance": {
        "name": "tokenDance",
        "base_url": "https://tokendance.space/gateway/v1",
        "models": ["mimo-v2.5-pro", "deepseek-v4-pro"],
        "context_window": 131072,
        "auth_type": "bearer",
        "auth_fields": ["api_key"],
        "default_model": "mimo-v2.5-pro",
        "description": "tokenDance 模型聚合平台 | 获取 Key: https://tokendance.space"
    }
}
