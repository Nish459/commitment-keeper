"""Tiered Token Factory client. Callers ask for a Tier, never a model string."""

import re
from typing import Any

import httpx
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from kept.config import Settings
from kept.domain.models import Tier

Messages = list[dict[str, str]]

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class LLMError(Exception):
    """The model call failed."""


class ModelNotConfiguredError(LLMError):
    """No model ID is configured for the requested tier."""


class LLMOutputError(LLMError):
    """The model replied, but not with valid structured output."""


def _clean(text: str) -> str:
    return _CODE_FENCE.sub("", _THINK_BLOCK.sub("", text).strip()).strip()


class LLMClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.nebius_api_key.get_secret_value() or "unset",
            base_url=settings.nebius_base_url,
            http_client=http_client,
            max_retries=2,
        )

    async def complete(
        self,
        tier: Tier,
        messages: Messages,
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        model = self._settings.model_for(tier)
        if not model:
            raise ModelNotConfiguredError(f"No model configured for tier '{tier}'")
        extra: dict[str, Any] = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
                **extra,
            )
        except OpenAIError as exc:
            raise LLMError(f"{tier} call failed: {exc}") from exc
        content = response.choices[0].message.content
        if not content:
            raise LLMError(f"{tier} returned an empty response")
        return _clean(content)

    async def complete_json[T: BaseModel](
        self,
        tier: Tier,
        messages: Messages,
        schema: type[T],
        *,
        repairs: int = 1,
        **kwargs: Any,
    ) -> T:
        """Validate model output against `schema`, asking the model to repair it on failure."""
        convo = list(messages)
        last_error = ""
        for _ in range(repairs + 1):
            raw = await self.complete(tier, convo, json_mode=True, **kwargs)
            try:
                return schema.model_validate_json(raw)
            except ValidationError as exc:
                last_error = str(exc)
                convo = [
                    *messages,
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": "That did not match the required JSON schema. "
                        f"Fix it and reply with JSON only.\nErrors:\n{last_error}",
                    },
                ]
        raise LLMOutputError(
            f"Invalid structured output after {repairs + 1} attempts: {last_error}"
        )
