"""导入种子数据（§四 scripts/load_seed.py）：点亮图里第一张关系网。

- 主数据（brands / people / cases_campaigns / guidelines）→ 图，system_of_record
- 断言（violates / complies_with）→ 图，conversation 低 authority
- 文档（cases + guidelines md）→ run_docs 流水线：raw 落盘 + chunk 入 PG
- 双平台同素材锚点写 entity_alias（§12.5）
- Metric 口径节点手工定义（§六：语义层手工定义）

幂等：图侧 MERGE、provenance 按 source_id 查重、chunk upsert，重跑无新增。
用法：uv run python scripts/load_seed.py
"""
from __future__ import annotations

import csv
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import psycopg
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from adkg.connectors.files import FilesConnector          # noqa: E402
from adkg.models import Entity, Provenance, Relation      # noqa: E402
from adkg.pipeline.run import run_docs                    # noqa: E402
from adkg.store.graph import GraphStore                   # noqa: E402
from adkg.store.provenance import TraceStore              # noqa: E402
from adkg.store.raw import RawStore                       # noqa: E402
from adkg.store.vector import VectorStore                 # noqa: E402

SEED = ROOT / "data" / "seed"
RAW = ROOT / "data" / "raw"                      # 文档真源（gen_seed 直写）
FETCHED_AT = "2026-10-19T00:00:00+08:00"                 # 种子固定时间，保证可重跑

METRICS = [  # §六：Metric 口径定义（语义层手工定义）
    ("Metric:ctr", "clicks / impressions", "creative×day", "不跨平台直接对比", ""),
    ("Metric:cvr", "conversions / clicks", "creative×day", "不跨平台直接对比", ""),
    ("Metric:cpa", "cost / conversions", "creative×day", "两平台口径统一后可比", ""),
    ("Metric:cpm", "cost / impressions * 1000", "creative×day", "", ""),
    ("Metric:roi", "revenue / cost", "case×month", "需回传收入数据", ""),
    ("Metric:purchase_rate", "orders / clicks", "product×day",
     "交易口径——与投放侧 cvr 分列（orders 需与投放 clicks 按 product×day join）", ""),
]


