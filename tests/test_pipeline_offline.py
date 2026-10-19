"""加工层离线单元测试：chunking / connectors(files) / store(raw)（Phase 2a）。"""
import pytest

from adkg.connectors.base import RawRecord
from adkg.connectors.files import FilesConnector
from adkg.pipeline.chunking import chunk_markdown
from adkg.store.raw import RawStore


# ---------------------------------------------------------------- chunking
class TestChunking:
    DOC = """---
title: 信息流视频规范
---

# 信息流视频规范

## 时长要求
信息流视频前 3 秒须出现品牌标识，不得使用纯文字开场。""" + "补充说明。" * 120 + """

## 尺寸要求
竖版 9:16，横版 16:9，分辨率不低于 1080p。
"""

    def test_剥离frontmatter_按标题分块(self):
        frontmatter, chunks = chunk_markdown(self.DOC, max_chars=500)
        assert "title: 信息流视频规范" in frontmatter
        texts = [c.text for c in chunks]
        assert any("时长要求" in t for t in texts)
        assert any("尺寸要求" in t for t in texts)

    def test_超长段按max_chars切(self):
        _, chunks = chunk_markdown(self.DOC, max_chars=500)
        assert all(len(c.text) <= 500 for c in chunks)
        assert len(chunks) >= 3

    def test_块索引连续(self):
        _, chunks = chunk_markdown(self.DOC, max_chars=500)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

    def test_空文档拒绝(self):
        with pytest.raises(ValueError):
            chunk_markdown("   \n  ", max_chars=500)


# ---------------------------------------------------------------- connectors
class TestFilesConnector:
    def test_遍历md产出RawRecord_带provenance(self, tmp_path):
        (tmp_path / "a.md").write_text("# A\n正文", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.md").write_text("# B\n正文", encoding="utf-8")
        (tmp_path / "c.txt").write_text("忽略", encoding="utf-8")

        conn = FilesConnector(root=tmp_path, source_type="official_doc")
        records = list(conn.fetch())
        assert len(records) == 2                      # 只认 .md
        assert all(r.provenance.source_type == "official_doc" for r in records)
        refs = sorted(r.source_ref for r in records)
        assert refs == ["a.md", "sub/b.md"]           # 相对路径稳定
        rec = records[0]
        assert isinstance(rec, RawRecord) and rec.text.startswith("#")

    def test_空目录产出空(self, tmp_path):
        assert list(FilesConnector(root=tmp_path, source_type="wiki").fetch()) == []


# ---------------------------------------------------------------- raw store
class TestRawStore:
    def test_写入返回相对路径与sha256(self, tmp_path):
        store = RawStore(tmp_path)
        rel, digest = store.write("docs/a.md", "# 你好")
        assert rel == "docs/a.md"
        assert len(digest) == 64 and (tmp_path / rel).read_text(encoding="utf-8") == "# 你好"
        assert (tmp_path / "docs" / "a.md.sha256").read_text(encoding="utf-8") == digest

    def test_幂等_同内容重写为no_op(self, tmp_path):
        store = RawStore(tmp_path)
        store.write("a.md", "同内容")
        rel, _ = store.write("a.md", "同内容")
        assert rel == "a.md"

    def test_不可变_同key不同内容拒绝(self, tmp_path):
        store = RawStore(tmp_path)
        store.write("a.md", "旧")
        with pytest.raises(FileExistsError):
            store.write("a.md", "新内容")
