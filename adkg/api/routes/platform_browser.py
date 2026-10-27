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
    """星图·模拟抓取并入库（写图）——与 POST /creators 同一道动作门（§12.4：
    agent 写工具不得比端点宽；2026-10-25 审查勘误）。"""

    base = ctx.env.get("ADKG_MOCK_DOUYIN_URL", "http://127.0.0.1:8100").rstrip("/")
    no = str(args.get("creator_id") or args.get("creator_no") or "").strip()
    query = str(args.get("query") or "").strip()
    if not no and not query:
        return "query（达人名/方向，模糊搜）与 creator_id（cr11 形态，直达详情）必填一个"
    from adkg.guards.rbac import role_allows
    if not role_allows(ctx.env, getattr(ctx, "shown", None) or ctx.role, "creator_write"):
        return "当前角色无达人录入权限，不能触发平台抓取入库（spec §18 角色门）"
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
            # 入库 + 权威仲裁走 creators._ingest_creator 单一来源（2026-10-26 收口，
            # 勘误旧整包 payload：字段级仲裁——空缺补齐、真字段冲突才进 review_queue；
            # audit_action 保持 platform_fetch 口径）。旧 review_queue 里的整包
            # incoming_props 载荷仍被人审处置兼容。
            from adkg.api.routes.creators import _ingest_creator
            result = _ingest_creator(ctx.env, ctx.graph, creator_id, props,
                                     "platform_api", f"mock-douyin:creator:{no}",
                                     ctx.role, ctx.person, audit_action="platform_fetch")
            outcome = str(result.get("outcome"))
            if outcome == "conflict":
                emit(5, f"库内已有更高权威记录（{result.get('existing_authority')}），"
                        f"未覆盖——空缺已补 {len(result.get('filled') or [])} 项，"
                        "字段冲突进人审队列")
                return json.dumps({"creator_id": creator_id, **props, "ingested": False,
                                   "conflict_queued": True,
                                   "field_diff": result.get("field_diff")},
                                  ensure_ascii=False, default=str)
            merged_note = (f"，空缺补齐 {len(result['filled'])} 项"
                           if result.get("filled") else "")
            emit(5, f"已入图（outcome={outcome}{merged_note}，"
                    f"provenance=platform_api）：{creator_id}")
            return json.dumps({"creator_id": creator_id, **props, "ingested": True,
                               "outcome": outcome},
                              ensure_ascii=False, default=str)
        except Exception as e:                              # noqa: BLE001 平台故障降级为工具结果
            return f"平台抓取失败：{type(e).__name__}: {e}"
        finally:
            browser.close()
