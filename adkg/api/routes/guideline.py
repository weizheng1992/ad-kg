"""POST /guideline/check（§9.4）：生成前机判——只查结构化阈值，不做语义比对。

语义 / 多模态比对归 smartServe 的 AIGC Agent 或人工（§十三）；
本端点是 AIGC 闭环的"生成前查规范"半边，另半边是 /ingest/assertion 写回。
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.auth import AuthService

router = APIRouter()


@router.post("/guideline/check")
def guideline_check(request: Request, body: dict,
                    authorization: str | None = Header(default=None)) -> dict:
    env = request.app.state.env
    resolved = AuthService(env).resolve(authorization)
    if not resolved and not (env.get("ADKG_DEV_AUTH") == "off" and body.get("role")):
        raise HTTPException(401, "缺有效 service token")

    spec = body.get("spec") or {}
    duration = spec.get("duration_s")
    if duration is None:
        raise HTTPException(422, "spec.duration_s 必填（机判阈值项）")

    from adkg.api.routes.actions import _graph
    guidelines = _graph(request).guidelines_with_thresholds()
    applicable, violations = [], []
    for g in guidelines:
        item = {"guideline_id": g["id"], "type": g["gtype"]}
        if g["max_duration_s"] is not None:
            item["max_duration_s"] = g["max_duration_s"]
            if float(duration) > float(g["max_duration_s"]):
                violations.append({**item, "actual_duration_s": duration,
                                   "rule": f"时长 {duration}s 超过上限 {g['max_duration_s']}s"})
        applicable.append(item)
    return {"applicable": applicable, "violations": violations,
            "note": "机判只覆盖结构化阈值（时长等）；语义比对归 AIGC Agent，"
                    "结果经 /ingest/assertion 写回（§9.4）"}
