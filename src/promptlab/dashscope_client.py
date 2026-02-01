"""Minimal client for DashScope/Qwen API using native SDK."""

import os
from typing import Optional

from dotenv import load_dotenv
import dashscope
from dashscope import Generation

load_dotenv()

# Set DashScope base URL
dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"


class DashScopeClient:
    """Minimal client for DashScope/Qwen API using native SDK."""

    DEFAULT_MODEL = "qwen3-235b-a22b-instruct-2507"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY not set. "
                "Please set it in .env file or environment variable."
            )

        self.model = model or os.getenv("QWEN_MODEL", self.DEFAULT_MODEL)

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """
        Send a chat completion request.

        Args:
            system_prompt: System message content
            user_message: User message content
            temperature: Sampling temperature (lower = more deterministic)
            max_tokens: Maximum response tokens

        Returns:
            Model response text
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        response = Generation.call(
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            result_format="message",
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.output.choices[0].message.content
