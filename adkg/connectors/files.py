"""本地文件 connector：遍历 root 下的 Markdown 文档（Phase 2a 文档路）。

source_type 由调用方给（guidelines → official_doc，案例文档 → wiki）；
source_id 用相对路径，稳定且可回跳。
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from adkg.connectors.base import RawRecord
from adkg.models import SourceType


class FilesConnector:
    def __init__(self, root: Path, source_type: str = "official_doc",
                 pattern: str = "*.md") -> None:
        self.root = Path(root)
        self.source_type = SourceType(source_type)
        self.pattern = pattern                         # 同目录分批摄取（raw 平铺：C-*/G-*）

    def fetch(self) -> Iterator[RawRecord]:
        for path in sorted(self.root.rglob(self.pattern)):
            yield RawRecord(
                source_ref=str(path.relative_to(self.root)),
                text=path.read_text(encoding="utf-8"),
                provenance={  # Pydantic 会校验并派生 authority
                    "source_type": self.source_type.value,
                    "source_id": f"file:{path.relative_to(self.root)}",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },  # type: ignore[arg-type]
            )