def _rows(rel: str) -> list[dict]:
    with open(SEED / rel, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    pg = os.environ["ADKG_PG_DSN"]
    neo = os.environ
    graph = GraphStore(neo["ADKG_NEO4J_URI"], neo["ADKG_NEO4J_USER"], neo["ADKG_NEO4J_PASSWORD"])
    trace = TraceStore(pg)
    entities: list[Entity] = []
    relations: list[Relation] = []

    def prov(source_id: str, stype: str = "system_of_record", confidence: float | None = None):
        return Provenance(source_type=stype, source_id=source_id,
                          fetched_at=FETCHED_AT, confidence=confidence)

    # ── 主数据：Brand / Product + has_product ─────────────────────────
    p_brand = prov("seed:brands_products.csv")
    for r in _rows("brands_products.csv"):
        entities += [
            Entity(entity_class="Brand", entity_id=r["brand_id"],
                   props={"name": r["brand_name"], "category": r["category"]}, provenance=p_brand),
            Entity(entity_class="Product", entity_id=r["product_id"],
                   props={**{"name": r["app_name"], "platform": r["platform"],
                             "target_age": r["target_age"]},
                          **({k: r[k] for k in ("spec", "detail", "price") if r.get(k)})},
                   provenance=p_brand)]
        relations.append(Relation(source=r["brand_id"], predicate="has_product",
                                  target=r["product_id"], provenance=p_brand))

    # ── 人员：Person + belongs_to_brand / external_for / responsible_for ──
    p_people = prov("seed:org_people.csv")
    for r in _rows("org_people.csv"):
        entities.append(Entity(entity_class="Person", entity_id=r["person_id"],
                               props={"name": r["name"], "org_role": r["org_role"]},
                               provenance=p_people))
        predicate = "external_for" if r["is_external"] == "1" else "belongs_to_brand"
        relations.append(Relation(source=r["person_id"], predicate=predicate,
                                  target=r["brand_id"], provenance=p_people))
        if r["case_id"]:
            relations.append(Relation(source=r["person_id"], predicate="responsible_for",
                                      target=r["case_id"], provenance=p_people))

    # ── 定向人群包：Audience 实体 + Campaign targets 推导边（§六 targets N:M）──
    p_aud = prov("seed:audiences.csv")
    aud_by_brand: dict[str, list[str]] = {}
    for r in _rows("audiences.csv"):
        entities.append(Entity(entity_class="Audience", entity_id=r["audience_id"],
                               props={"name": r["name"],
                                      "targeting_desc": r["targeting_desc"]},
                               provenance=p_aud))
        aud_by_brand.setdefault(r["brand_id"], []).append(r["audience_id"])

    # ── 案例-计划-素材主数据 ─────────────────────────────────────────
    p_cc = prov("seed:cases_campaigns.csv")
    seen_case, seen_camp = set(), set()
    camp_brand: dict[str, str] = {}                        # campaign → brand（targets 推导用）
    for r in _rows("cases_campaigns.csv"):
        if r["case_id"] not in seen_case:
            seen_case.add(r["case_id"])
            entities.append(Entity(entity_class="Case", entity_id=r["case_id"],
                                   props={"name": r["case_name"], "stage": r["stage"],
                                          "bd_budget": r["bd_budget"],
                                          "settlement_status": r["settlement_status"],
                                          **{k: r[k] for k in ("lost_reason", "terminate_reason",
                                                               "gross_margin")
                                             if r.get(k)}},
                                   provenance=p_cc))
            relations += [
                Relation(source=r["case_id"], predicate="for_brand",
                         target=r["brand_id"], provenance=p_cc),
                Relation(source=r["case_id"], predicate="for_product",
                         target=r["product_id"], provenance=p_cc)]
        if r["campaign_id"] not in seen_camp:
            seen_camp.add(r["campaign_id"])
            camp_brand[r["campaign_id"]] = r["brand_id"]
            entities.append(Entity(entity_class="Campaign", entity_id=r["campaign_id"],
                                   props={"name": r["campaign_name"],
                                          "status": r["campaign_status"],
                                          "daily_budget": r["daily_budget"]}, provenance=p_cc))
            relations += [
                Relation(source=r["campaign_id"], predicate="belongs_to",
                         target=r["case_id"], provenance=p_cc),
                Relation(source=r["campaign_id"], predicate="in_channel",
                         target=f"Channel:{r['channel']}", provenance=p_cc)]
        entities.append(Entity(entity_class="Creative", entity_id=r["creative_id"],
                               props={"name": r["creative_title"],
                                      "is_aigc": r["is_aigc"] == "1"}, provenance=p_cc))
        relations += [
            Relation(source=r["campaign_id"], predicate="uses",
                     target=r["creative_id"], provenance=p_cc),
            Relation(source=r["creative_id"], predicate="links_to",
                     target=f"LandingPage:lp-{r['campaign_id'].split('-cp')[0][-3:]}",
                     provenance=p_cc)]

    # 计划 → 定向人群包（targets N:M）：本品牌的计划定向本品牌的全部人群包
    for camp_id, bid in sorted(camp_brand.items()):
        for aud_id in aud_by_brand.get(bid, []):
            relations.append(Relation(source=camp_id, predicate="targets",
                                      target=aud_id, provenance=p_aud))

    # 渠道与落地页节点
    for ch in ("信息流", "搜索", "开屏"):
        entities.append(Entity(entity_class="Channel", entity_id=f"Channel:{ch}",
                               props={"slot_type": ch}, provenance=p_cc))
    lp_ids = {r.target for r in relations if r.predicate == "links_to"}
    entities += [Entity(entity_class="LandingPage", entity_id=i, props={},
                        provenance=p_cc) for i in sorted(lp_ids)]

    # 衍生链（§六 derived_from）：AIGC 素材沿用同案例爆款
    relations.append(Relation(source="Creative:creative_992", predicate="derived_from",
                              target="Creative:C-2025-005-cp1-cr1", provenance=p_cc))

    # ── 达人主数据（spec §3）：Creator + collabs_with / promotes ─────────
    p_cr = prov("seed:creators.csv")
    for r in _rows("creators.csv"):
        entities.append(Entity(entity_class="Creator", entity_id=r["creator_id"],
                               props={"name": r["name"], "platform": r["platform"],
                                      "niches": r["niches"],
                                      "followers": int(r["followers"]),
                                      "quote_20s": int(r["quote_20s"]),
                                      "quote_image": int(r["quote_image"]),
                                      "gmv_30d": int(r["gmv_30d"]),
                                      "city": r["city"], "rating": float(r["rating"])},
                               provenance=p_cr))
    for r in _rows("case_creators.csv"):
        relations.append(Relation(source=r["case_id"], predicate="collabs_with",
                                  target=r["creator_id"], provenance=p_cr))
    for r in _rows("creator_products.csv"):
        relations.append(Relation(source=r["creator_id"], predicate="promotes",
                                  target=r["product_id"], provenance=p_cr))
    # ── 报价历史种子（spec §15）：只追加表，重灌幂等（同日同源去重）────────
    with psycopg.connect(pg) as conn, conn.cursor() as cur:
        hrows = _rows("quote_history.csv")
        cur.executemany(
            "INSERT INTO creator_quote_history (creator_id, date, quote_20s, source_type,"
            " source_id) VALUES (%(creator_id)s, %(date)s, %(quote_20s)s,"
            " 'system_of_record', 'seed:quote_history.csv')"
            " ON CONFLICT (creator_id, date, source_type) DO NOTHING",
            [{"creator_id": r["creator_id"], "date": r["date"],
              "quote_20s": int(r["quote_20s"])} for r in hrows])

    # ── 扩容批次（2026-10-24）：新案例负责人——org_people 逐字节不动，单独立表 ──
    if (SEED / "case_persons.csv").exists():
        for r in _rows("case_persons.csv"):
            relations.append(Relation(source=r["person_id"], predicate="responsible_for",
                                      target=r["case_id"], provenance=p_people))

    # ── 规范（frontmatter 带机判阈值）────────────────────────────────
    p_gd = prov("seed:guidelines")
    for path in sorted(RAW.glob("G-*.md")):            # 文档真源在 raw（gen_seed 直写）
        text = path.read_text(encoding="utf-8")
        m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
        fm = yaml.safe_load(m.group(1)) if m else {}
        props = {"guideline_type": fm.get("guideline_type")}
        if fm.get("max_duration_s"):
            props["max_duration_s"] = fm["max_duration_s"]
        entities.append(Entity(entity_class="Guideline", entity_id=fm["id"],
                               props=props, provenance=p_gd))

    # ── 断言（AIGC 比对结果回写样例，§9.4）───────────────────────────
    p_as = prov("seed:assertions.csv", stype="conversation")
    for r in _rows("assertions.csv"):
        relations.append(Relation(source=r["subject"], predicate=r["predicate"],
                                  target=r["object"], provenance=p_as,
                                  confidence=float(r["confidence"])))

    # ── Metric 口径节点 ──────────────────────────────────────────────
    p_m = prov("ontology:metric")
    for mid, expr, grain, scope, note in METRICS:
        entities.append(Entity(entity_class="Metric", entity_id=mid,
                               props={"expr": expr, "grain": grain,
                                      "valid_scope": scope, "note": note}, provenance=p_m))

    # ── 入图（MERGE 幂等），随后对账 ──────────────────────────────────
    graph.upsert_entities(entities)
    graph.upsert_relations(relations)
    print(f"图：{len(entities)} 节点 / {len(relations)} 关系已 MERGE")

    # ── 双平台同素材锚点 → entity_alias（§12.5）──────────────────────
    with psycopg.connect(pg) as conn, conn.cursor() as cur:
        for source, ext in (("douyin", "dy_889"), ("xhs", "xhs_77")):
            cur.execute(
                "INSERT INTO entity_alias (source, external_id, internal_id)"
                " VALUES (%s,%s,'Creative:creative_992')"
                " ON CONFLICT (source, external_id) DO NOTHING", (source, ext))
        # 部分平台回执 ID 与本体对齐（其余留作 unmatched 人审演示，§7.4）
        cc = _rows("cases_campaigns.csv")
        douyin_first8 = [r["creative_id"] for r in cc if r["platform"] == "douyin"][:8]
        xhs_first8 = [r["creative_id"] for r in cc if r["platform"] == "xhs"][:8]
        for i, cid in enumerate(douyin_first8):
            cur.execute("INSERT INTO entity_alias (source, external_id, internal_id)"
                        " VALUES ('douyin', %s, %s) ON CONFLICT DO NOTHING",
                        (f"dy_cr{i}", cid))
        # 负责人案例（C-2025-006，优化师 demo 主场景）的创意也纳入对齐——
        # 否则其案例级谓词在事实表无 matched 行（评测 R2 抓出的数据覆盖缺口）
        for i, cid in enumerate([r["creative_id"] for r in cc
                                 if r["case_id"] == "Case:C-2025-006"
                                 and r["platform"] == "douyin"][:2]):
            cur.execute("INSERT INTO entity_alias (source, external_id, internal_id)"
                        " VALUES ('douyin', %s, %s) ON CONFLICT DO NOTHING",
                        (f"dy_cr{8 + i}", cid))
        for i, cid in enumerate(xhs_first8):
            cur.execute("INSERT INTO entity_alias (source, external_id, internal_id)"
                        " VALUES ('xhs', %s, %s) ON CONFLICT DO NOTHING",
                        (f"xhs_cr{i}", cid))
        # 扩容批次对齐（2026-10-24）：新案例素材 ↔ dy_cr100+ / xhs_cr100+ 段（各 80，
        # 与 gen_seed 扩容事实一一对应——新案例全部进 unified_metrics 口径面）
        for i, cid in enumerate([r["creative_id"] for r in cc if r["platform"] == "douyin"
                                 and int(r["case_id"].rsplit("-", 1)[1]) > 20][:80]):
            cur.execute("INSERT INTO entity_alias (source, external_id, internal_id)"
                        " VALUES ('douyin', %s, %s) ON CONFLICT DO NOTHING",
                        (f"dy_cr{100 + i}", cid))
        for i, cid in enumerate([r["creative_id"] for r in cc if r["platform"] == "xhs"
                                 and int(r["case_id"].rsplit("-", 1)[1]) > 20][:80]):
            cur.execute("INSERT INTO entity_alias (source, external_id, internal_id)"
                        " VALUES ('xhs', %s, %s) ON CONFLICT DO NOTHING",
                        (f"xhs_cr{100 + i}", cid))
    print("entity_alias：双平台锚点 + 16 条平台回执对齐 + 扩容 160 条（其余 unmatched 留给人审演示）")

    # ── 文档路：cases + guidelines 走流水线（raw + chunk 入 PG，嵌入本地当场生成）──
    from adkg.llm import LLMClient
    for pat, stype in (("C-*.md", "wiki"), ("G-*.md", "official_doc")):
        stats = run_docs(FilesConnector(RAW, source_type=stype, pattern=pat),
                         RawStore(ROOT / "data" / "raw"),
                         VectorStore(pg), graph, trace,
                         extractor=None, embed_fn=LLMClient().embed)
        print(f"文档路 {pat}：{stats.docs} 篇 → {stats.chunks} 块（抽取跳过——§7.2 降级；嵌入本地 bge）")
    # chunk 权限元数据回填（§八 向量层：class / case_id 供检索按角色过滤）
    with psycopg.connect(pg) as conn, conn.cursor() as cur:
        cur.execute("UPDATE chunks SET entity_class='Guideline'"
                    " WHERE doc_id LIKE 'file:G-%' OR doc_id LIKE 'feishu:doc:%'")
        cur.execute("UPDATE chunks SET entity_class='Case',"
                    " case_id='Case:'||replace(replace(doc_id,'file:',''),'.md','')"
                    " WHERE doc_id LIKE 'file:C-2025-%'")

    counts = graph.counts()
    print(f"对账：{counts}")

    # ── 数据路（Phase 3）：两平台 CSV → 映射 → 别名换算 → 事实表 ──────
    from adkg.pipeline.etl_facts import etl_csv
    for mapping, csvf in (("douyin", "creative_metrics_daily_douyin.csv"),
                          ("xiaohongshu", "creative_metrics_daily_xhs.csv")):
        st = etl_csv(pg, graph, ROOT / "ontology" / "mappings" / f"{mapping}.yaml",
                     SEED / csvf)
        print(f"数据路 {mapping}：{st.rows} 行（matched {st.matched} / unmatched {st.unmatched}）")

    # ── 交易路：SKU 订单 → product_orders_daily（§六 交易口径分列）─────
    with psycopg.connect(pg) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM product_orders_daily")
        cur.execute(
            "INSERT INTO provenance (source_type, source_id, fetched_at, authority, version)"
            " VALUES ('platform_api', 'ecommerce:seed:product_orders_daily.csv', %s, 80, %s)"
            " RETURNING id", (FETCHED_AT, 1))
        prov_id = cur.fetchone()[0]
        orows = _rows("product_orders_daily.csv")
        cur.executemany(
            "INSERT INTO product_orders_daily (date, product_id, orders, gmv, provenance_id)"
            " VALUES (%(date)s, %(product_id)s, %(orders)s, %(gmv)s, %(prov)s)"
            " ON CONFLICT (date, product_id) DO UPDATE SET orders = EXCLUDED.orders,"
            " gmv = EXCLUDED.gmv",
            [{**r, "orders": int(r["orders"]), "gmv": float(r["gmv"]), "prov": prov_id}
             for r in orows])
    print(f"交易路 product_orders_daily：{len(orows)} 行")
    graph.close()


if __name__ == "__main__":
    main()
