"""一次性初始化脚本（骨架）：执行 sql/、建 Postgres 双账号、建 Neo4j 约束与索引。

幂等：全部 IF NOT EXISTS / DO 块，重复执行结果不变（tests 集成冒烟依赖这一点）。

用法：uv run python scripts/init_db.py
凭据来自 .env（见 .env.example）；双账号口令从 ADKG_PG_DSN / ADKG_PG_RO_DSN 解析。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

import os  # noqa: E402  （dotenv 之后取值）


def _pg_admin_dsn() -> str:
    return (f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
            f"@127.0.0.1:{os.environ.get('POSTGRES_PORT', '5433')}/{os.environ['POSTGRES_DB']}")


def _password_from_dsn(dsn: str) -> str:
    m = re.search(r"://[^:]+:([^@]+)@", dsn)
    if not m:
        sys.exit("无法从 DSN 解析口令，检查 .env 的 ADKG_PG_DSN / ADKG_PG_RO_DSN")
    return m.group(1)


def init_postgres() -> None:
    """按序执行 sql/ 全部脚本；创建 adkg_rw（读写）与 adkg_ro（只读，text2sql 第一闸）。"""
    dsn = _pg_admin_dsn()
    rw_pw = _password_from_dsn(os.environ["ADKG_PG_DSN"])
    ro_pw = _password_from_dsn(os.environ["ADKG_PG_RO_DSN"])

    sql_files = sorted((ROOT / "sql").glob("*.sql"))
    sql = "\n".join(f.read_text(encoding="utf-8") for f in sql_files)
    grants = f"""
    -- 双账号（§五 运行形态）：DO 块保证幂等
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'adkg_rw') THEN
            CREATE ROLE adkg_rw LOGIN PASSWORD '{rw_pw}';
        ELSE
            ALTER ROLE adkg_rw WITH LOGIN PASSWORD '{rw_pw}';
        END IF;
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'adkg_ro') THEN
            CREATE ROLE adkg_ro LOGIN PASSWORD '{ro_pw}';
        ELSE
            ALTER ROLE adkg_ro WITH LOGIN PASSWORD '{ro_pw}';
        END IF;
    END $$;

    GRANT USAGE ON SCHEMA public TO adkg_rw, adkg_ro;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO adkg_rw;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO adkg_rw;
    -- audit_log 只追加（§八）：对应用账号收回 UPDATE / DELETE
    REVOKE UPDATE, DELETE ON audit_log FROM adkg_rw;
    -- adkg_ro：只读事实与检索面，不含 audit_log（仅 admin 可读，§八）
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO adkg_ro;
    REVOKE SELECT ON audit_log FROM adkg_ro;
    -- 账号与会话表不进只读检索面（spec §2：口令哈希 / 会话 token 不出应用层）
    REVOKE SELECT ON app_user, app_session FROM adkg_ro;
    """

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql)
        conn.execute(grants)
    print(f"Postgres：{' + '.join(f.name for f in sql_files)} 执行完成；"
          "adkg_rw / adkg_ro 已就绪（audit_log 只追加，app_* 不进只读面）")


def init_neo4j() -> None:
    """约束与索引（§四 scripts 注释）：entity_id 唯一 + class 索引。"""
    uri = os.environ.get("ADKG_NEO4J_URI", "bolt://127.0.0.1:7687")
    driver = GraphDatabase.driver(
        uri, auth=(os.environ["ADKG_NEO4J_USER"], os.environ["ADKG_NEO4J_PASSWORD"]))
    try:
        with driver.session() as s:
            s.run("CREATE CONSTRAINT entity_id IF NOT EXISTS "
                  "FOR (n:Entity) REQUIRE n.id IS UNIQUE")
            s.run("CREATE INDEX entity_class IF NOT EXISTS FOR (n:Entity) ON (n.class)")
        print("Neo4j：entity_id 唯一约束 + class 索引已就绪")
    finally:
        driver.close()


if __name__ == "__main__":
    try:
        init_postgres()
    except psycopg.OperationalError as e:
        sys.exit(f"连不上 Postgres（先 docker compose up -d）：{e}")
    try:
        init_neo4j()
    except Exception as e:  # noqa: BLE001 骨架阶段：Neo4j 不在线只警告不失败
        print(f"警告：Neo4j 初始化跳过（{e}）", file=sys.stderr)
