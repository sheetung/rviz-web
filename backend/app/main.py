"""
FastAPI 应用入口
支持 RViz Web 可视化系统
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.v1 import configs, ros, video
from .core.config import get_settings
from .core.security import origin_is_allowed
from .core.version import APP_VERSION
from .services.dependencies import get_rosbridge_service

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 获取配置
settings = get_settings()
DOCS_ASSETS_DIR = Path(__file__).resolve().parent / "static" / "swagger-ui"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting RViz Web Visualization System")
    service = get_rosbridge_service()
    await service.start()
    logger.info("Server started on port %s", settings.backend_port)
    try:
        yield
    finally:
        logger.info("Shutting down RViz Web Visualization System")
        await video.shutdown_video_streams()
        await service.stop()


# 创建 FastAPI 应用
app = FastAPI(
    title="RViz Web Visualization",
    description="基于 Vue.js + FastAPI 的 ROS2 可视化平台",
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


app.mount(
    "/docs-assets",
    StaticFiles(directory=DOCS_ASSETS_DIR),
    name="docs-assets",
)


@app.get("/docs", include_in_schema=False)
async def swagger_ui_html():
    """使用仓库内静态资源提供 Swagger UI。"""
    return HTMLResponse("""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>RViz Web Visualization - Swagger UI</title>
    <link rel="stylesheet" href="/docs-assets/swagger-ui.css">
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="/docs-assets/swagger-ui-bundle.js"></script>
    <script src="/docs-assets/swagger-init.js"></script>
  </body>
</html>
""")


@app.get("/openapi.json", include_in_schema=False)
async def openapi_schema():
    return JSONResponse(app.openapi())


# 全局 Rosbridge 服务实例将通过依赖注入管理

# 注册 API 路由
app.include_router(ros.router, prefix="/api/v1", tags=["ROS"])
app.include_router(configs.router, prefix="/api/v1", tags=["Configs"])
app.include_router(video.router, prefix="/api/v1", tags=["Video"])


@app.get("/")
async def root():
    """根路径"""
    return {"message": "RViz Web Visualization System", "version": APP_VERSION}


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": "ros-web-viz",
        "version": APP_VERSION,
    }


@app.get("/api/v1/version")
async def version_info():
    """返回工程、API 与配置格式版本。"""
    return {
        "version": APP_VERSION,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 端点 - Rosbridge 协议"""
    if not origin_is_allowed(websocket.headers.get("origin"), settings):
        await websocket.close(code=4403, reason="Origin not allowed")
        return
    service = get_rosbridge_service()
    await service.handle_websocket(websocket)


# 单容器部署时提供 SPA；必须最后挂载，避免遮蔽 /health、/api 和 /ws。
if os.path.exists("./static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.debug,
    )
