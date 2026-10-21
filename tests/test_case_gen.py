"""案例生成（case_gen + /ingest/case-*）：草稿抽取/对齐/幂等/仲裁 单元 + 端点校验。

离线：FakeGraph + 假 chat_json——对齐复用、新 id、Person 未对齐丢弃、
同文档幂等、主数据/同边仲裁不覆盖、commit 只写新实体。
端点：TestClient + dev 认证 + 真库（docs 列表 / 404 / 角色门 / 422 / 401）。
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


class FakeGraph:
    """记录式假图：entities[id] = {class,name,authority,prov_source_id}；edge_auth[(s,p,d)]=auth。"""

    def __init__(self, entities=None, edge_auth=None):
        self.entities = dict(entities or {})
        self.edge_auth = dict(edge_auth or {})
        self.upserted_entities: list = []
        self.upserted_relations: list = []

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _one(self, rec):
        class _R:
            def __init__(self, r):
                self._r = r

            def single(self):
                return self._r
        return _R(rec)

    def run(self, q, **kw):                                  # 只分支 case_gen 实际用到的形态
        if "n.authority" in q:
            e = self.entities.get(kw["id"])
            return self._one({"auth": e["authority"]} if e and e.get("authority") is not None else None)
        if "class:'Person'" in q:
            e = self.entities.get(kw["id"])
            ok = e and e["class"] == "Person"
            return self._one({"id": kw["id"], "name": e.get("name")} if ok else None)
        if "{id: $id}" in q:
            return self._one({"id": kw["id"]} if kw["id"] in self.entities else None)
        if "n.class=$cls AND (n.name=$name" in q:
            name, cls = kw["name"], kw["cls"]
            hits = [i for i, e in self.entities.items() if e["class"] == cls
                    and e.get("name") and (e["name"] == name or name in e["name"])]
            hits.sort(key=lambda i: len(self.entities[i]["name"]))
            return self._one({"id": hits[0]} if hits else None)
        if "prov_source_id=$doc" in q:
            hit = next((i for i, e in self.entities.items()
                        if e["class"] == "Case" and e.get("prov_source_id") == kw["doc"]), None)
            return self._one({"id": hit} if hit else None)
        if "STARTS WITH $p" in q:
            return _Rows([{"id": i} for i in self.entities if i.startswith(kw["p"])])
        if q.startswith("MATCH (a:Entity"):
            import re
            pred = re.search(r"\[r:(\w+)\]", q).group(1)
            auth = self.edge_auth.get((kw["s"], pred, kw["o"]))
            return self._one({"auth": auth} if auth is not None else None)
        raise AssertionError(f"FakeGraph 未覆盖的查询：{q[:60]}")

    def upsert_entities(self, ents):
        for e in ents:
            self.upserted_entities.append(e)
            self.entities[e.entity_id] = {"class": e.entity_class,
                                          "name": e.props.get("name"),
                                          "authority": e.provenance.authority,
                                          "prov_source_id": e.provenance.source_id}

    def upsert_relations(self, rels):
        self.upserted_relations.extend(rels)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def data(self):
        return self._rows


def _chat(payload):
    return lambda system, user: payload


_GOOD = {"brand": {"name": "途野露营", "props": {"category": "户外"}},
         "products": [{"name": "星链Pro", "props": {"category": "智能硬件"}},
                      {"name": "游星表"}],
         "case": {"name": "星链Pro 秋季投放案例", "stage": "live",
                  "props": {"bd_budget": 50000}},
         "persons": [{"name": "李昂", "org_role": "优化师"}, {"name": "张三", "org_role": "AE"}]}


def _graph():
    return FakeGraph(entities={
        "Brand:B05": {"class": "Brand", "name": "途野露营", "authority": 100},
        "Person:li": {"class": "Person", "name": "李昂", "authority": 100},
    })


def _draft_cls():
    from adkg.models import load_schema
    from adkg.pipeline.case_gen import build_draft
    return load_schema, build_draft


class TestBuildDraft:
    def test_对齐复用与新建id与关系构造(self):
        load_schema, build_draft = _draft_cls()
        d = build_draft("feishu:doc:X", "文档正文", _graph(), load_schema(), _chat(_GOOD), now=NOW)
        assert d["brand"]["id"] == "Brand:B05" and d["brand"]["existing"]      # L1 命中主数据
        assert [p["id"] for p in d["products"]] == ["Product:星链pro", "Product:游星表"]
        assert not any(p["existing"] for p in d["products"])
        assert d["case"]["id"] == "Case:C-2026-001" and not d["case"]["existing"]
        assert d["case"]["props"]["stage"] == "live"
        rels = {(r["predicate"], r["source"], r["target"]) for r in d["relations"]}
        assert ("for_brand", "Case:C-2026-001", "Brand:B05") in rels
        assert ("for_product", "Case:C-2026-001", "Product:星链pro") in rels
        assert ("has_product", "Brand:B05", "Product:游星表") in rels
        assert ("responsible_for", "Person:li", "Case:C-2026-001") in rels     # 对齐到既有 Person
        assert len(d["relations"]) == 6                        # 1 for_brand + 2 for_product + 2 has_product + 1 responsible
        assert not any("张三" in r["source"] for r in d["relations"])
        assert any("张三" in w and "未对齐" in w for w in d["warnings"])

    def test_单数product兼容(self):
        load_schema, build_draft = _draft_cls()
        old = {**_GOOD, "product": _GOOD["products"][0], "products": None}
        d = build_draft("feishu:doc:X", "正文", _graph(), load_schema(), _chat(old), now=NOW)
        assert [p["id"] for p in d["products"]] == ["Product:星链pro"]

    def test_stage非法回proposal(self):
        load_schema, build_draft = _draft_cls()
        bad = {**_GOOD, "case": {**_GOOD["case"], "stage": "上线中"}}
        d = build_draft("feishu:doc:X", "正文", _graph(), load_schema(), _chat(bad), now=NOW)
        assert d["case"]["props"]["stage"] == "proposal"
        assert any("proposal" in w for w in d["warnings"])

    def test_同文档幂等复用CaseId(self):
        load_schema, build_draft = _draft_cls()
        g = _graph()
        g.entities["Case:C-2026-001"] = {"class": "Case", "name": "旧案例",
                                         "authority": 60, "prov_source_id": "feishu:doc:X"}
        d = build_draft("feishu:doc:X", "正文", g, load_schema(), _chat(_GOOD), now=NOW)
        assert d["case"]["existing"] and d["case"]["id"] == "Case:C-2026-001"
        assert d["case"]["same_doc"]

    def test_案例序号递增(self):
        load_schema, build_draft = _draft_cls()
        g = _graph()
        g.entities["Case:C-2026-007"] = {"class": "Case", "name": "x", "authority": 100}
        d = build_draft("feishu:doc:Y", "正文", g, load_schema(), _chat(_GOOD), now=NOW)
        assert d["case"]["id"] == "Case:C-2026-008"


class TestCommitDraft:
    def _commit(self):
        from adkg.models import load_schema
        from adkg.pipeline.case_gen import commit_draft
        return load_schema(), commit_draft

    def test_全链草稿入图只写新实体(self):
        load_schema, build_draft = _draft_cls()
        schema, commit = self._commit()
        g = _graph()
        d = build_draft("feishu:doc:X", "正文", g, load_schema(), _chat(_GOOD), now=NOW)
        out = commit(d, g, schema, now=NOW)
        assert out["case_id"] == "Case:C-2026-001" and out["entities"] == 3     # brand 已存在不写
        assert out["relations"] == 6
        assert {e.entity_id for e in g.upserted_entities} == {
            "Case:C-2026-001", "Product:星链pro", "Product:游星表"}
        assert all(e.provenance.authority == 60 for e in g.upserted_entities)
        assert all(e.provenance.source_id == "feishu:doc:X" for e in g.upserted_entities)
        assert {(r.source, r.predicate, r.target) for r in g.upserted_relations} == {
            ("Case:C-2026-001", "for_brand", "Brand:B05"),
            ("Case:C-2026-001", "for_product", "Product:星链pro"),
            ("Case:C-2026-001", "for_product", "Product:游星表"),
            ("Brand:B05", "has_product", "Product:星链pro"),
            ("Brand:B05", "has_product", "Product:游星表"),
            ("Person:li", "responsible_for", "Case:C-2026-001")}

    def test_主数据id冲突不覆盖且边一并拦下(self):
        load_schema, build_draft = _draft_cls()
        schema, commit = self._commit()
        g = _graph()
        d = build_draft("feishu:doc:X", "正文", g, load_schema(), _chat(_GOOD), now=NOW)
        d["brand"]["existing"] = False                          # 伪装新实体，id 撞主数据（auth 100）
        out = commit(d, g, schema, now=NOW)
        assert any("不覆盖" in w for w in out["warnings"])
        assert not any(e.entity_id == "Brand:B05" for e in g.upserted_entities)
        assert all("B05" not in r.target + r.source for r in g.upserted_relations)  # 被拦端点的边不写

    def test_同边高authority不覆盖(self):
        load_schema, build_draft = _draft_cls()
        schema, commit = self._commit()
        g = _graph()
        g.edge_auth[("Brand:B05", "has_product", "Product:星链pro")] = 100
        d = build_draft("feishu:doc:X", "正文", g, load_schema(), _chat(_GOOD), now=NOW)
        out = commit(d, g, schema, now=NOW)
        assert out["relations"] == 5
        assert any("同边" in w for w in out["warnings"])

    def test_重复commit幂等(self):
        load_schema, build_draft = _draft_cls()
        schema, commit = self._commit()
        g = _graph()
        d = build_draft("feishu:doc:X", "正文", g, load_schema(), _chat(_GOOD), now=NOW)
        commit(d, g, schema, now=NOW)
        n_rels = len(g.upserted_relations)
        out2 = commit(d, g, schema, now=NOW)                    # 二次：auth 60 不高于 60 → MERGE 幂等重写
        assert out2["entities"] == 3 and out2["relations"] == 6
        assert len(g.upserted_relations) == n_rels * 2
        assert not any("不覆盖" in w for w in out2["warnings"])

    def test_无case仅品牌商品可入图(self):
        # 极光场景：商品知识文档无投放内容 → 只入 Brand + Products + has_product
        load_schema, build_draft = _draft_cls()
        schema, commit = self._commit()
        g = _graph()
        d = build_draft("feishu:doc:X", "正文", g, load_schema(), _chat(_GOOD), now=NOW)
        d["case"] = None
        d["relations"] = [r for r in d["relations"] if r["predicate"] == "has_product"]
        out = commit(d, g, schema, now=NOW)
        assert out["case_id"] == "" and out["entities"] == 2 and out["relations"] == 2

    def test_全空草稿拒绝(self):
        schema, commit = self._commit()
        with pytest.raises(ValueError):
            commit({"doc_id": "feishu:doc:X", "relations": []}, FakeGraph(),
                   schema, now=NOW)


@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestIngestEndpoints:
    def _client(self, **overrides):
        from fastapi.testclient import TestClient

        from adkg.api.main import create_app
        env = {k: v for k, v in os.environ.items() if k.startswith(("ADKG_", "NEO4J"))}
        env.update(overrides)
        return TestClient(create_app(env))

    def test_docs列表含飞书文档(self):
        r = self._client().get("/ingest/docs")
        assert r.status_code == 200
        docs = r.json()["docs"]
        assert docs and all(d["doc_id"].startswith("feishu:") for d in docs)
        assert all(d["title"] and d["chunks"] > 0 for d in docs)

    def test_docs搜索过滤(self):
        docs = self._client().get("/ingest/docs", params={"q": "不存在的词xyz"}).json()["docs"]
        assert docs == []

    def test_draft未知文档404(self):
        r = self._client().post("/ingest/case-draft", json={
            "doc_id": "feishu:doc:nope", "role": "management", "user": "Person:chen"})
        assert r.status_code == 404

    def test_draft角色门403(self):
        r = self._client().post("/ingest/case-draft", json={
            "doc_id": "feishu:doc:x", "role": "client", "user": "Person:client_a"})
        assert r.status_code == 403

    def test_commit缺draft422(self):
        r = self._client().post("/ingest/case-commit", json={
            "role": "management", "user": "Person:chen"})
        assert r.status_code == 422

    def test_未认证401(self):
        r = self._client(ADKG_DEV_AUTH="on").get("/ingest/docs")
        assert r.status_code == 401
