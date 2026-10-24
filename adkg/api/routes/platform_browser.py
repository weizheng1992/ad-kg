"""星图·模拟平台的 Playwright 浏览工具（spec §6 / Q10A / Q11A）。

agent 工具注册表里的「数据平台连接器」：无头浏览器真实点击（达人广场 → 搜索 /
直达详情），每步截图随 tool_step 事件流回前端（ZCode 式透明）；抓取结果按
platform_api 口径幂等 MERGE 入图 + 审计——这是连接器主数据同步，不是 agent
断言（§9.5 平台效果数据通道），不经 /actions/check（那是业务动作裁决）。

抓取页 = mock-douyin 服务（ADKG_MOCK_DOUYIN_URL，默认本机 8100）；
playwright 缺依赖 / 服务不在线时返回错误串，不断 agent 循环（§7.2 降级）。
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone


def _shot(page) -> str | None:
    """页面截图 → jpeg data URL（质量 55：单步 ~30-60KB，流回前端够用）。"""
    try:
        png = page.screenshot(type="jpeg", quality=55)
        return "data:image/jpeg;base64," + base64.b64encode(png).decode()
    except Exception:
        return None


def _num(text: str) -> int:
    """「728.5万」→ 7285000；「¥138,999」→ 138999；解析失败返回 0。"""
    t = text.replace("¥", "").replace(",", "").strip()
    m = re.match(r"([\d.]+)万?$", t)
    if not m:
        return 0
    v = float(m.group(1))
    return int(v * 10000) if t.endswith("万") else int(v)


def fetch_creator_from_platform(args: dict, ctx) -> str:
    base = ctx.env.get("ADKG_MOCK_DOUYIN_URL", "http://127.0.0.1:8100").rstrip("/")
    no = str(args.get("creator_no") or "").strip()
    query = str(args.get("query") or "").strip()
    if not no and not query:
        return "query（达人名/方向，模糊搜）与 creator_no（cr11 形态，直达详情）必填一个"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "playwright 未安装（uv add playwright && uv run playwright install chromium）"

    def emit(step: int, desc: str, shot: str | None = None) -> None:
        if getattr(ctx, "emit", None):
            ctx.emit("tool_step", tool="fetch_creator_from_platform",
                     step=step, desc=desc, screenshot=shot)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"{base}/", timeout=15000, wait_until="domcontentloaded")
            emit(1, "打开星图·模拟达人广场", _shot(page))
            if no:
                page.goto(f"{base}/creator/{no}", timeout=15000, wait_until="domcontentloaded")
                emit(2, f"直达达人详情 /creator/{no}", _shot(page))
            else:
                page.fill("#kw", query)
                emit(2, f"搜索「{query}」", _shot(page))
                page.click("button[type=submit]")
                page.wait_for_load_state("domcontentloaded")
                first = page.locator("tbody a").first
                if not first.count():
                    return f"平台搜索「{query}」无结果"
                name = first.inner_text()
                first.click()
                page.wait_for_load_state("domcontentloaded")
                no = page.url.rsplit("/", 1)[-1]
                emit(3, f"点击「{name}」进入详情", _shot(page))

            # 详情页抽取（容忍单字段缺失：MERGE `+=` 合并语义不清空旧值）
            kpis = page.locator(".kpi b").all_inner_texts()
            platform_txt = page.locator("h2 span.tag").first.inner_text() if page.locator(
                "h2 span.tag").count() else ""
            niches = page.locator("p.muted .tag").all_inner_texts()
            muted = page.locator("h2 + p.muted").inner_text() if page.locator(
                "h2 + p.muted").count() else ""
            m_city = re.search(r"([\u4e00-\u9fa5]{2,4}) ·", muted)
            m_rating = re.search(r"评分 ([\d.]+)", muted)
            followers = _num(kpis[0]) if len(kpis) > 0 else 0
            quote_20s = _num(kpis[1]) if len(kpis) > 1 else 0
            quote_image = _num(kpis[2]) if len(kpis) > 2 else 0
            gmv_30d = _num(kpis[3]) if len(kpis) > 3 else 0
            emit(4, f"抽取档案：粉丝 {followers} · 20s 报价 {quote_20s} · GMV {gmv_30d}",
                 _shot(page))

            creator_id = f"Creator:{no}"
            from adkg.guards.audit import audit
            from adkg.models import Entity, Provenance
            # h2 内含平台 tag span：inner_text 按行拼——取首行即纯名字
            props = {"name": page.locator("h2").inner_text().split("\n")[0].strip(),
                     "platform": ("douyin" if "抖音" in platform_txt
                                  else "xhs" if "小红书" in platform_txt else None),
                     "niches": "|".join(niches)}
            props = {k: v for k, v in props.items() if v is not None}
            if followers:
                props["followers"] = followers
            if quote_20s:
                props["quote_20s"] = quote_20s
            if quote_image:
                props["quote_image"] = quote_image
            if gmv_30d:
                props["gmv_30d"] = gmv_30d
            if m_city:
                props["city"] = m_city.group(1)
            if m_rating:
                props["rating"] = float(m_rating.group(1))
            # 权威仲裁（§12.2 / Q11A「冲突仍走 review_queue」）：已有更高权威记录
            # （如种子 system_of_record/100）在场时不覆盖字段——冲突进 review_queue
            # 人审，抓取结果仅随工具返回供参考
            prov = Provenance(source_type="platform_api",
                              source_id=f"mock-douyin:creator:{no}",
                              fetched_at=datetime.now(timezone.utc))
            with ctx.graph.session() as s:
                rec = s.run("MATCH (n:Entity {id: $id}) RETURN n.authority AS auth",
                            id=creator_id).single()
            existing_auth = rec["auth"] if rec else None
            if existing_auth is not None and existing_auth > prov.authority:
                import psycopg
                with psycopg.connect(ctx.env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
                    # 去重：同实体+同来源的未决 conflict 只留一条（幂等重抓不刷屏）；
                    # incoming_source_type 供人审处置回放（spec §15）
                    cur.execute(
                        "INSERT INTO review_queue (kind, payload)"
                        " SELECT 'conflict', %(payload)s"
                        " WHERE NOT EXISTS (SELECT 1 FROM review_queue"
                        "  WHERE kind = 'conflict' AND status = 'open'"
                        "  AND payload->>'entity' = %(entity)s"
                        "  AND payload->>'incoming_source' = %(source)s)",
                        {"payload": json.dumps(
                            {"entity": creator_id,
                             "incoming_source": prov.source_id,
                             "incoming_source_type": "platform_api",
                             "incoming_authority": prov.authority,
                             "existing_authority": existing_auth,
                             "incoming_props": props}, ensure_ascii=False),
                         "entity": creator_id, "source": prov.source_id})
                audit(ctx.env, ctx.role, ctx.person, "platform_fetch", creator_id, "deny",
                      f"更高权威（{existing_auth}）在场未覆盖，冲突进 review_queue（§12.2）")
                emit(5, f"库内已有更高权威记录（{existing_auth}），未覆盖——冲突进人审队列")
                return json.dumps({"creator_id": creator_id, **props, "ingested": False,
                                   "conflict_queued": True},
                                  ensure_ascii=False, default=str)
            ctx.graph.upsert_entities([Entity(entity_class="Creator", entity_id=creator_id,
                                              props=props, provenance=prov)])
            from adkg.api.routes.creators import record_quote_history
            record_quote_history(ctx.env, creator_id, props.get("quote_20s"),
                                 "platform_api", prov.source_id)   # 报价快照（§15）
            audit(ctx.env, ctx.role, ctx.person, "platform_fetch", creator_id,
                  "allow", "playwright 抓取星图·模拟并幂等入图（platform_api）")
            emit(5, f"已入图（幂等 MERGE，provenance=platform_api）：{creator_id}")
            return json.dumps({"creator_id": creator_id, **props,
                               "ingested": True}, ensure_ascii=False, default=str)
        except Exception as e:                              # noqa: BLE001 平台故障降级为工具结果
            return f"平台抓取失败：{type(e).__name__}: {e}"
        finally:
            browser.close()
