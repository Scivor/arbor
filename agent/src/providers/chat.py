"""ChatOpenAI: OpenAI-compatible LLM client with function-calling support.

Adapts Vibe-Trading's ChatLLM pattern to coffee_v3's openai-based stack.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import openai

# Alias for Vibe-Trading compatibility
ChatLLM = None  # Will be set after class definition


class LLMResponse:
    """LLM response container."""

    def __init__(
        self,
        content: Optional[str] = None,
        tool_calls: list | None = None,
        finish_reason: str = "stop",
    ):
        self.content = content
        # Normalise: accept dicts or objects with .name
        self.tool_calls = self._normalise(tool_calls or [])
        self.finish_reason = finish_reason

    @staticmethod
    def _normalise(calls: list) -> list:
        """Coerce dicts to objects with .name for Vibe-Trading compatibility."""
        result = []
        for c in calls:
            if isinstance(c, dict):
                args = c.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                obj = type("TC", (), {"id": c.get("id", ""), "name": c.get("name", ""), "arguments": args})()
                result.append(obj)
            else:
                result.append(c)
        return result

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class ChatOpenAI:
    """OpenAI-compatible LLM client using DeepSeek API.

    Environment variables:
        DEEPSEEK_API_KEY — API key (required)
        OPENAI_API_KEY   — Alias (used if DEEPSEEK_API_KEY not set)
        DEEPSEEK_BASE_URL — Base URL (default: https://api.deepseek.com)
        DEEPSEEK_MODEL   — Model (default: deepseek-chat)
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.model_name = model_name or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"

        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is not set")

        self._client = openai.OpenAI(api_key=api_key, base_url=self.base_url)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[int] = None,
    ) -> LLMResponse:
        """Call the LLM synchronously.

        Args:
            messages: Message list (OpenAI format).
            tools: Tool definition list (OpenAI function calling format).
            timeout: Optional per-call timeout in seconds.

        Returns:
            LLMResponse with content and tool_calls.
        """
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if timeout:
            kwargs["timeout"] = timeout

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        # Parse tool calls
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                })

        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
        )

    def chat_with_raw(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return the raw API response dict (for streaming)."""
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if timeout:
            kwargs["timeout"] = timeout

        chunks: list[str] = []
        completion_content: str = ""
        raw_tool_calls: list[dict] = []

        stream = self._client.chat.completions.create(**kwargs)
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                chunks.append(delta.content)
                completion_content += delta.content
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    if raw_tool_calls and tc.index == (len(raw_tool_calls) - 1):
                        # Append to last
                        existing = raw_tool_calls[-1]
                        if tc.function.arguments:
                            existing["function"]["arguments"] += tc.function.arguments or ""
                    else:
                        raw_tool_calls.append({
                            "id": tc.id or "",
                            "function": {
                                "name": tc.function.name or "",
                                "arguments": tc.function.arguments or "",
                            },
                        })

        parsed_calls = []
        for tc in raw_tool_calls:
            parsed_calls.append({
                "id": tc["id"],
                "name": tc["function"]["name"],
                "arguments": tc["function"]["arguments"],
            })

        return {
            "content": completion_content,
            "tool_calls": parsed_calls,
            "finish_reason": "stop",
        }


# Alias for Vibe-Trading loop.py compatibility
ChatLLM = ChatOpenAI


def _stream_chat(
    self,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    on_text_chunk: Optional[Callable[[str], None]] = None,
) -> LLMResponse:
    raw = self.chat_with_raw(messages, tools=tools)
    if on_text_chunk:
        for ch in raw["content"]:
            on_text_chunk(ch)
    return LLMResponse(
        content=raw["content"],
        tool_calls=raw.get("tool_calls", []),
        finish_reason=raw.get("finish_reason", "stop"),
    )


ChatOpenAI.stream_chat = _stream_chat
