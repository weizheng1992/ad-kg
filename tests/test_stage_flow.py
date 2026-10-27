"""案例状态机多源同源守门（缺陷清单⑧余项）：合法迁移唯一真源 =
ontology/schema.yaml#constraints.case_stage。ActionChecker 裁决、/cases 详情
的展示形态（主线/分支/迁移表下发）、CaseStage 枚举、前端阶段词表都必须由它
派生或与它一致——此前 STAGE_FLOW / STAGE_BRANCH / NEXT_STAGES 三处手抄，
漂移无人拦。本文件纯静态对账（读文件 + 正则，不依赖 DB），漂移即红。
"""
import re
from pathlib import Path

from adkg.models import CaseStage, load_schema

ROOT = Path(__file__).resolve().parents[1]

CASE_STAGE = load_schema()["constraints"]["case_stage"]
TRANSITIONS: dict[str, list[str]] = CASE_STAGE["transitions"]
STAGES = set(TRANSITIONS) | {d for dsts in TRANSITIONS.values() for d in dsts}


def test_迁移表自洽终态无出边():
    assert CASE_STAGE["initial"] in STAGES
    assert set(CASE_STAGE["terminal"]) <= STAGES
    for src in CASE_STAGE["terminal"]:
        assert TRANSITIONS.get(src) == [], f"终态 {src} 不可有出边"


def test_CaseStage枚举与schema迁移表同源():
    # models.CaseStage 是 case_gen 校验 Case.stage 取值域的枚举，必须恰为表内阶段全集
    assert {s.value for s in CaseStage} == STAGES, (
        f"枚举漂移：仅枚举 {sorted({s.value for s in CaseStage} - STAGES)} / "
        f"仅 schema {sorted(STAGES - {s.value for s in CaseStage})}——以 schema.yaml 为准")


def test_展示形态由迁移表派生():
    """/cases 的流转条与合法目标下拉不再手抄：常量必须等于 schema 派生结果
    （钉住当前展示形状——schema 改表后此处红，展示语义需随表一并确认）。"""
    from adkg.api.routes.cases import STAGE_BRANCH, STAGE_FLOW, STAGE_TRANSITIONS
    assert STAGE_TRANSITIONS == TRANSITIONS            # 下发给前端的即 schema 原表
    assert STAGE_FLOW == ["proposal", "live", "closed"]
    assert STAGE_BRANCH == {"lost": "proposal", "terminated": "live"}
    # 派生不变量：主线相邻两步 = 来源迁移表的首目标；分支 = 非首目标挂回来源
    for a, b in zip(STAGE_FLOW, STAGE_FLOW[1:]):
        assert TRANSITIONS[a][:1] == [b], f"主线 {a}→{b} 不是首目标链"
    for dst, src in STAGE_BRANCH.items():
        assert dst in TRANSITIONS[src][1:], f"分支 {src}→{dst} 不在迁移表"


def test_前端阶段词表与schema同源():
    """labels.ts STAGE_LABEL 键集 = schema 阶段全集——schema 加阶段没配中文即红。"""
    labels = (ROOT / "web" / "src" / "lib" / "labels.ts").read_text(encoding="utf-8")
    m = re.search(r"export const STAGE_LABEL[^{]*\{([^}]*)\}", labels)
    assert m, "web/src/lib/labels.ts 未找到 export const STAGE_LABEL 字面量"
    frontend = {k.split(":")[0].strip().strip("'\"")
                for k in m.group(1).split(",") if k.strip()}
    assert frontend == STAGES, (
        f"阶段词表漂移：仅前端 {sorted(frontend - STAGES)} / "
        f"仅 schema {sorted(STAGES - frontend)}——两侧需同步（以 schema.yaml 为准）")


def test_前端不再手抄迁移表():
    """合法目标一律消费后端 stage_flow.transitions 下发——NEXT_STAGES 手抄
    常量禁止回潮（三源漂移的病根）。"""
    page = (ROOT / "web" / "src" / "pages" / "cases" / "CaseDetailPage.tsx"
            ).read_text(encoding="utf-8")
    assert "NEXT_STAGES" not in page, "CaseDetailPage 不得手抄迁移表，改用 stage_flow.transitions"
    assert "flow.transitions" in page, "变更控件应消费后端下发的 transitions"
