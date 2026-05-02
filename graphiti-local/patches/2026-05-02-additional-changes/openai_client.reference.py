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

import logging
import typing

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from .config import DEFAULT_MAX_TOKENS, LLMConfig
from .openai_base_client import DEFAULT_REASONING, DEFAULT_VERBOSITY, BaseOpenAIClient

logger = logging.getLogger(__name__)


class _FallbackUsage:
    """Maps chat completion usage attrs to responses API attrs."""

    def __init__(self, usage: typing.Any) -> None:
        self.input_tokens = getattr(usage, 'prompt_tokens', 0) or 0
        self.output_tokens = getattr(usage, 'completion_tokens', 0) or 0


class _ChatCompletionWrapper:
    """Wraps a chat completion response to match the responses API interface."""

    def __init__(self, completion: typing.Any) -> None:
        self.output_text = completion.choices[0].message.content or '{}'
        self.usage = _FallbackUsage(completion.usage) if completion.usage else None


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
        """Create a structured completion using OpenAI's beta parse API."""
        # Reasoning models (gpt-5 family) don't support temperature
        is_reasoning_model = (
            model.startswith('gpt-5') or model.startswith('o1') or model.startswith('o3')
        )

        request_kwargs = {
            'model': model,
            'input': messages,  # type: ignore
            'max_output_tokens': max_tokens,
            'text_format': response_model,  # type: ignore
        }

        temperature_value = temperature if not is_reasoning_model else None
        if temperature_value is not None:
            request_kwargs['temperature'] = temperature_value

        # Only include reasoning and verbosity parameters for reasoning models
        if is_reasoning_model and reasoning is not None:
            request_kwargs['reasoning'] = {'effort': reasoning}  # type: ignore

        if is_reasoning_model and verbosity is not None:
            request_kwargs['text'] = {'verbosity': verbosity}  # type: ignore

        try:
            response = await self.client.responses.parse(**request_kwargs)
            return response
        except Exception as e:
            # 触发 fallback 的场景:
            # - dashscope qwen-plus: validation error / json parse 失败
            # - mlx_lm.server: 不实现 /v1/responses → 404 Not Found
            # - mlx_vlm.server: ParsedResponse text/parsed 为 None → "Invalid response from LLM"
            # 简化: 所有 responses.parse 失败都尝试 chat.completions fallback
            logger.warning(
                'responses.parse failed, falling back to chat.completions: %s', e
            )
            fallback_messages = list(messages)
            if fallback_messages and fallback_messages[0].get('role') == 'system':
                fallback_messages[0] = {
                    **fallback_messages[0],
                    'content': fallback_messages[0]['content']
                        + '\nRespond with valid JSON.',
                }
            else:
                fallback_messages.insert(
                    0, {'role': 'system', 'content': 'Respond with valid JSON.'}
                )
            fallback_kwargs: dict[str, typing.Any] = {
                'model': model,
                'messages': fallback_messages,
                'max_tokens': max_tokens,
                'response_format': {'type': 'json_object'},
            }
            if temperature_value is not None:
                fallback_kwargs['temperature'] = float(temperature_value)
            try:
                fallback = await self.client.chat.completions.create(**fallback_kwargs)
                return _ChatCompletionWrapper(fallback)
            except Exception as fallback_e:
                logger.error('chat.completions fallback also failed: %s', fallback_e)
                raise e

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
