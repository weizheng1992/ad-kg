"""平台后台导出文件 connector（§五 数据三层③）：导出 CSV → raw 落盘 + ETL 入口。

官方 API 需真实代理商授权，留给部署方（connector 双 adapter 成真 seam，§9.6）；
演示与冷启动走这条路：把后台导出的报表 CSV 放进目录，按文件名认平台。
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from adkg.connectors.base import RawRecord

# 文件名子串 → mapping 名（ontology/mappings/<名>.yaml）
PLATFORM_BY_FILENAME = {"douyin": "douyin", "巨量": "douyin",
                        "xiaohongshu": "xiaohongshu", "聚光": "xiaohongshu"}


class PlatformsExportConnector:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def etl_targets(self) -> list[tuple[Path, str]]:
        """[(csv 路径, mapping 名)]，供 etl_csv 逐个灌入。"""
        targets = []
        for path in sorted(self.root.glob("*.csv")):
            for key, mapping in PLATFORM_BY_FILENAME.items():
                if key in path.name:
                    targets.append((path, mapping))
                    break
        return targets

    def fetch(self) -> Iterator[RawRecord]:
        """导出文件落原始层（不可变，§二.5）——内容解释归 etl_facts。"""
        for path, _ in self.etl_targets():
            yield RawRecord(
                source_ref=str(path.relative_to(self.root)),
                text=path.read_text(encoding="utf-8"),
                provenance={
                    "source_type": "platform_api",
                    "source_id": f"platform_export:{path.name}",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },  # type: ignore[arg-type]
            )
