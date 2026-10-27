"""图标白名单前后端同源守门（缺陷清单⑫）：menus.py _ICONS 手抄自
web/src/lib/nav.tsx 的 ICONS 键集——此前同步全靠注释提醒，漂移无人拦。
本文件纯静态对账（读文件 + 正则，不依赖 DB）：两侧键集不一致即红，
把同步义务变成机器守门。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_图标白名单与nav_tsx同源():
    """_ICONS（后端校验白名单）必须与 nav.tsx ICONS（前端渲染表）键集完全一致。"""
    nav = (ROOT / "web" / "src" / "lib" / "nav.tsx").read_text(encoding="utf-8")
    m = re.search(r"export const ICONS[^{]*\{([^}]*)\}", nav)
    assert m, "web/src/lib/nav.tsx 未找到 export const ICONS 字面量"
    # 前端写法为简写键（LayoutDashboard, …）；兼容 Key: Value 形态取左半
    frontend = {k.split(":")[0].strip() for k in m.group(1).split(",") if k.strip()}
    from adkg.api.routes.menus import _ICONS
    assert frontend == set(_ICONS), (
        f"图标白名单漂移：仅前端 {sorted(frontend - set(_ICONS))} / "
        f"仅后端 {sorted(set(_ICONS) - frontend)}——两侧需同步（以后端 _ICONS 校验为准）")
