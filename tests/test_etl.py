"""mappings 资产 + etl_facts 测试：映射纯函数离线，端到端打真库（不在线跳过）。"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
from adkg.pipeline.etl_facts import UNIFIED_COLUMNS, load_mapping, parse_rows

DOUYIN = ROOT / "ontology/mappings/douyin.yaml"
XHS = ROOT / "ontology/mappings/xiaohongshu.yaml"


class TestMappings资产:
    def test_两平台映射齐备且目标一致(self):
        d, x = load_mapping(DOUYIN), load_mapping(XHS)
        assert set(d["columns"].values()) == UNIFIED_COLUMNS
        assert set(x["columns"].values()) == UNIFIED_COLUMNS
        assert d["source"] != x["source"] and d["table"] != x["table"]

    def test_xhs用中文表头(self):
        cols = load_mapping(XHS)["columns"]
        assert set(cols) == {"日期", "计划ID", "素材ID", "消耗", "曝光量", "点击量", "转化量"}

    def test_指标引用是Metric节点(self):
        for m in (load_mapping(DOUYIN), load_mapping(XHS)):
            assert m["metrics"] and all(i.startswith("Metric:") for i in m["metrics"])


class TestParseRows:
    def test_中文表头翻译成unified列(self):
        m = load_mapping(XHS)
        rows = parse_rows(m, [{"日期": "2025-06-15", "计划ID": "xhs_c1", "素材ID": "xhs_77",
                               "消耗": "120.0", "曝光量": "20000", "点击量": "100", "转化量": "2"}])
        assert rows[0]["creative_local_id"] == "xhs_77"
        assert rows[0]["cost"] == "120.0"

    def test_缺列报错(self):
        m = load_mapping(DOUYIN)
        with pytest.raises(ValueError, match="缺列"):
            parse_rows(m, [{"date": "2025-01-01"}])          # 其余列全缺


# ---------------------------------------------------------------- 端到端（真库）
def _db_up() -> bool:
    try:
        import os

        import psycopg
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        with psycopg.connect(os.environ["ADKG_PG_DSN"], connect_timeout=3):
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_up(), reason="Postgres 不在线")
class TestEtl端到端:
    def test_双平台锚点灌入与维度物化(self, tmp_path):
        """dy_889 / xhs_77 双别名都指向 creative_992（load_seed 已写）——
        同一素材两平台进 unified_metrics，维度列从图侧物化。"""
        import os

        import psycopg
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from adkg.pipeline.etl_facts import etl_csv
        from adkg.store.graph import GraphStore

        pg = os.environ["ADKG_PG_DSN"]
        graph = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                           os.environ["ADKG_NEO4J_PASSWORD"])
        d_csv = tmp_path / "d.csv"
        d_csv.write_text(
            "date,campaign_local_id,creative_local_id,cost,impressions,clicks,conversions\n"
            "2025-06-15,dy_c1,dy_889,86.0,10000,90,1\n", encoding="utf-8")
        x_csv = tmp_path / "x.csv"
        x_csv.write_text(
            "日期,计划ID,素材ID,消耗,曝光量,点击量,转化量\n"
            "2025-06-15,xhs_c1,xhs_77,120.0,20000,100,2\n", encoding="utf-8")

        with psycopg.connect(pg) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM creative_metrics_daily_douyin"
                        " WHERE date='2025-06-15' AND campaign_local_id='dy_c1'")
            cur.execute("DELETE FROM creative_metrics_daily_xhs"
                        " WHERE date='2025-06-15' AND campaign_local_id='xhs_c1'")

        s1 = etl_csv(pg, graph, DOUYIN, d_csv)
        s2 = etl_csv(pg, graph, XHS, x_csv)
        assert (s1.matched, s1.unmatched) == (1, 0)
        assert (s2.matched, s2.unmatched) == (1, 0)

        with psycopg.connect(pg) as conn, conn.cursor() as cur:
            cur.execute("SELECT platform, cost, creative_id, campaign_id, case_id, brand_id"
                        " FROM unified_metrics WHERE date='2025-06-15' ORDER BY platform")
            rows = cur.fetchall()
        by = {r[0]: r for r in rows}
        for platform in ("douyin", "xhs"):
            r = by[platform]
            assert r[2] == "Creative:creative_992"           # 别名换算成功
            assert r[3:] == ("Campaign:C-2025-005-cp1", "Case:C-2025-005", "Brand:B06")
        assert by["douyin"][1] == 86 and by["xhs"][1] == 120  # 同口径可比（画面 3）
        graph.close()
