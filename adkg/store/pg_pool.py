"""PG 连接池（2026-10-25 三件套之一）：API 层共享池替代每请求临时连接。

用法与 psycopg.connect 同形（with ... as conn，干净退出提交/异常回滚）：
    from adkg.store import pg_pool
    with pg_pool.connect(dsn, options="-c statement_timeout=3000") as conn: ...

池按 (dsn, options, row_factory) 键缓存；min 1 / max 8——FastAPI 线程池默认
40 线程也打不满 PG max_connections=100（此前 agent ReAct 嵌套 /ask 一次可叠
数个临时连接，裸奔有撞顶风险）。脚本（load_seed 等批任务）仍走 psycopg 直连。
"""
from __future__ import annotations

from typing import Any

import atexit

from psycopg_pool import ConnectionPool

_POOLS: dict[tuple, ConnectionPool] = {}


def _close_all() -> None:                                  # 进程退出收口（免终结期线程噪音）
    for p in _POOLS.values():
        try:
            p.close()
        except Exception:
            pass


atexit.register(_close_all)
_MAX_PER_KEY = 8      # 每（DSN×选项×行工厂）一键一池；键种类 <6，总连接上限 ~48 < 100


def connect(dsn: str, *, options: str | None = None, row_factory: Any = None):
    """取池化连接（上下文管理器，语义同 psycopg.connect）。"""
    key = (dsn, options, row_factory)
    pool = _POOLS.get(key)
    if pool is None:
        kwargs: dict[str, Any] = {"min_size": 1, "max_size": _MAX_PER_KEY,
                                  "timeout": 10, "max_idle": 300, "open": True}
        if options:
            kwargs["kwargs"] = {"options": options}
        if row_factory is not None:
            kwargs["kwargs"] = {**kwargs.get("kwargs", {}), "row_factory": row_factory}
        pool = ConnectionPool(dsn, name=f"adkg-{len(_POOLS)}", **kwargs)
        _POOLS[key] = pool
    return pool.connection()
