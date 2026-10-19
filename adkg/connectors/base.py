"""接入层协议（README §四）：Connector 只拿原始数据，不做语义解释。

fetch() 产出的每条 RawRecord 必带 provenance——缺失即拒绝入库（§12.1）。
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from pydantic import BaseModel

from adkg.models import Provenance, SourceType


class RawRecord(BaseModel):
    """一条原始记录：来源引用 + 文本 + provenance。"""

    source_ref: str                    # 相对路径 / 文档 ID / API 请求标识
    text: str
    provenance: Provenance


class Connector(Protocol):
    """接入层协议；files / feishu / platforms / warehouse 四个 adapter 共用。"""

    def fetch(self) -> Iterator[RawRecord]: ...
