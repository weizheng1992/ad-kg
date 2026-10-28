"""达人报价快照读写（spec §15，2026-10-27 缺陷⑨收敛；2026-10-28 读侧随迁）。

原住在 api/routes/creators.py，被 admin.py（冲突采纳留痕）跨 route import——
读写两路都归 store，route 只留 HTTP 壳。
"""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from adkg.store import pg_pool


def record_quote_history(env: dict, creator_id: str, quote_20s, source_type: str,
                         source_id: str) -> None:
    """报价快照（spec §15）：三条入库口共用——历史即事实，只追加（同日同源
    幂等跳过）。"""
    if not quote_20s:
        return
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO creator_quote_history (creator_id, date, quote_20s, source_type,"
            " source_id) VALUES (%s, current_date, %s, %s, %s)"
            " ON CONFLICT (creator_id, date, source_type) DO NOTHING",
            (creator_id, int(quote_20s), source_type, source_id))


def quote_history(env: dict, creator_id: str) -> list[dict]:
    """报价历史（spec §15）：种子轨迹 + 三条入库口的运行时快照；表缺席等 PG 错
    回空（2026-10-28 自 creators.py 下沉）。"""
    try:
        with pg_pool.connect(env["ADKG_PG_DSN"], row_factory=dict_row) as conn, \
                conn.cursor() as cur:
            cur.execute("SELECT date::text AS date, quote_20s, source_type"
                        " FROM creator_quote_history WHERE creator_id = %(id)s"
                        " ORDER BY date", {"id": creator_id})
            return [dict(r) for r in cur.fetchall()]
    except psycopg.Error:
        return []
