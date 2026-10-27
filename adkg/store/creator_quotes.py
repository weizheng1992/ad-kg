"""达人报价快照写入（spec §15，2026-10-27 缺陷⑨收敛）。

原住在 api/routes/creators.py，被 admin.py（冲突采纳留痕）跨 route import——
写路径归 store（检索层只读），route 只留 HTTP 壳；读侧（详情报价历史查询）
仍在 creators.py，量小未随迁。
"""
from __future__ import annotations

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
