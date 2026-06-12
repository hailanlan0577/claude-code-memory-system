"""
Copyright 2024, Zep Software, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import re
import typing

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from .config import DEFAULT_MAX_TOKENS, LLMConfig
from .openai_base_client import DEFAULT_REASONING, DEFAULT_VERBOSITY, BaseOpenAIClient


# === 本地补丁 (2026-06-12) ===========================================================
# 本实例的 LLM 后端是本地 llama.cpp / llama-server（如 Qwen3.6-35B 等本地 OpenAI 兼容模型）。
# 两个坑:
#   1) llama.cpp 的 /v1/responses(Responses API) 不强制结构化输出, 会把 JSON 裹进 ```json 围栏,
#      导致 responses.parse 严格校验抛 json_invalid。
#   2) 改走 /v1/chat/completions 后, json_object 模式也不强制语法(实测同请求时而吐纯文本)。
# 解法: _create_structured_completion 改用 chat.completions + response_format=json_schema
#      (按 response_model.model_json_schema() 让 llama.cpp 建 GBNF 语法, 强制输出合法且符合
#      schema 的 JSON); 复杂 schema 编译失败(400)则回退 json_object; 统一去 markdown 围栏;
#      返回一个仅暴露 _handle_structured_response 所需字段(output_text/usage/refusal)的壳对象。
# 仅适配本地 llama.cpp 后端, 不影响真 OpenAI。升级 graphiti_core 后需重新应用本补丁。

_FENCE_RE = re.compile(r'^```[a-zA-Z0-9]*\s*|\s*```$')


def _strip_code_fences(text: str) -> str:
    """去掉 llama.cpp 可能套在 JSON 外的 markdown 代码围栏。"""
    t = (text or '').strip()
    if t.startswith('```'):
        t = re.sub(r'^```[a-zA-Z0-9]*\s*', '', t)
        t = re.sub(r'\s*```$', '', t)
    return t.strip()


class _UsageShim:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _StructuredResponseShim:
    """模仿 OpenAI Responses 对象, 只提供 _handle_structured_response 用到的字段。"""

    def __init__(self, output_text: str, input_tokens: int, output_tokens: int):
        self.output_text = output_text
        self.usage = _UsageShim(input_tokens, output_tokens)
        self.refusal = None
# =====================================================================================


class OpenAIClient(BaseOpenAIClient):
    """
    OpenAIClient is a client class for interacting with OpenAI's language models.

    This class extends the BaseOpenAIClient and provides OpenAI-specific implementation
    for creating completions.

    Attributes:
        client (AsyncOpenAI): The OpenAI client used to interact with the API.
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        cache: bool = False,
        client: typing.Any = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        reasoning: str = DEFAULT_REASONING,
        verbosity: str = DEFAULT_VERBOSITY,
    ):
        """
        Initialize the OpenAIClient with the provided configuration, cache setting, and client.

        Args:
            config (LLMConfig | None): The configuration for the LLM client, including API key, model, base URL, temperature, and max tokens.
            cache (bool): Whether to use caching for responses. Defaults to False.
            client (Any | None): An optional async client instance to use. If not provided, a new AsyncOpenAI client is created.
        """
        super().__init__(config, cache, max_tokens, reasoning, verbosity)

        if config is None:
            config = LLMConfig()

        if client is None:
            self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        else:
            self.client = client

    async def _create_structured_completion(
        self,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel],
        reasoning: str | None = None,
        verbosity: str | None = None,
    ):
        """Create a structured completion.

        本地补丁: 走 chat.completions + json_schema (适配 本地 llama.cpp 强制语法),
        失败回退 json_object, 去围栏后用壳对象返回。
        """
        is_reasoning_model = (
            model.startswith('gpt-5') or model.startswith('o1') or model.startswith('o3')
        )

        # 本地 llama.cpp 的 json_object 模式不强制语法(实测会吐纯文本/markdown 围栏)。
        # 用 json_schema: 按 response_model 的 schema 建 GBNF 语法, 强制输出合法且符合 schema 的 JSON。
        # 万一某个复杂 schema 无法编译成语法(API 400), 回退 json_object + 去围栏兜底。
        temp = temperature if not is_reasoning_model else None
        try:
            completion = await self.client.chat.completions.create(
                model=model, messages=messages, temperature=temp, max_tokens=max_tokens,
                response_format={
                    'type': 'json_schema',
                    'json_schema': {
                        'name': (response_model.__name__ or 'Response')[:60],
                        'schema': response_model.model_json_schema(),
                    },
                },
            )
        except Exception:
            completion = await self.client.chat.completions.create(
                model=model, messages=messages, temperature=temp, max_tokens=max_tokens,
                response_format={'type': 'json_object'},
            )
        content = _strip_code_fences(completion.choices[0].message.content or '{}')
        usage = getattr(completion, 'usage', None)
        input_tokens = (getattr(usage, 'prompt_tokens', 0) or 0) if usage else 0
        output_tokens = (getattr(usage, 'completion_tokens', 0) or 0) if usage else 0
        return _StructuredResponseShim(content, input_tokens, output_tokens)

    async def _create_completion(
        self,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel] | None = None,
        reasoning: str | None = None,
        verbosity: str | None = None,
    ):
        """Create a regular completion with JSON format."""
        # Reasoning models (gpt-5 family) don't support temperature
        is_reasoning_model = (
            model.startswith('gpt-5') or model.startswith('o1') or model.startswith('o3')
        )

        return await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature if not is_reasoning_model else None,
            max_tokens=max_tokens,
            response_format={'type': 'json_object'},
        )
