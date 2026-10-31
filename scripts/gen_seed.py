"""生成合成种子数据（§五 数据三层①）：静态文件提交进 repo，可重生成。

确定性：random.seed(42)，同日重跑产出逐字节一致（diff 干净）；事实日期为滚动窗口（见 gen_facts），重生成即滚动到当月。
规模取规模假设零头，2026-10-24 扩容（spec §12）：品牌 8+16 / 商品 18+21 /
案例 20+40（lost/terminated 各带拒因）/ 素材 ~80+160 / 事实行 ~1.8k+3.8k /
达人 20+40——**扩容全部追加**，旧 20 案例与既有事实逐字节不变（golden 实体域
锚定与既有测试断言零扰动；唯一排名型期望 G06 扩后按实际值校准）。
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = Path(__file__).resolve().parents[1] / "data" / "seed"
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"    # 文档直写 raw（2026-10-23 去重）
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
# SKU 形态商品（§六 Product 双形态）：规格/详情/价格齐备，投放案例与交易种子挂这三支
SKUS = [
    ("P16", "轻食即食鸡胸肉 7 日装", "餐饮", "7 日装 × 330g／冷藏锁鲜", "高蛋白低卡，健身餐搭配", "89.90", "B01"),
    ("P17", "澄肌烟酰胺焕亮精华礼盒", "美妆个护", "30ml × 2 瓶／礼盒装", "烟酰胺精华，提亮修护套装", "169.00", "B04"),
    ("P18", "喵汪到家上门洗护年卡", "宠物服务", "年卡 12 次／单次 60 分钟", "上门洗护服务，含深度除螨", "365.00", "B06"),
]
SKU_BY_BRAND = {sku[6]: sku[0] for sku in SKUS}
SKU_PRICE = {sku[0]: float(sku[5]) for sku in SKUS}
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
# 拒因（spec §3「合同拒绝的理由」）：lost/terminated 各 3 例，i 序即 (i-15)%3 / (i-18)%3
LOST_REASONS = ["预算被竞品方案挤占", "达人档期冲突，提案超期", "客户侧产品改版，投放暂缓"]
TERMINATE_REASONS = ["客户年度预算终止", "合作条款未谈拢提前终止", "效果未达约定阈值终止"]

# ── 扩容批次（2026-10-24，全追加）────────────────────────────────────
# 新品牌 16（8 品类 × 2）/ 新 SKU 6 / 新案例 40（i=21..60）/ 新达人 40（cr21..cr60）
NEW_BRANDS = [
    ("B09", "植愈研社", "美妆个护"), ("B10", "轻卡星球", "餐饮"),
    ("B11", "铁山攀岩馆", "运动健身"), ("B12", "字句出版社", "文化阅读"),
    ("B13", "苔原户外", "户外旅行"), ("B14", "爪爪联盟", "宠物服务"),
    ("B15", "口算星人", "教育学习"), ("B16", "晚安研究所", "健康睡眠"),
    ("B17", "烟酰胺实验室", "美妆个护"), ("B18", "海盐轻食", "餐饮"),
    ("B19", "肌力芳草地", "运动健身"), ("B20", "古卷书局", "文化阅读"),
    ("B21", "星野营地", "户外旅行"), ("B22", "布偶家族", "宠物服务"),
    ("B23", "思维导图侠", "教育学习"), ("B24", "静音舱", "健康睡眠"),
]
NEW_PRODUCTS = [  # 每家新品牌 1 支 App（P19..P34）
    (f"P{18 + n}", f"{b[1]}App", b[2], "iOS/Android", AGE_BY_CATEGORY[b[2]])
    for n, b in enumerate(NEW_BRANDS, 1)]
NEW_SKUS = [  # 交易面加厚：6 个新 SKU（P35..P40）
    ("P35", "轻卡星球鸡胸肉全家福", "餐饮", "10 袋 × 100g／冷冻", "高蛋白便携装", "69.00", "B10"),
    ("P36", "植愈研社神经酰胺面霜", "美妆个护", "50g × 1 瓶", "屏障修护面霜", "129.00", "B09"),
    ("P37", "铁山攀岩镁粉袋套装", "运动健身", "镁粉袋 + 200g 粉／套装", "室内攀岩入门套装", "199.00", "B11"),
    ("P38", "苔原户外四季帐篷", "户外旅行", "2 人双层／铝杆", "公园露营到徒步全能款", "899.00", "B13"),
    ("P39", "爪爪联盟冻干主食试吃装", "宠物服务", "6 味 × 100g／试吃箱", "猫犬通用主食冻干", "89.00", "B14"),
    ("P40", "晚安研究所褪黑素软糖", "健康睡眠", "60 粒 × 1 瓶", "3mg 缓释配方", "99.00", "B16"),
]
NEW_STAGES = (["live"] * 10 + ["closed"] * 14 + ["proposal"] * 6 +
              ["lost"] * 6 + ["terminated"] * 4)          # 40，i = 21..60
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
    """brands_products.csv + org_people.csv + cases_campaigns.csv + case_persons.csv
    （含双平台同素材锚点；扩容批次全追加——旧 20 案例逐字节不变）。"""
    _write_csv("brands_products.csv",
               ["brand_id", "brand_name", "category", "product_id", "app_name", "platform",
                "target_age", "spec", "detail", "price"],
               [[f"Brand:{b[0]}", b[1], b[2], f"Product:{p[0]}", p[1], p[3], p[4], "", "", ""]
                for b, p in zip(BRANDS, PRODUCTS[:8])]
               + [[f"Brand:{s[6]}", next(b[1] for b in BRANDS if b[0] == s[6]), s[2],
                   f"Product:{s[0]}", s[1], "电商", AGE_BY_CATEGORY[s[2]],
                   s[3], s[4], s[5]] for s in SKUS]
               # 扩容批次：16 家新品牌各 1 App + 6 支新 SKU（追加行）
               + [[f"Brand:{b[0]}", b[1], b[2], f"Product:{p[0]}", p[1], p[3], p[4], "", "", ""]
                  for b, p in zip(NEW_BRANDS, NEW_PRODUCTS)]
               + [[f"Brand:{s[6]}", next(b[1] for b in NEW_BRANDS if b[0] == s[6]), s[2],
                   f"Product:{s[0]}", s[1], "电商", AGE_BY_CATEGORY[s[2]],
                   s[3], s[4], s[5]] for s in NEW_SKUS])
    cases, rows, people_rows = [], [], []
    case_of_person: dict[str, str] = {}
    case_name_by_id: dict[str, str] = {}
    for i, stage in enumerate(STAGES, 1):
        bi = i % len(BRANDS)
        brand = BRANDS[bi]
        # 商品归属同品牌（App/小程序都从该品牌取）——brand 按 i%8、product 按 i%15
        # 各选各的会错配出「澄肌研究所·途野露营App」这类假数据（2026-10-20 实测）
        product = PRODUCTS[8 + bi] if (i % 2 == 1 and bi < 7) else PRODUCTS[bi]
        # 有 SKU 的品牌：奇数案例与 i%8==0 的案例推广 SKU（商品粒度统计的演示锚）
        if brand[0] in SKU_BY_BRAND and (i % 2 == 1 or i % 8 == 0):
            sku = next(s for s in SKUS if s[0] == SKU_BY_BRAND[brand[0]])
            product = (sku[0], sku[1], sku[2], "电商", AGE_BY_CATEGORY[sku[2]])
        person = PEOPLE[i % len(PEOPLE)]
        case_id = f"Case:C-2025-{i:03d}"
        case_name = f"{brand[1]}·{product[1]}投放案例"     # 与案例文档标题同式（图上 Case.name）
        case_name_by_id[case_id] = case_name
        cases.append((case_id, stage, brand, product, person))
        case_of_person.setdefault(person[0], case_id)
        lost_reason = LOST_REASONS[(i - 15) % 3] if stage == "lost" else ""
        term_reason = TERMINATE_REASONS[(i - 18) % 3] if stage == "terminated" else ""
        # 毛利率（spec §5 结算中心）：live 预估 / closed 结案口径；其余阶段留空。
        # 纯 i 算术（10%–34%），不进 rng 流——既有数值序列零扰动
        margin = f"{((i * 13) % 25 + 10) / 100:.2f}" if stage in ("live", "closed") else ""
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
                             channel, lost_reason, term_reason, margin])
    # 双平台同素材锚点（§12.5）：同一本体素材在两平台各有 local id
    rows.append(["Case:C-2025-005", case_name_by_id["Case:C-2025-005"], "live", "36000", "unbilled",
                 "Brand:B06", "Product:P06", "Campaign:C-2025-005-cp1", "信息流计划·A",
                 "delivering", "4200", "Creative:creative_992", "上门洗护种草 15s 竖版",
                 "1", "douyin", "信息流", "", "", "0.23"])
    rows.append(["Case:C-2025-005", case_name_by_id["Case:C-2025-005"], "live", "36000", "unbilled",
                 "Brand:B06", "Product:P06", "Campaign:C-2025-005-cp1", "信息流计划·A",
                 "delivering", "4200", "Creative:creative_992", "上门洗护种草 15s 竖版",
                 "1", "xhs", "信息流", "", "", "0.23"])
    # ── 扩容批次：新案例 40（i=21..60），品牌铺满全部 24 家 ──────────
    all_brands = BRANDS + NEW_BRANDS
    cat_sku = {s[2]: s for s in SKUS + NEW_SKUS}
    case_person_rows = []
    for k, stage in enumerate(NEW_STAGES):
        i = 21 + k
        brand = all_brands[k % len(all_brands)]
        if brand[0] in {b[0] for b in BRANDS}:        # 旧品牌用既有 App/小程序
            bidx = next(j for j, b in enumerate(BRANDS) if b[0] == brand[0])
            product = PRODUCTS[8 + bidx] if (k % 2 == 1 and bidx < 7) else PRODUCTS[bidx]
        else:
            product = NEW_PRODUCTS[[b[0] for b in NEW_BRANDS].index(brand[0])]
        if brand[2] in cat_sku and k % 3 == 1:        # 每 3 单 1 支 SKU（交易面加厚）
            s = cat_sku[brand[2]]
            product = (s[0], s[1], s[2], "电商", AGE_BY_CATEGORY[s[2]])
        person = PEOPLE[(i + k) % len(PEOPLE)]
        case_id = f"Case:C-2025-{i:03d}"
        case_name = f"{brand[1]}·{product[1]}投放案例"
        cases.append((case_id, stage, brand, product, person))
        case_person_rows.append([case_id, f"Person:{person[0]}"])
        lost_reason = LOST_REASONS[(i - 15) % 3] if stage == "lost" else ""
        term_reason = TERMINATE_REASONS[(i - 18) % 3] if stage == "terminated" else ""
        margin = f"{((i * 13) % 25 + 10) / 100:.2f}" if stage in ("live", "closed") else ""
        for c in range(2):
            camp = f"Campaign:{case_id.split(':')[1]}-cp{c + 1}"
            channel = CHANNELS[(i + c) % 3]
            camp_name = f"{channel}计划·{CAMP_SEQ[c]}"
            for kk in range(2):
                cid = f"Creative:{case_id.split(':')[1]}-cp{c + 1}-cr{kk + 1}"
                titles = TITLE_BY_CHANNEL[channel]
                rows.append([case_id, case_name, stage, f"{(i * 7 + c * 3) % 9 + 1}0000",
                             "paid" if stage == "closed" else "unbilled",
                             f"Brand:{brand[0]}", f"Product:{product[0]}", camp, camp_name,
                             "delivering" if stage == "live" else "paused",
                             f"{(i + c) % 5 * 1000 + 3000}", cid,
                             titles[(i + c + kk) % len(titles)],
                             "1" if (i + kk) % 3 == 0 else "0",
                             ["douyin", "xhs"][(i + c + kk) % 2],
                             channel, lost_reason, term_reason, margin])
    _write_csv("cases_campaigns.csv",
               ["case_id", "case_name", "stage", "bd_budget", "settlement_status", "brand_id",
                "product_id", "campaign_id", "campaign_name", "campaign_status", "daily_budget",
                "creative_id", "creative_title", "is_aigc", "platform", "channel",
                "lost_reason", "terminate_reason", "gross_margin"], rows)
    for idx, (pid, name, role) in enumerate(PEOPLE):
        people_rows.append([f"Person:{pid}", name, role,
                            f"Brand:{BRANDS[idx % 8][0]}", case_of_person[pid], "0"])
    people_rows.append([f"Person:{CLIENT[0]}", CLIENT[1], CLIENT[2], "Brand:B04", "", "1"])
    _write_csv("org_people.csv",
               ["person_id", "name", "org_role", "brand_id", "case_id", "is_external"],
               people_rows)
    # 扩容批次：新案例的 responsible_for（org_people 逐字节不动，单独立表）
    _write_csv("case_persons.csv", ["case_id", "person_id"], case_person_rows)
    return cases


def gen_docs(cases) -> None:
    """案例 md + 规范 md 直写 data/raw（2026-10-23 起 seed 不再存文档副本——
    生成器模板即真源，raw 是唯一落盘处；clone 后先跑本脚本再 load_seed）。"""
    RAW.mkdir(parents=True, exist_ok=True)
    for case_id, stage, brand, product, person in cases:
        text = (f"# {brand[1]}·{product[1]}投放案例\n\n"
                f"对接人 {person[1]}（{person[2]}）负责本案，当前阶段 {stage}。\n\n"
                f"## 背景\n{brand[1]} 是{brand[2]}赛道品牌，推广商品「{product[1]}」，"
                f"主打 {product[3]} 端获客。\n\n"
                f"## 投放\n两支计划分别跑信息流与搜索，素材以竖版短视频为主，"
                f"其中一条为 AIGC 生成并沿用爆款衍生。\n\n"
                f"## 结果\n{'转化成本优于行业均值，已结案复盘。' if stage == 'closed' else '投放进行中，CPA 稳定在目标区间。'}\n")
        (RAW / f"{case_id.split(':')[1]}.md").write_text(text, encoding="utf-8")
    for gid, gtype, max_dur, body in GUIDELINES:
        fm = f"---\nid: Guideline:{gid}\nguideline_type: {gtype}\n"
        if max_dur:
            fm += f"max_duration_s: {max_dur}\n"
        fm += "---\n\n"
        (RAW / f"{gid}.md").write_text(
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
    # 扩容批次：新案例 80 素材/平台 × 28 天（整月铺满，近30天/上月窗口有数）× 两平台 = 各 +2240 行
    # （local id 段 dy_cr100+ / xhs_cr100+ 与 load_seed 扩容别名一一对应；
    #  行键 (j%12 月, j//80 日, j%30 计划, j%80 素材) 在 2240 内不重复；
    #  独立随机流 rng4——主 rng 消费序零扰动，gen_product_orders 旧字节不变）
    rng4 = random.Random(2025)
    for j in range(2240):
        d = f"{months[j % 12][0]}-{months[j % 12][1]:02d}-{j // 80 + 1:02d}"
        imp = rng4.randint(8000, 60000)
        clk = int(imp * rng4.uniform(0.004, 0.02))
        douyin.append([d, f"dy_c{50 + j % 30}", f"dy_cr{100 + j % 80}",
                       round(rng4.uniform(80, 400), 2), imp, clk,
                       max(1, int(clk * rng4.uniform(0.02, 0.08)))])
        imp2 = rng4.randint(5000, 40000)
        clk2 = int(imp2 * rng4.uniform(0.003, 0.015))
        xhs.append([d, f"xhs_c{50 + j % 30}", f"xhs_cr{100 + j % 80}",
                    round(rng4.uniform(60, 300), 2), imp2, clk2,
                    max(1, int(clk2 * rng4.uniform(0.02, 0.07)))])
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


def gen_product_orders() -> None:
    """SKU 交易种子（§六 交易口径分列）：product_orders_daily.csv，近 90 天；
    购买率 = orders / clicks（与投放点击按 product×day join，README §六）。"""
    today = date.today()
    rows = []
    for sku in SKUS:
        price = SKU_PRICE[sku[0]]
        for d in range(90):
            day = today - timedelta(days=d)
            orders = rng.randint(3, 50)
            rows.append([day.isoformat(), f"Product:{sku[0]}", orders,
                         round(orders * price, 2)])
    for sku in NEW_SKUS:                                 # 扩容批次：6 支新 SKU × 90 天
        price = float(sku[5])
        for d in range(90):
            day = today - timedelta(days=d)
            orders = rng.randint(3, 50)
            rows.append([day.isoformat(), f"Product:{sku[0]}", orders,
                         round(orders * price, 2)])
    _write_csv("product_orders_daily.csv",
               ["date", "product_id", "orders", "gmv"], rows)


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


# ── 达人种子（spec §3）：独立随机流 rng2，不扰动既有数值序列（确定性重跑可 diff）──
CAT_CREATORS = {          # 8 品类 × 2 达人：与 BRANDS 品类一一对应（niche 匹配合作）
    "餐饮":       [("轻卡食堂长", "低卡测评|探店"), ("深夜食堂老柒", "探店|美食制作")],
    "运动健身":   [("燃脂教练阿力", "健身教学|运动装备"), ("马拉松笔记", "跑步|体能训练")],
    "文化阅读":   [("书房夜航船", "读书|社科拆书"), ("通勤听书酱", "听书|职场成长")],
    "美妆个护":   [("成分党阿澄", "成分测评|护肤"), ("油皮自救指南", "护肤|平价好物")],
    "户外旅行":   [("山野老周", "露营|户外装备"), ("营地设计师小鹿", "露营|亲子出行")],
    "宠物服务":   [("铲屎官阿喵", "养宠日常|宠物用品"), ("宠物行为学长大乖", "宠物训练|养宠科普")],
    "教育学习":   [("速算蜂脑力课", "思维训练|学习方法"), ("职场充电宝典", "效率工具|职场技能")],
    "健康睡眠":   [("睡眠研究所", "睡眠科普|助眠好物"), ("深眠实验室", "健康监测|作息管理")],
}
CROSS_CREATORS = [        # 跨品类达人：带货宽、报价高
    ("食旅阿岛", "美食|旅行|探店", "douyin"),
    ("穿搭研究所长", "穿搭|好物开箱", "xhs"),
    ("数码先森", "3C数码|开箱测评", "douyin"),
    ("亲子实验田", "亲子|家居好物", "xhs"),
]
# 扩容批次新达人（spec §12）：品类 24（每类 +3）+ 跨品类 16
NEW_CAT_CREATORS = {
    "餐饮":       [("干饭阿宝", "探店|家常菜"), ("轻食厨房日记", "低卡食谱|便当"), ("深夜饼铺", "街头小吃|探店")],
    "运动健身":   [("硬拉老K", "力量训练|健身房"), ("跳绳奶奶", "居家燃脂|打卡"), ("球场教练Tom", "篮球教学|体能")],
    "文化阅读":   [("拆书匠老白", "社科拆书|书单"), ("纸页旅行", "文学解读|随笔"), ("地铁读书人", "通勤阅读|摘抄")],
    "美妆个护":   [("早八化妆师Mia", "通勤妆|平价彩妆"), ("油痘肌自救", "祛痘|护肤成分"), ("香水小卖部", "香评|小众香")],
    "户外旅行":   [("折叠椅侦探", "露营装备|营地测评"), ("徒步的栗子", "徒步路线|户外安全"), ("后备箱食堂", "露营烹饪|车载好物")],
    "宠物服务":   [("猫粮侦探", "猫粮测评|养猫"), ("训犬师大米", "狗狗训练|行为纠正"), ("异宠小课堂", "小宠科普|饲养")],
    "教育学习":   [("错题本爷爷", "学习方法|考试策略"), ("英语早茶", "口语练习|晨读"), ("几何可视化", "数学思维|图解")],
    "健康睡眠":   [("助眠白噪音坊", "白噪音|睡前放松"), ("褪黑素研究员", "睡眠科普|作息实验"), ("卧室改造家", "寝具测评|睡眠环境")],
}
NEW_CROSS_CREATORS = [
    ("好物猎人阿奇", "好物开箱|测评", "douyin"), ("厨房与远方", "美食|旅行|露营", "xhs"),
    ("全家好物志", "家居|亲子好物", "xhs"), ("极客爸爸", "3C数码|亲子", "douyin"),
    ("省钱研究所", "平价好物|比价", "douyin"), ("办公室生存指南", "职场好物|效率", "xhs"),
    ("健身餐盆友", "健身餐|低卡好物", "douyin"), ("猫狗双全", "养宠|好物开箱", "xhs"),
    ("书包里的大人", "文具|学习好物", "xhs"), ("夜宵自救指南", "美食|深夜放毒", "douyin"),
    ("户外美学部", "露营|穿搭", "xhs"), ("运动装备控", "运动装备|球鞋", "douyin"),
    ("书桌改造计划", "学习空间|文具", "xhs"), ("早睡俱乐部", "作息管理|助眠好物", "douyin"),
    ("成分党小翻", "成分测评|个护", "xhs"), ("宠物出行家", "携宠旅行|户外", "douyin"),
]
CREATOR_CITIES = ["杭州", "上海", "北京", "广州", "成都", "长沙", "厦门", "重庆"]


def gen_creators(cases) -> None:
    """creators.csv / case_creators.csv / creator_products.csv（spec §3）。

    达人 20 = 8 品类 × 2 + 跨品类 4；live/closed 案例挂 1–3 位品类匹配达人
    （每 3 单加一位跨品类）；带货 = 品类同源商品（含 SKU），跨品类达人带全部 SKU。
    """
    rng2 = random.Random(4242)
    products_of_cat: dict[str, list[str]] = {}
    for p in PRODUCTS:
        products_of_cat.setdefault(p[2], []).append(f"Product:{p[0]}")
    for s in SKUS:
        products_of_cat.setdefault(s[2], []).insert(0, f"Product:{s[0]}")
    sku_ids = [f"Product:{s[0]}" for s in SKUS]

    rows, collab_rows, promote_rows = [], [], []
    cat_creator_ids: dict[str, list[str]] = {}            # 品类 → 达人 id（合作匹配用）
    cid_seq = 0
    rng5 = random.Random(2026)                            # 扩容批次独立流：旧 rng2 消费序零扰动

    def _add(name, niches, platform, stream):
        nonlocal cid_seq
        cid_seq += 1
        followers = stream.randint(50_000, 8_000_000)
        quote_20s = max(2_000, min(150_000, int(followers * stream.uniform(0.002, 0.02))))
        row = [f"Creator:cr{cid_seq:02d}", name, platform, niches, followers, quote_20s,
               int(quote_20s * 0.6), stream.randint(100_000, 30_000_000),
               CREATOR_CITIES[cid_seq % len(CREATOR_CITIES)], round(stream.uniform(4.0, 5.0), 1)]
        rows.append(row)
        return row[0]

    for cat, pairs in CAT_CREATORS.items():
        for name, niches in pairs:
            cr_id = _add(name, niches, "douyin" if len(rows) % 2 == 0 else "xhs", rng2)
            cat_creator_ids.setdefault(cat, []).append(cr_id)
            # 带货：品类同源商品（品类达人主推本品类，SKU 权重靠前）
            for pid in products_of_cat.get(cat, []):
                promote_rows.append([cr_id, pid])
    for name, niches, platform in CROSS_CREATORS:
        cr_id = _add(name, niches, platform, rng2)
        for pid in sku_ids:                    # 跨品类达人带全部 SKU
            promote_rows.append([cr_id, pid])

    # ── 扩容批次：新达人 40（cr21..cr60）＝ 品类 24（每类 +3）+ 跨品类 16 ──
    new_products_of_cat = {c: list(ps) for c, ps in products_of_cat.items()}
    for p in NEW_PRODUCTS:
        new_products_of_cat.setdefault(p[2], []).append(f"Product:{p[0]}")
    for s in NEW_SKUS:
        new_products_of_cat.setdefault(s[2], []).insert(0, f"Product:{s[0]}")
    all_sku_ids = sku_ids + [f"Product:{s[0]}" for s in NEW_SKUS]
    new_cat_ids: dict[str, list[str]] = {}
    for cat, pairs in NEW_CAT_CREATORS.items():
        for name, niches in pairs:
            cr_id = _add(name, niches, "douyin" if len(rows) % 2 == 0 else "xhs", rng5)
            new_cat_ids.setdefault(cat, []).append(cr_id)
            for pid in new_products_of_cat.get(cat, []):
                promote_rows.append([cr_id, pid])
    new_cross = []
    for name, niches, platform in NEW_CROSS_CREATORS:
        cr_id = _add(name, niches, platform, rng5)
        new_cross.append(cr_id)
        for pid in all_sku_ids:
            promote_rows.append([cr_id, pid])

    # 合作：旧案例（i≤20）保持原字节逻辑；新案例挂新达人 2 位 + 旧品类达人 1 位，
    # 每 3 单再加一位新跨品类（新达人有单可查、旧达人合作史加厚）
    cross_ids = [r[0] for r in rows[:20]][-len(CROSS_CREATORS):]
    for case_id, stage, brand, product, person in cases:
        if stage not in ("live", "closed"):
            continue
        i_num = int(case_id.split("-")[-1])
        if i_num <= 20:
            picked = list(cat_creator_ids.get(brand[2], [])[:2])
            if i_num % 3 == 0:
                picked.append(cross_ids[i_num % len(cross_ids)])
        else:
            pool_new = new_cat_ids.get(brand[2], [])
            pool_old = cat_creator_ids.get(brand[2], [])
            picked = [pool_new[(i_num + j) % len(pool_new)] for j in range(2)]
            if pool_old:
                picked.append(pool_old[i_num % 2])
            if i_num % 3 == 0:
                picked.append(new_cross[i_num % len(new_cross)])
        for cr_id in picked:
            base_quote = next(r[5] for r in rows if r[0] == cr_id)
            collab_rows.append([case_id, cr_id, int(base_quote * rng2.uniform(0.85, 1.1))])

    _write_csv("creators.csv",
               ["creator_id", "name", "platform", "niches", "followers", "quote_20s",
                "quote_image", "gmv_30d", "city", "rating"], rows)
    _write_csv("case_creators.csv",
               ["case_id", "creator_id", "deal_quote"], collab_rows)
    _write_csv("creator_products.csv",
               ["creator_id", "product_id"], promote_rows)
    # 报价历史种子（spec §15）：旧 20 位达人 × 30 天轨迹（±8% 波动，独立 rng6——
    # 旧流零扰动）；三条入库口运行时也会追加快照，曲线随真实使用长尾生长
    rng6 = random.Random(2027)
    hist = []
    today = date.today()
    for r in rows[:20]:
        base = int(r[5])
        for d in range(30, 0, -1):
            hist.append([r[0], (today - timedelta(days=d)).isoformat(),
                         max(500, int(base * rng6.uniform(0.92, 1.08)))])
    _write_csv("quote_history.csv",
               ["creator_id", "date", "quote_20s"], hist)


if __name__ == "__main__":
    cases = gen_master()
    gen_docs(cases)
    gen_facts()
    gen_audiences()
    gen_product_orders()
    gen_assertions()
    gen_creators(cases)
    n_csv = sum(1 for p in SEED.rglob("*") if p.is_file())
    n_doc = sum(1 for p in RAW.rglob("*") if p.is_file())
    print(f"seed 生成完成：CSV {n_csv} 个 → data/seed/，文档 {n_doc} 个 → data/raw/")
