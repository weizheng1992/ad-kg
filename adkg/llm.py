"""LLM 适配层（§五）：OpenAI 兼容接口，抽取 / 路由 / Text2SQL / judge 共用。

嵌入同走 OpenAI 兼容 API（Qwen3-Embedding）；缺 key 时调用方按 §7.2 降级矩阵处理。
"""
from __future__ import annotations

import os
from typing import Callable

from openai import OpenAI


class LLMClient:
    def __init__(self) -> None:
        self._client = OpenAI(
            base_url=os.environ.get("ADKG_LLM_BASE_URL"),
            api_key=os.environ.get("ADKG_LLM_API_KEY"),
        )
        self._model = os.environ.get("ADKG_LLM_MODEL", "glm-4.6")
        self._embed_client = OpenAI(
            base_url=os.environ.get("ADKG_EMBED_BASE_URL"),
            api_key=os.environ.get("ADKG_EMBED_API_KEY"),
        )
        self._embed_model = os.environ.get("ADKG_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")

    def chat_json(self, system: str, user: str) -> dict:
        """一次对话拿 JSON（结构化输出由调用方按 Pydantic 校验兜底）。"""
        resp = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        import json
        return json.loads(resp.choices[0].message.content or "{}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._embed_client.embeddings.create(model=self._embed_model,
                                                    input=texts)
        return [d.embedding for d in resp.data]


ChatJsonFn = Callable[[str, str], dict]
EmbedFn = Callable[[list[str]], list[list[float]]]
