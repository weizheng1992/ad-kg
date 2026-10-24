"""FastAPI 服务层（§三）：create_app(env) 便于测试注入环境。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from adkg.api.routes import (actions, admin, agent, ask, auth, brands, cases,  # noqa: E402
                             creative, creators, guideline, graph, ingest,
                             settlements, stats)


def create_app(env: dict[str, str] | None = None) -> FastAPI:
    app = FastAPI(title="AdKG", version="0.1.0",
                  description="本体驱动的广告营销知识中台（README §三）")
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])          # dev 演示；生产经反代收敛（§9.7）

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # 未捕获异常统一 JSON 500：Starlette 默认纯文本 body，HTTP 消费方（smartServe/
        # web）.json() 会直接抛 SyntaxError 掩盖真错；traceback 仍由 uvicorn 记录
        return JSONResponse(status_code=500,
                            content={"detail": f"internal error: {type(exc).__name__}"})

    app.state.env = dict(env or os.environ)
    app.include_router(auth.router)
    app.include_router(ask.router)
    app.include_router(creators.router)
    app.include_router(cases.router)
    app.include_router(brands.router)
    app.include_router(settlements.router)
    app.include_router(stats.router)
    app.include_router(admin.router)
    app.include_router(graph.router)
    app.include_router(actions.router)
    app.include_router(guideline.router)
    app.include_router(ingest.router)
    app.include_router(creative.router)
    app.include_router(agent.router)
    return app


app = create_app()
