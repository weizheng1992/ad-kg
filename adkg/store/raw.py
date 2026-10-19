"""原始层（§八）：不可变、带 hash、可重跑。

同一 key 同内容重写为 no-op（幂等）；不同内容直接拒绝——原始层落盘后不改（§二.5）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path


class RawStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, key: str, text: str) -> tuple[str, str]:
        """落盘返回 (相对路径, sha256)；旁写 <key>.sha256 校验文件。"""
        path = self.root / key
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                return key, digest
            raise FileExistsError(f"原始层不可变：{key} 已存在且内容不同（§二.5）")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        (self.root / f"{key}.sha256").write_text(digest, encoding="utf-8")
        return key, digest
