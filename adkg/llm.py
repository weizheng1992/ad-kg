"""LLM 适配层（§五）：OpenAI 兼容接口，抽取 / 路由 / Text2SQL / judge 共用。

嵌入同走 OpenAI 兼容 API（百炼 qwen3.7-text-embedding-flash / bge 本地降级）；缺 key 时调用方按 §7.2 降级矩阵处理。
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
            timeout=30, max_retries=1,              # 限流时快速失败走降级（§7.2）
        )
        self._model = os.environ.get("ADKG_LLM_MODEL", "glm-5.3-flash")
        self._embed_api_base = os.environ.get("ADKG_EMBED_BASE_URL", "")
        self._embed_model = os.environ.get("ADKG_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
        self._embed_client = (OpenAI(base_url=self._embed_api_base,
                                     api_key=os.environ.get("ADKG_EMBED_API_KEY"))
                              if self._embed_api_base else None)
        self._embed_dim = int(os.environ.get("ADKG_EMBED_DIM", "0") or 0)
        self._local_embedder = None                     # 惰性加载本地模型

    def chat_json(self, system: str, user: str) -> dict:
        """一次对话拿 JSON（结构化输出由调用方按 Pydantic 校验兜底）。"""
        resp = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            temperature=0,                                  # 路由/judge 要确定性
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        import json
        return json.loads(resp.choices[0].message.content or "{}")

    def batch_chat_json(self, system: str, user: str) -> dict:
        """批任务（抽取/批量判分）：走 ADKG_LLM_BATCH_* 配置——coding 端点
        为交互设计限流严格，批式走普通端点免费档（glm-4-flash），缺省回落主配置。"""
        base = os.environ.get("ADKG_LLM_BATCH_BASE_URL") or \
            os.environ.get("ADKG_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
        model = os.environ.get("ADKG_LLM_BATCH_MODEL", "glm-4-flash")
        client = OpenAI(base_url=base, api_key=os.environ["ADKG_LLM_API_KEY"],
                        timeout=30, max_retries=2)
        resp = client.chat.completions.create(
            model=model, response_format={"type": "json_object"}, temperature=0,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        import json
        return json.loads(resp.choices[0].message.content or "{}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        """嵌入：配了 EMBED_BASE_URL 走 API（dimensions 按 ADKG_EMBED_DIM 下发），否则本地 sentence-transformers。"""
        if self._embed_client is not None:
            kwargs: dict = {"model": self._embed_model, "input": texts}
            if self._embed_dim:
                kwargs["dimensions"] = self._embed_dim
            resp = self._embed_client.embeddings.create(**kwargs)
            return [d.embedding for d in resp.data]
        if self._local_embedder is None:
            from sentence_transformers import SentenceTransformer
            self._local_embedder = SentenceTransformer(self._embed_model)
        vecs = self._local_embedder.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]


ChatJsonFn = Callable[[str, str], dict]
EmbedFn = Callable[[list[str]], list[list[float]]]
