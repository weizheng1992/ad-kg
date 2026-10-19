"""FastAPI 服务层（§三）：create_app(env) 便于测试注入环境。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from adkg.api.routes import ask  # noqa: E402


def create_app(env: dict[str, str] | None = None) -> FastAPI:
    app = FastAPI(title="AdKG", version="0.1.0",
                  description="本体驱动的广告营销知识中台（README §三）")
    app.state.env = dict(env or os.environ)
    app.include_router(ask.router)
    return app


app = create_app()
