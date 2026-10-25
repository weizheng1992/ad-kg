"""平台事实 ETL（§四 pipeline/etl_facts.py）：CSV → 映射翻译 → entity_alias 换算
→ 图侧维度物化 → 事实表；对不上的标 unmatched 进 review_queue（§12.5）。

映射真源在 ontology/mappings/*.yaml；中文表头在映射层翻译（xiaohongshu.yaml）。
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import psycopg

from adkg.store import pg_pool
import yaml

UNIFIED_COLUMNS = {"date", "campaign_local_id", "creative_local_id",
                   "cost", "impressions", "clicks", "conversions"}


@dataclass
class EtlStats:
    rows: int = 0
    matched: int = 0
    unmatched: int = 0


def load_mapping(path: Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    missing = UNIFIED_COLUMNS - set(data["columns"].values())
    if missing:
        raise ValueError(f"{path} 映射缺 unified 列：{missing}")
    return data


def parse_rows(mapping: dict, rows: list[dict]) -> list[dict]:
    """纯函数：平台行 → unified 列名行（中文表头在此翻译）。"""
    cols = mapping["columns"]
    out = []
    for i, row in enumerate(rows):
        missing = [k for k in cols if k not in row]
        if missing:
            raise ValueError(f"第 {i + 2} 行缺列 {missing}")
        out.append({unified: row[platform] for platform, unified in cols.items()})
    return out


def etl_csv(pg_dsn: str, graph, mapping_path: Path, csv_path: Path,
            fetched_at: str = "2026-10-19T00:00:00+08:00") -> EtlStats:
    mapping = load_mapping(mapping_path)
    platform = mapping["source"]
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = parse_rows(mapping, list(csv.DictReader(f)))
    stats = EtlStats(rows=len(rows))

    with pg_pool.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT source, external_id, internal_id FROM entity_alias")
        aliases = {(s, e): i for s, e, i in cur.fetchall()}
        alias_source = mapping["alias_source"]

        # 本体 ID 换算（L1：entity_alias 直接命中，§7.4）
        for r in rows:
            r["creative_id"] = aliases.get((alias_source, r["creative_local_id"]))
        matched_ids = sorted({r["creative_id"] for r in rows if r["creative_id"]})
        contexts = graph.creative_contexts(matched_ids) if matched_ids else {}

        stats.matched = sum(1 for r in rows if r["creative_id"])
        stats.unmatched = stats.rows - stats.matched

        cur.execute(
            "INSERT INTO provenance (source_type, source_id, fetched_at, authority, version)"
            " VALUES ('platform_api', %s, %s, 80, %s) RETURNING id",
            (f"{platform}:seed:{csv_path.name}", fetched_at,
             csv_path.stat().st_mtime_ns // 10 ** 8))          # 版本=内容指纹近似
        prov_id = cur.fetchone()[0]

        cur.executemany(
            f"INSERT INTO {mapping['table']}"
            " (date, campaign_local_id, creative_local_id, creative_id,"
            "  campaign_id, case_id, brand_id, product_id, cost, impressions, clicks, conversions,"
            "  provenance_id)"
            " VALUES (%(date)s, %(campaign_local_id)s, %(creative_local_id)s,"
            " %(creative_id)s, %(campaign_id)s, %(case_id)s, %(brand_id)s, %(product_id)s,"
            " %(cost)s, %(impressions)s, %(clicks)s, %(conversions)s, %(_prov)s)"
            " ON CONFLICT (date, campaign_local_id, creative_local_id) DO UPDATE SET"
            " creative_id = EXCLUDED.creative_id, campaign_id = EXCLUDED.campaign_id,"
            " case_id = EXCLUDED.case_id, brand_id = EXCLUDED.brand_id,"
            " product_id = EXCLUDED.product_id,"
            " cost = EXCLUDED.cost, impressions = EXCLUDED.impressions,"
            " clicks = EXCLUDED.clicks, conversions = EXCLUDED.conversions",
            [{**r, "campaign_id": contexts.get(r["creative_id"], {}).get("campaign_id"),
              "case_id": contexts.get(r["creative_id"], {}).get("case_id"),
              "brand_id": contexts.get(r["creative_id"], {}).get("brand_id"),
              "product_id": contexts.get(r["creative_id"], {}).get("product_id"),
              "_prov": prov_id} for r in rows])

        if stats.unmatched:
            cur.execute("INSERT INTO review_queue (kind, payload) VALUES ('unmatched', %s)",
                        (json.dumps({"platform": platform, "file": csv_path.name,
                                     "unmatched_rows": stats.unmatched,
                                     "hint": "平台 local_id 未命中 entity_alias"},
                                    ensure_ascii=False),))
    return stats
