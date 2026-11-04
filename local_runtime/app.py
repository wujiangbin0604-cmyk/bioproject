"""在同一个本机端口提供现有FastAPI与前端成品。"""
from pathlib import Path
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from backend.app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


class LocalFrontend(StaticFiles):
    """浏览器路由回退到首页；缺失API及静态文件继续返回404。"""

    async def get_response(self, path, scope):
        normalized = path.replace('\\', '/').lstrip('/')
        if normalized == 'api' or normalized.startswith('api/'):
            raise HTTPException(404)
        try:
            response = await super().get_response(path, scope)
            if response.status_code != 404:
                return response
        except HTTPException as error:
            if error.status_code != 404:
                raise
        # Never turn API errors or missing JS/CSS into an HTML success response.
        if normalized.startswith('assets/') or Path(normalized).suffix:
            raise HTTPException(404)
        return await super().get_response('index.html', scope)


def create_local_app(root=ROOT):
    """保持原API、进程监督与退出清理，仅挂载静态前端。"""
    root = Path(root).resolve()
    frontend = root / 'frontend/dist'
    if not (frontend / 'index.html').is_file():
        raise RuntimeError('前端尚未构建，请先执行 python genescope.py setup')
    app = create_app(project_root=root)
    app.mount('/', LocalFrontend(directory=frontend, html=True), name='local-frontend')
    return app
