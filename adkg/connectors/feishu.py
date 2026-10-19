"""飞书云文档 connector（§四 / §7.2）：按 revision 增量同步，新版本 supersedes 旧版本。

- 认证：自建应用 tenant_access_token（app_id/secret 在 .env，凭据不进仓库）
- 文档类型：新版文档（docx）；取 raw_content 纯文本，revision 作 provenance.version
- transport 依赖注入：单测塞假实现，线上走 httpx

上线前置（飞书开放平台）：给应用开通云文档只读权限（docx:document:readonly
或 drive:drive:readonly）、发布版本、把目标文档/文件夹授权给应用。
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Callable

import httpx

from adkg.connectors.base import RawRecord

BASE = "https://open.feishu.cn"

# transport(method, url, headers=None, json=None) -> 已解析的 JSON dict
Transport = Callable[..., dict]


def httpx_transport(method: str, url: str, *, headers: dict | None = None,
                    json: dict | None = None) -> dict:
    resp = httpx.request(method, url, headers=headers, json=json, timeout=15)
    resp.raise_for_status()
    return resp.json()


class FeishuConnector:
    def __init__(self, app_id: str, app_secret: str, doc_tokens: list[str],
                 transport: Transport = httpx_transport, base: str = BASE) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.doc_tokens = doc_tokens
        self._transport = transport
        self._base = base
        self._token: str | None = None        # 惰性 + 进程内缓存（expire ~2h）

    # ---------------------------------------------------------------- auth
    def _tenant_token(self) -> str:
        if self._token is None:
            data = self._transport(
                "POST", f"{self._base}/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret})
            self._check(data, "获取 tenant_access_token")
            self._token = data["tenant_access_token"]
        return self._token

    @staticmethod
    def _check(data: dict, action: str) -> None:
        if data.get("code", 0) != 0:
            raise RuntimeError(f"飞书 {action} 失败：code={data.get('code')} msg={data.get('msg')}")

    def _get(self, path: str, action: str) -> dict:
        data = self._transport("GET", f"{self._base}{path}",
                               headers={"Authorization": f"Bearer {self._tenant_token()}"})
        self._check(data, action)
        return data

    # ---------------------------------------------------------------- fetch
    def fetch(self) -> Iterator[RawRecord]:
        for token in self.doc_tokens:
            meta = self._get(f"/open-apis/docx/v1/documents/{token}", f"读取文档信息 {token}")
            doc = meta["data"]["document"]
            revision = str(doc.get("revision_id", ""))
            content = self._get(
                f"/open-apis/docx/v1/documents/{token}/raw_content",
                f"读取文档内容 {token}")["data"].get("content", "")
            if not content.strip():
                continue                           # 空文档不入库
            yield RawRecord(
                source_ref=f"feishu/{token}",
                text=content,
                provenance={
                    "source_type": "official_doc",
                    "source_id": f"feishu:doc:{token}",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "version": revision or None,   # 幂等键的一半（§八）
                    "source_url": f"https://feishu.cn/docx/{token}",
                },  # type: ignore[arg-type]
            )
