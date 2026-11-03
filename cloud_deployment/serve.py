"""一个容器内管理loopback API和静态代理；只通过代理提供网页与API。"""
from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

from cloud_deployment.verify import verify_content


def main():
    root = Path(__file__).resolve().parents[1]
    verify_content(root)
    for directory in ("nginx", "nginx/client", "nginx/proxy", "nginx/fastcgi", "nginx/uwsgi", "nginx/scgi"):
        (Path("/tmp") / directory).mkdir(parents=True, exist_ok=True)
    subprocess.run(["nginx", "-e", "stderr", "-t", "-c", str(root / "cloud_deployment/nginx.conf")], check=True)
    processes = []

    def shutdown(_number, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app",
                                           "--host", "127.0.0.1", "--port", "8000", "--workers", "1", "--no-proxy-headers"], cwd=root))
        processes.append(subprocess.Popen(["nginx", "-e", "stderr", "-c", str(root / "cloud_deployment/nginx.conf"), "-g", "daemon off;"]))
        while True:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("API或网页服务退出，请检查docker compose logs")
            time.sleep(.5)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
