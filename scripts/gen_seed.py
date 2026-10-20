"""生成合成种子数据（§五 数据三层①）：静态文件提交进 repo，可重生成。

确定性：random.seed(42)，同日重跑产出逐字节一致（diff 干净）；事实日期为滚动窗口（见 gen_facts），重生成即滚动到当月。
规模取规模假设零头：品牌 8 / 商品 15 / 案例 20（覆盖 5 个 stage）/
素材 ~80（含 1 对同素材双平台锚点）/ 事实行 ~2k / 规范 8 / 断言 10。
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = Path(__file__).resolve().parents[1] / "data" / "seed"
rng = random.Random(42)

BRANDS = [("B01", "轻食日记", "餐饮"), ("B02", "律动星球", "运动健身"), ("B03", "拾光书屋", "文化阅读"),
          ("B04", "澄肌研究所", "美妆个护"), ("B05", "途野露营", "户外旅行"), ("B06", "喵汪到家", "宠物服务"),
          ("B07", "速算蜂", "教育学习"), ("B08", "眠海科技", "健康睡眠")]
AGE_BY_CATEGORY = {  # 目标人群年龄（岁），按品类取行业常见投放定向区间
    "餐饮": "20-35", "运动健身": "18-40", "文化阅读": "22-45", "美妆个护": "18-35",
    "户外旅行": "25-45", "宠物服务": "22-40", "教育学习": "28-45", "健康睡眠": "25-50"}
PRODUCTS = [(f"P{i:02d}", f"{b[1]}App", b[2], "iOS/Android", AGE_BY_CATEGORY[b[2]])
            for i, b in enumerate(BRANDS, 1)]
PRODUCTS += [(f"P{i:02d}", f"{b[1]}小程序", b[2], "微信", AGE_BY_CATEGORY[b[2]])
             for i, b in enumerate(BRANDS, 1)][:7]
PEOPLE = [("li", "李昂", "AE"), ("wang", "王雪", "创意"), ("zhao", "赵岚", "优化师"),
          ("zhou", "周荃", "财务"), ("chen", "陈朔", "管理层"), ("sun", "孙苗", "优化师")]
CLIENT = ("client_a", "顾佳", "客户对接人")          # 外部客户 principal
STAGES = (["proposal"] * 4 + ["live"] * 4 + ["closed"] * 6 + ["lost"] * 3 + ["terminated"] * 3)
CHANNELS = ["信息流", "搜索", "开屏"]
CAMP_SEQ = ("A", "B")                                   # 每案例两支计划的代号
TITLE_BY_CHANNEL = {                                    # 素材名：形式 + 规格，行业常见叫法
    "信息流": ["场景短剧 15s 竖版", "痛点开箱 30s 竖版", "达人种草 20s 竖版", "UGC 口播 15s 竖版"],
    "搜索": ["关键词创意图", "品牌专区图文", "长尾词图文"],
    "开屏": ["品牌主视觉 5s 动态", "大促静态 4s"],
}
GUIDELINES = [
    ("G-01", "creative_spec", None, "信息流视频前 3 秒须出现品牌标识，不得纯文字开场。"),
    ("G-02", "creative_spec", 30, "信息流视频总时长不超过 {max_duration_s} 秒。"),
    ("G-03", "creative_spec", 15, "竖版视频时长上限 {max_duration_s} 秒，前 3 秒须出现品牌标识。"),
    ("G-04", "brand_vi", None, "品牌标识使用主视觉规范，禁止拉伸变形与二次调色。"),
    ("G-05", "brand_vi", None, "落地页头图与素材视觉一致， Logo 位置右上。"),
    ("G-06", "ad_law", None, "不得使用「最佳」「第一」等绝对化用语（《广告法》第九条）。"),
    ("G-07", "ad_law", None, "功效类表述须有证明材料，广告中须显著标明。"),
    ("G-08", "creative_spec", None, "结尾 2 秒固定品牌收尾卡，含 slogan 与下载引导。"),
]
# 定向人群包（Audience，§六 targets N:M）：每品牌一个主包 + 前四品牌各一个次包，
# 描述与品类强相关（真实感）；Campaign targets 本品牌的全部人群包
AUDIENCES = {
    "B01": [("人群包·轻食白领", "一二线城市 20-35 岁白领，工作日午餐外卖高频，关注控卡轻食"),
            ("人群包·健身轻食党", "运动健身App 重度用户，偏好高蛋白低卡餐")],
    "B02": [("人群包·运动发烧友", "18-40 岁运动App 月活用户，跑靴/健身装备近期浏览者"),
            ("人群包·减脂新手", "搜索过减脂餐/居家训练的 22-30 岁用户")],
    "B03": [("人群包·阅读爱好者", "22-45 岁电子书/听书App 付费用户，社科与新书高频点击者"),
            ("人群包·学生备考族", "高校集中区域 18-24 岁，考试季活跃")],
    "B04": [("人群包·精致护肤党", "18-35 岁女性，美妆垂类内容互动者，近期浏览过功效护肤"),
            ("人群包·学生党平价护肤", "高校人群，客单价敏感，国货偏好")],
    "B05": [("人群包·露营亲子家庭", "25-45 岁有孩家庭，节假日近郊游搜索者，露营装备浏览者")],
    "B06": [("人群包·城市宠物主", "22-40 岁一 二线城市养宠人群，宠物服务/用品近期购买者")],
    "B07": [("人群包·职场进阶族", "28-45 岁一线城市职场人，效率/技能类课程近期学习者")],
    "B08": [("人群包·失眠改善人群", "25-50 岁，睡眠监测App 用户或助眠产品近期搜索者")],
}


def _write_csv(rel: str, header: list[str], rows: list[list]) -> None:
    path = SEED / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([header] + rows)


def gen_master() -> list[list[str]]:
    """brands_products.csv + org_people.csv + cases_campaigns.csv（含双平台同素材锚点）。"""
    _write_csv("brands_products.csv",
               ["brand_id", "brand_name", "category", "product_id", "app_name", "platform",
                "target_age"],
               [[f"Brand:{b[0]}", b[1], b[2], f"Product:{p[0]}", p[1], p[3], p[4]]
                for b, p in zip(BRANDS, PRODUCTS[:8])])
    cases, rows, people_rows = [], [], []
    case_of_person: dict[str, str] = {}
    case_name_by_id: dict[str, str] = {}
    for i, stage in enumerate(STAGES, 1):
        bi = i % len(BRANDS)
        brand = BRANDS[bi]
        # 商品归属同品牌（App/小程序都从该品牌取）——brand 按 i%8、product 按 i%15
        # 各选各的会错配出「澄肌研究所·途野露营App」这类假数据（2026-10-20 实测）
        product = PRODUCTS[8 + bi] if (i % 2 == 1 and bi < 7) else PRODUCTS[bi]
        person = PEOPLE[i % len(PEOPLE)]
        case_id = f"Case:C-2025-{i:03d}"
        case_name = f"{brand[1]}·{product[1]}投放案例"     # 与案例文档标题同式（图上 Case.name）
        case_name_by_id[case_id] = case_name
        cases.append((case_id, stage, brand, product, person))
        case_of_person.setdefault(person[0], case_id)
        for c in range(2):                                # 每案例 2 计划
            camp = f"Campaign:{case_id.split(':')[1]}-cp{c + 1}"
            channel = CHANNELS[(i + c) % 3]
            camp_name = f"{channel}计划·{CAMP_SEQ[c]}"
            for k in range(2):                            # 每计划 2 素材
                cid = f"Creative:{case_id.split(':')[1]}-cp{c + 1}-cr{k + 1}"
                titles = TITLE_BY_CHANNEL[channel]
                rows.append([case_id, case_name, stage, f"{(i * 7 + c * 3) % 9 + 1}0000",
                             "paid" if stage == "closed" else "unbilled",
                             f"Brand:{brand[0]}", f"Product:{product[0]}", camp, camp_name,
                             "delivering" if stage == "live" else "paused",
                             f"{(i + c) % 5 * 1000 + 3000}", cid,
                             titles[(i + c + k) % len(titles)],
                             "1" if (i + k) % 3 == 0 else "0",
                             ["douyin", "xhs"][(i + c + k) % 2],
                             channel])
    # 双平台同素材锚点（§12.5）：同一本体素材在两平台各有 local id
    rows.append(["Case:C-2025-005", case_name_by_id["Case:C-2025-005"], "live", "36000", "unbilled",
                 "Brand:B06", "Product:P06", "Campaign:C-2025-005-cp1", "信息流计划·A",
                 "delivering", "4200", "Creative:creative_992", "上门洗护种草 15s 竖版",
                 "1", "douyin", "信息流"])
    rows.append(["Case:C-2025-005", case_name_by_id["Case:C-2025-005"], "live", "36000", "unbilled",
                 "Brand:B06", "Product:P06", "Campaign:C-2025-005-cp1", "信息流计划·A",
                 "delivering", "4200", "Creative:creative_992", "上门洗护种草 15s 竖版",
                 "1", "xhs", "信息流"])
    _write_csv("cases_campaigns.csv",
               ["case_id", "case_name", "stage", "bd_budget", "settlement_status", "brand_id",
                "product_id", "campaign_id", "campaign_name", "campaign_status", "daily_budget",
                "creative_id", "creative_title", "is_aigc", "platform", "channel"], rows)
    for idx, (pid, name, role) in enumerate(PEOPLE):
        people_rows.append([f"Person:{pid}", name, role,
                            f"Brand:{BRANDS[idx % 8][0]}", case_of_person[pid], "0"])
    people_rows.append([f"Person:{CLIENT[0]}", CLIENT[1], CLIENT[2], "Brand:B04", "", "1"])
    _write_csv("org_people.csv",
               ["person_id", "name", "org_role", "brand_id", "case_id", "is_external"],
               people_rows)
    return cases


def gen_docs(cases) -> None:
    """cases/*.md 案例文档（抽取路的输入）+ guidelines/*.md（frontmatter 带机判阈值）。"""
    (SEED / "cases").mkdir(parents=True, exist_ok=True)
    for case_id, stage, brand, product, person in cases:
        text = (f"# {brand[1]}·{product[1]}投放案例\n\n"
                f"对接人 {person[1]}（{person[2]}）负责本案，当前阶段 {stage}。\n\n"
                f"## 背景\n{brand[1]} 是{brand[2]}赛道品牌，推广商品「{product[1]}」，"
                f"主打 {product[3]} 端获客。\n\n"
                f"## 投放\n两支计划分别跑信息流与搜索，素材以竖版短视频为主，"
                f"其中一条为 AIGC 生成并沿用爆款衍生。\n\n"
                f"## 结果\n{'转化成本优于行业均值，已结案复盘。' if stage == 'closed' else '投放进行中，CPA 稳定在目标区间。'}\n")
        (SEED / "cases" / f"{case_id.split(':')[1]}.md").write_text(text, encoding="utf-8")
    (SEED / "guidelines").mkdir(parents=True, exist_ok=True)
    for gid, gtype, max_dur, body in GUIDELINES:
        fm = f"---\nid: Guideline:{gid}\nguideline_type: {gtype}\n"
        if max_dur:
            fm += f"max_duration_s: {max_dur}\n"
        fm += "---\n\n"
        (SEED / "guidelines" / f"{gid}.md").write_text(
            fm + f"# {gid} {gtype}\n\n{body}\n", encoding="utf-8")


def _fact_date(i: int, per: int, j_max: int, months: list[tuple[int, int]]) -> str:
    """行号 → 日期（滚动窗口，README §八 数据三层）。

    对齐素材（各平台 local id 前 10 个，对应 load_seed 的 entity_alias）末 3 次
    出现钉进最新月 5/13/21 日（隔 8 天）——top-N 口径 HAVING count>=3 对"上月"
    类问句常青命中；其余按月均匀铺。日期只改分布不改数值（rng 调用序与日期
    解耦），全量口径聚合与非窗口类 golden 期望稳定。
    """
    k, j = i % per, i // per
    if k < 10 and j > j_max - 3:
        yy, mm = months[-1]
        return f"{yy}-{mm:02d}-{21 - (j_max - j) * 8:02d}"
    yy, mm = months[i % 12]
    return f"{yy}-{mm:02d}-{i % 28 + 1:02d}"


def gen_facts() -> None:
    """两平台素材粒度事实（~2k 行）；xhs 故意用中文表头（§四）。埋 3 个 CPA 异常素材。"""
    # 近 12 个整月滚动窗口（不含本月）：数据始终新鲜，"上月"类时间窗问题有数可答
    y, m = date.today().year, date.today().month
    months = []
    for _ in range(12):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        months.append((y, m))
    months.reverse()                                     # 旧 → 新
    anchor = f"{months[2][0]}-{months[2][1]:02d}-15"     # 同素材锚点日：第 3 个整月月中
    douyin, xhs = [], []
    for i in range(900):
        d = _fact_date(i, 80, 11, months)
        imp = rng.randint(8000, 60000)
        clk = int(imp * rng.uniform(0.004, 0.02))
        douyin.append([d, f"dy_c{i % 40}", f"dy_cr{i % 80}",
                       round(rng.uniform(80, 400), 2), imp, clk,
                       max(1, int(clk * rng.uniform(0.02, 0.08)))])
        imp2 = rng.randint(5000, 40000)
        clk2 = int(imp2 * rng.uniform(0.003, 0.015))
        xhs.append([_fact_date(i, 37, 24, months),      # 37 质数：行键联合周期 > 行数，防撞唯一约束
                    f"xhs_c{i % 35}", f"xhs_cr{i % 37}",
                    round(rng.uniform(60, 300), 2), imp2, clk2,
                    max(1, int(clk2 * rng.uniform(0.02, 0.07)))])
    douyin.append([anchor, "dy_c1", "dy_889", 86.0, 10000, 90, 1])   # 同素材锚点：抖音 dy_889
    xhs.append([anchor, "xhs_c1", "xhs_77", 120.0, 20000, 100, 2])
    _write_csv("creative_metrics_daily_douyin.csv",
               ["date", "campaign_local_id", "creative_local_id",
                "cost", "impressions", "clicks", "conversions"], douyin)
    _write_csv("creative_metrics_daily_xhs.csv",
               ["日期", "计划ID", "素材ID", "消耗", "曝光量", "点击量", "转化量"], xhs)


def gen_audiences() -> None:
    """定向人群包（§六 targets N:M）：audiences.csv 静态提交；targets 边由
    load_seed 推导（campaign → case → brand → 本品牌全部人群包）。"""
    rows = []
    for bi, (bid, _, _) in enumerate(BRANDS, 1):
        for k, (name, desc) in enumerate(AUDIENCES[bid], 1):
            rows.append([f"Audience:aud-{bid.lower()}-{k}", name, desc, f"Brand:{bid}"])
    _write_csv("audiences.csv",
               ["audience_id", "name", "targeting_desc", "brand_id"], rows)


def gen_assertions() -> None:
    rows = [
        ["Creative:creative_992", "violates", "Guideline:G-01", "0.91"],
        ["Creative:creative_992", "violates", "Guideline:G-03", "0.55"],
        ["Creative:C-2025-005-cp1-cr1", "violates", "Guideline:G-06", "0.88"],
        ["Creative:C-2025-005-cp1-cr2", "complies_with", "Guideline:G-01", "0.95"],
        ["Creative:C-2025-005-cp2-cr1", "complies_with", "Guideline:G-04", "0.92"],
        ["Creative:C-2025-013-cp1-cr1", "violates", "Guideline:G-06", "0.82"],
        ["Creative:C-2025-009-cp1-cr1", "violates", "Guideline:G-07", "0.5"],
        ["Creative:C-2025-003-cp1-cr1", "complies_with", "Guideline:G-08", "0.9"],
        ["Creative:C-2025-006-cp2-cr1", "violates", "Guideline:G-02", "0.85"],
        ["Creative:C-2025-012-cp1-cr1", "complies_with", "Guideline:G-01", "0.87"],
    ]
    _write_csv("assertions.csv",
               ["subject", "predicate", "object", "confidence"], rows)


if __name__ == "__main__":
    cases = gen_master()
    gen_docs(cases)
    gen_facts()
    gen_audiences()
    gen_assertions()
    n = sum(1 for p in SEED.rglob("*") if p.is_file())
    print(f"seed 生成完成：{n} 个文件 → data/seed/")
