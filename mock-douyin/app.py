# ==================================================================
# 星图·模拟（mock-douyin，spec §3 / §6）：模拟「抖音达人平台」的独立轻量服务。
# 与真实抖音无任何连接；数据 = 仓库种子（data/seed 挂载，只读）。
# 页面三张：达人列表（搜索/筛选/分页）、达人详情（报价卡/历史合作/带货商品）、
# 效果报表（日消耗/转化，聚合两平台事实 CSV）。
# M6 的 agent 浏览工具（Playwright 无头）走 HTTP 真实点击这组页面。
# 纯 stdlib（http.server + csv），零依赖；SEED_DIR 指向种子目录。
# 本地直跑：SEED_DIR=data/seed python mock-douyin/app.py   → http://127.0.0.1:8100
# ==================================================================

from __future__ import annotations

import csv
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SEED = Path(os.environ.get("SEED_DIR", "data/seed"))
PORT = int(os.environ.get("PORT", "8100"))


def _rows(name: str) -> list[dict]:
    with open(SEED / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_creators() -> list[dict]:
    collabs: dict[str, list[str]] = {}
    for r in _rows("case_creators.csv"):
        collabs.setdefault(r["creator_id"], []).append(r["case_id"])
    return [{**r, "case_ids": sorted(set(collabs.get(r["creator_id"], [])))}
            for r in _rows("creators.csv")]


def load_products() -> dict[str, dict]:
    by_id = {r["product_id"]: r for r in _rows("brands_products.csv")}
    promote: dict[str, list[dict]] = {}
    for r in _rows("creator_products.csv"):
        p = by_id.get(r["product_id"])
        if p:
            promote.setdefault(r["creator_id"], []).append(p)
    return promote


def load_report() -> list[dict]:
    """两平台事实按日聚合（消耗/转化汇总——比率不预聚合，口径留在消费方）。"""
    daily: dict[str, dict] = {}
    for fname, date_k, cost_k, conv_k in (
            ("creative_metrics_daily_douyin.csv", "date", "cost", "conversions"),
            ("creative_metrics_daily_xhs.csv", "日期", "消耗", "转化量")):
        for r in _rows(fname):
            d = daily.setdefault(r[date_k], {"date": r[date_k], "cost": 0.0, "conversions": 0})
            d["cost"] += float(r[cost_k] or 0)
            d["conversions"] += int(float(r[conv_k] or 0))
    return sorted(daily.values(), key=lambda x: x["date"])


CREATORS = load_creators()
PRODUCTS = load_products()
REPORT = load_report()

CSS = """
body{font:14px/1.6 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;margin:0;background:#f6f7f9;color:#1c1e21}
header{background:#111;color:#fff;padding:14px 28px;display:flex;align-items:center;gap:12px}
header .logo{font-size:18px;font-weight:700}
header .sim{background:#fe2c55;color:#fff;font-size:11px;padding:2px 8px;border-radius:10px}
header nav a{color:#cbd2d9;margin-left:18px;text-decoration:none}
main{max-width:1080px;margin:24px auto;padding:0 20px}
.card{background:#fff;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.08);padding:18px 20px;margin-bottom:16px}
table{width:100%;border-collapse:collapse}
th{color:#6b7280;font-weight:500;text-align:left;padding:8px 10px;border-bottom:1px solid #eceef1;font-size:12px}
td{padding:10px;border-bottom:1px solid #f2f3f5}
a{color:#0f6fff;text-decoration:none}
input,select,button{font:inherit;padding:6px 10px;border:1px solid #d7dbe0;border-radius:6px;margin-right:8px}
button{background:#fe2c55;color:#fff;border:none;padding:6px 16px;cursor:pointer}
.tag{display:inline-block;background:#f1f3f6;border-radius:4px;padding:1px 7px;margin:1px 3px;font-size:12px;color:#444}
.kpi{display:inline-block;margin-right:28px}
.kpi b{display:block;font-size:22px}
.kpi span{color:#6b7280;font-size:12px}
.muted{color:#6b7280;font-size:12px}
"""

PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>{title} · 星图</title><style>{css}</style></head><body>
<header><span class="logo">★ 星图</span><span class="sim">模拟</span>
<nav><a href="/">达人广场</a><a href="/report">效果报表</a></nav></header>
<main>{body}</main></body></html>"""


def _fmt_wan(n) -> str:
    n = float(n or 0)
    return f"{n / 10000:.1f}万" if n >= 10000 else f"{n:.0f}"


def render_list(q: str, platform: str, niche: str, page: int) -> str:
    items = [c for c in CREATORS
             if (not q or q in c["name"] or q in c["niches"])
             and (not platform or c["platform"] == platform)
             and (not niche or niche in c["niches"])]
    size, page = 10, max(1, page)
    pages = max(1, (len(items) + size - 1) // size)
    chunk = items[(page - 1) * size:page * size]
    rows = "".join(
        f"<tr><td><a href='/creator/{c['creator_id'].split(':')[1]}'>{c['name']}</a></td>"
        f"<td>{'抖音' if c['platform'] == 'douyin' else '小红书'}</td>"
        f"<td>{''.join(f'<span class=tag>{n}</span>' for n in c['niches'].split('|'))}</td>"
        f"<td>{_fmt_wan(c['followers'])}</td><td>¥{int(c['quote_20s']):,}</td>"
        f"<td>¥{int(c['gmv_30d']):,}</td><td>{c['city']}</td><td>{c['rating']}</td>"
        f"<td>{len(c['case_ids'])}</td></tr>" for c in chunk)
    niches = sorted({n for c in CREATORS for n in c["niches"].split("|")})
    body = f"""
<div class=card><form method=get action="/">
<input id=kw name=q value="{q}" placeholder="搜索达人名 / 视频方向">
<select name=platform><option value="">全部平台</option>
<option{' selected' if platform=='douyin' else ''} value=douyin>抖音</option>
<option{' selected' if platform=='xhs' else ''} value=xhs>小红书</option></select>
<select name=niche><option value="">全部方向</option>
{''.join(f"<option{' selected' if niche==n else ''}>{n}</option>" for n in niches)}</select>
<button type=submit>搜索</button></form></div>
<div class=card><table><thead><tr><th>达人</th><th>平台</th><th>视频方向</th><th>粉丝</th>
<th>20s视频报价</th><th>30天带货GMV</th><th>城市</th><th>评分</th><th>合作单</th></tr></thead>
<tbody>{rows or '<tr><td colspan=9 class=muted>没有匹配的达人</td></tr>'}</tbody></table>
<p class=muted>第 {page} / {pages} 页，共 {len(items)} 位达人
{'&nbsp;<a href=?q=' + q + '&platform=' + platform + '&niche=' + niche + '&page=' + str(page-1) + '>上一页</a>' if page > 1 else ''}
{'&nbsp;<a href=?q=' + q + '&platform=' + platform + '&niche=' + niche + '&page=' + str(page+1) + '>下一页</a>' if page < pages else ''}</p></div>"""
    return PAGE.format(title="达人广场", css=CSS, body=body)


def render_detail(num: str) -> str:
    c = next((x for x in CREATORS if x["creator_id"] == f"Creator:{num}"), None)
    if not c:
        return PAGE.format(title="未找到", css=CSS, body='<div class=card>没有这位达人</div>')
    prods = PRODUCTS.get(c["creator_id"], [])
    body = f"""
<div class=card><h2 style=margin:0 0 6px>{c['name']}
<span class=tag>{'抖音' if c['platform']=='douyin' else '小红书'}</span></h2>
<p class=muted>{''.join(f'<span class=tag>{n}</span>' for n in c['niches'].split('|'))} · {c['city']} · 评分 {c['rating']}</p>
<p><span class=kpi><b>{_fmt_wan(c['followers'])}</b><span>粉丝</span></span>
<span class=kpi><b>¥{int(c['quote_20s']):,}</b><span>20s视频报价</span></span>
<span class=kpi><b>¥{int(c['quote_image']):,}</b><span>图文报价</span></span>
<span class=kpi><b>¥{int(c['gmv_30d']):,}</b><span>30天带货GMV</span></span></p></div>
<div class=card><h3>历史合作（{len(c['case_ids'])} 单）</h3>
<p class=muted>{'、'.join(c['case_ids']) or '暂无'}</p></div>
<div class=card><h3>带货商品（{len(prods)}）</h3><table>
<thead><tr><th>商品</th><th>品类</th><th>规格</th><th>客单价</th></tr></thead><tbody>
{''.join(f"<tr><td>{p['app_name']}</td><td>{p['category']}</td><td>{p['spec'] or '-'}</td><td>{('¥'+p['price']) if p['price'] else '-'}</td></tr>" for p in prods)
 or '<tr><td colspan=4 class=muted>暂无</td></tr>'}</tbody></table></div>"""
    return PAGE.format(title=c["name"], css=CSS, body=body)


def render_report() -> str:
    total_cost = sum(d["cost"] for d in REPORT)
    total_conv = sum(d["conversions"] for d in REPORT)
    rows = "".join(f"<tr><td>{d['date']}</td><td>¥{d['cost']:,.0f}</td><td>{d['conversions']:,}</td></tr>"
                   for d in REPORT[-30:])
    body = f"""
<div class=card><p><span class=kpi><b>¥{total_cost:,.0f}</b><span>累计消耗（两平台汇总）</span></span>
<span class=kpi><b>{total_conv:,}</b><span>累计转化</span></span></p></div>
<div class=card><h3>近 30 天明细</h3><table><thead><tr><th>日期</th><th>消耗</th><th>转化</th></tr></thead>
<tbody>{rows}</tbody></table><p class=muted>数据即种子事实（creative_metrics_daily_*）——
比率型口径（CPA 等）由消费方按汇总比计算，平台只出分子分母（README §六）</p></div>"""
    return PAGE.format(title="效果报表", css=CSS, body=body)


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: str, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj) -> None:
        import json
        self._send(json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/" :
            self._send(render_list(qs.get("q", ""), qs.get("platform", ""),
                                   qs.get("niche", ""), int(qs.get("page", "1"))))
        elif u.path == "/report":
            self._send(render_report())
        elif u.path == "/api/creators":
            q, platform, niche = qs.get("q", ""), qs.get("platform", ""), qs.get("niche", "")
            self._json({"items": [c for c in CREATORS
                                  if (not q or q in c["name"] or q in c["niches"])
                                  and (not platform or c["platform"] == platform)
                                  and (not niche or niche in c["niches"])]})
        elif re.fullmatch(r"/creator/(\w+)", u.path):
            self._send(render_detail(u.path.split("/")[2]))
        elif re.fullmatch(r"/api/creators/(\w+)", u.path):
            num = u.path.split("/")[3]
            c = next((x for x in CREATORS if x["creator_id"] == f"Creator:{num}"), None)
            (self._json({"creator": c, "products": PRODUCTS.get(c["creator_id"], [])})
             if c else self.send_error(404))
        else:
            self.send_error(404)


if __name__ == "__main__":
    print(f"星图·模拟 running on http://127.0.0.1:{PORT}（SEED_DIR={SEED}）")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
