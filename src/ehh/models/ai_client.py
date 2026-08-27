from typing import Literal

import anthropic
import openai
from munch import Munch

from ..utils.convert import mask_string_middle

AIClientKind = Literal["openai-chat-completions", "openai-responses", "anthropic-messages"]

# reasoning models on slow proxies can take well over a minute; give the
# request a generous timeout so it isn't cut off by the SDK default.
_REQUEST_TIMEOUT = 180.0
_MAX_RETRIES = 2
_ANTHROPIC_MAX_TOKENS = 8192


class AIClient:
    kind: AIClientKind
    api_url: str
    api_key: str
    models: list[str]
    selected_model_index: int
    client: openai.OpenAI | anthropic.Anthropic

    def __init__(
        self,
        kind: AIClientKind,
        api_url: str,
        api_key: str,
        models: list[str],
        sel_model: int,
    ):
        self.kind = kind
        self.api_url = api_url
        self.api_key = api_key
        self.models = models
        self.selected_model_index = sel_model

        if kind in ("openai-chat-completions", "openai-responses"):
            self.client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.api_url,
                timeout=_REQUEST_TIMEOUT,
                max_retries=_MAX_RETRIES,
            )
        elif kind == "anthropic-messages":
            # most Anthropic-compatible proxies (incl. PackyCode) expect a
            # bearer token rather than the x-api-key header api_key= sends.
            self.client = anthropic.Anthropic(
                auth_token=self.api_key,
                base_url=self.api_url,
                timeout=_REQUEST_TIMEOUT,
                max_retries=_MAX_RETRIES,
            )
        else:
            raise ValueError(f"unknown AI client kind: {kind}")

    @classmethod
    def from_dict(cls, data: Munch):
        return cls(
            data.kind, data.api_url, data.api_key, data.model.all, data.model.selected
        )

    def describe(self) -> str:
        return f"{self.kind}: {self.api_url} / {mask_string_middle(self.api_key)} / {self.models}"

    @property
    def selected_model(self) -> str:
        return self.models[self.selected_model_index]

    def generate(self, system_prompt: str, user_prompt: str) -> str | None:
        """Send a system+user prompt, dispatching on `kind`, and return the raw text response."""
        if self.kind == "openai-chat-completions":
            response = self.client.chat.completions.create(
                model=self.selected_model,
                messages=[
                    {
                        "role": "system",
                        "content": [{"type": "text", "text": system_prompt}],
                    },
                    {"role": "user", "content": [{"type": "text", "text": user_prompt}]},
                ],
            )
            return response.choices[0].message.content
        elif self.kind == "openai-responses":
            response = self.client.responses.create(
                model=self.selected_model,
                instructions=system_prompt,
                input=user_prompt,
            )
            return response.output_text
        elif self.kind == "anthropic-messages":
            response = self.client.messages.create(
                model=self.selected_model,
                max_tokens=_ANTHROPIC_MAX_TOKENS,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": [{"type": "text", "text": user_prompt}]}
                ],
            )
            return "".join(
                block.text for block in response.content if block.type == "text"
            )
        else:
            raise ValueError(f"unknown AI client kind: {self.kind}")
