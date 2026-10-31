"""审计写入收口（README §9.1/§12.4，2026-10-23）：INSERT 只此一份——端点各抄一份
INSERT 是漏账温床。

verdict 枚举由库约束兜底（audit_log_verdict_check: allow/deny/filtered/info）。
agent_id（双身份 §9.1，/actions/check）与外部 conn（/ingest/case-commit 与别名注册
同事务落账，2026-10-24 收敛）走可选参数；返回 audit_id（RETURNING id，裁决回执引用）。
"""
from __future__ import annotations


from adkg.store import pg_pool


def audit(env: dict, role: str, person: str | None, action: str,
          target: str, verdict: str = "info", reason: str = "", *,
          agent_id: str | None = None, conn=None) -> str:
    cols = ["user_id", "role", "action", "target", "verdict", "reason"]
    vals: list = [person, role, action, str(target)[:200], verdict, str(reason)[:500]]
    if agent_id is not None:
        cols.insert(2, "agent_id")
        vals.insert(2, agent_id)
    stmt = (f"INSERT INTO audit_log ({', '.join(cols)})"
            f" VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id")
    if conn is not None:            # 调用方事务内：不自行 commit，随其统一落/回滚
        with conn.cursor() as cur:
            cur.execute(stmt, vals)
            return str(cur.fetchone()[0])
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute(stmt, vals)
        return str(cur.fetchone()[0])
