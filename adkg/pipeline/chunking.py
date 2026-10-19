"""Markdown 分块（Phase 2a）：按标题切、超长段二切，产出 (index, text) 序列。

纯函数，不碰 provenance——由 pipeline 在入库时挂上（§四：层间通过 models 交互）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True)
class ChunkText:
    chunk_index: int
    text: str
    heading: str


def _split_long(text: str, max_chars: int) -> list[str]:
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)] or [""]


def chunk_markdown(doc: str, max_chars: int = 500) -> tuple[str, list[ChunkText]]:
    """返回 (frontmatter, chunks)。frontmatter 无则空串；块索引从 0 连续。"""
    if not doc.strip():
        raise ValueError("空文档不可分块")

    m = _FRONTMATTER.match(doc)
    frontmatter = m.group(1) if m else ""
    body = doc[m.end():] if m else doc

    sections: list[tuple[str, str]] = []   # (heading, 段落集合)
    heading, buf = "", []
    for line in body.splitlines():
        if line.startswith("#"):
            if buf:
                sections.append((heading, "\n".join(buf).strip()))
            heading, buf = line.strip(), []
        else:
            buf.append(line)
    if buf:
        sections.append((heading, "\n".join(buf).strip()))

    chunks: list[ChunkText] = []
    idx = 0
    for head, para in sections:
        if not para:
            continue
        section_text = f"{head}\n{para}" if head else para
        for piece in _split_long(section_text, max_chars):
            chunks.append(ChunkText(chunk_index=idx, text=piece.strip(), heading=head))
            idx += 1
    if not chunks:                          # 只有 frontmatter / 只有标题
        chunks.append(ChunkText(chunk_index=0, text=body.strip(), heading=""))
    return frontmatter, chunks
