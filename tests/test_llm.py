import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import BaseModel

from kept.adapters.egress import build_http_client
from kept.adapters.llm import LLMClient, LLMError, LLMOutputError, ModelNotConfiguredError
from kept.config import Settings
from kept.domain.models import AuditEvent, Tier


class NullSink:
    def record(self, event: AuditEvent) -> None:
        pass


class Answer(BaseModel):
    value: int


def _reply(content: str) -> httpx.Response:
    body = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
    }
    return httpx.Response(200, json=body)


def _client(handler: Callable[[httpx.Request], httpx.Response], **env: str) -> LLMClient:
    settings = Settings(_env_file=None, model_ultra=env.get("ultra", ""))
    http = build_http_client(
        [httpx.URL(settings.nebius_base_url).host],
        NullSink(),
        inner=httpx.MockTransport(handler),
    )
    return LLMClient(settings, http)


async def test_complete_json_strips_think_and_fences() -> None:
    client = _client(lambda _: _reply('<think>hmm</think>\n```json\n{"value": 3}\n```'))
    result = await client.complete_json(Tier.NANO, [{"role": "user", "content": "x"}], Answer)
    assert result.value == 3


async def test_complete_json_repairs_once() -> None:
    replies = iter(['{"value": "nope"}', '{"value": 7}'])
    seen: list[list[dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["messages"])
        return _reply(next(replies))

    client = _client(handler)
    result = await client.complete_json(Tier.SUPER, [{"role": "user", "content": "x"}], Answer)
    assert result.value == 7
    assert "did not match" in seen[1][-1]["content"]


async def test_complete_json_fails_after_repairs() -> None:
    client = _client(lambda _: _reply("not json"))
    with pytest.raises(LLMOutputError):
        await client.complete_json(Tier.NANO, [{"role": "user", "content": "x"}], Answer)


async def test_unconfigured_tier_raises() -> None:
    client = _client(lambda _: _reply("{}"))
    with pytest.raises(ModelNotConfiguredError):
        await client.complete(Tier.ULTRA, [{"role": "user", "content": "x"}])


async def test_thinking_false_is_sent_as_chat_template_kwarg() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _reply("ready")

    client = _client(handler)
    await client.complete(Tier.NANO, [{"role": "user", "content": "x"}], thinking=False)
    await client.complete(Tier.NANO, [{"role": "user", "content": "x"}])
    assert bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in bodies[1]


async def test_empty_content_error_explains_cause() -> None:
    client = _client(lambda _: _reply(""))
    with pytest.raises(LLMError, match="thinking=False"):
        await client.complete(Tier.NANO, [{"role": "user", "content": "x"}])
