"""审计写入收口（README §9.1/§12.4，2026-10-23）：四端点各抄一份 INSERT 是漏账温床。

verdict 枚举由库约束兜底（audit_log_verdict_check: allow/deny/filtered/info）。
"""
from __future__ import annotations

import psycopg


def audit(env: dict, role: str, person: str | None, action: str,
          target: str, verdict: str = "info", reason: str = "") -> None:
    with psycopg.connect(env["ADKG_PG_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO audit_log (user_id, role, action, target, verdict, reason)"
                    " VALUES (%s,%s,%s,%s,%s,%s)",
                    (person, role, action, str(target)[:200], verdict, str(reason)[:200]))
