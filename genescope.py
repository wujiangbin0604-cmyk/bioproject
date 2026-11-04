"""GeneScope本地启动、依赖安装、环境诊断及命令行使用入口。"""
from __future__ import annotations
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
ENV = ROOT / '.venv-local'
PACKAGES = ['fastapi', 'uvicorn', 'numpy', 'pandas', 'scikit-learn', 'joblib', 'scipy', 'psutil', 'python-multipart']


def environment_python(folder=ENV):
    """返回指定虚拟环境的解释器路径。"""
    return Path(folder) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def execute(command, **kwargs):
    """用参数数组运行子程序，不拼接shell命令。"""
    subprocess.run([str(item) for item in command], cwd=ROOT, check=True, **kwargs)


def setup(args):
    """在项目私有虚拟环境中安装依赖，源码版额外构建前端。"""
    if sys.version_info < (3, 12):
        raise RuntimeError('请先安装Python3.12或更新版本；冻结M1推荐精确Python3.14.0')
    from local_runtime.integrity import verify
    print(json.dumps(verify(ROOT), ensure_ascii=False), flush=True)
    if args.rebuild_frontend and (ROOT / 'local_bundle_manifest.json').is_file():
        raise RuntimeError('成品包保留原校验内容；需要重建前端请使用GitHub源码目录')
    frontend = ROOT / 'frontend/dist/index.html'
    if args.wheelhouse and not frontend.is_file():
        raise RuntimeError('离线安装需要带前端成品的Release包；源码版需先完成npm构建')
    python = environment_python()
    if not python.is_file():
        print('创建本项目虚拟环境 .venv-local ...', flush=True)
        execute([sys.executable, '-m', 'venv', ENV])
    pip = [python, '-m', 'pip', 'install', '--disable-pip-version-check', '--only-binary=:all:', '-r', ROOT / 'requirements-local.lock.txt']
    if args.wheelhouse:
        folder = Path(args.wheelhouse).resolve()
        if not folder.is_dir():
            raise RuntimeError('离线wheelhouse目录不存在')
        pip += ['--no-index', '--find-links', folder]
    print('安装本地运行依赖（不修改系统Python）...', flush=True)
    execute(pip)
    if not frontend.is_file() or args.rebuild_frontend:
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            raise RuntimeError('源码版构建需要Node.js与npm；可改为下载带前端成品的Release包')
        subprocess.run([npm, 'ci'], cwd=ROOT / 'frontend', check=True)
        subprocess.run([npm, 'run', 'build'], cwd=ROOT / 'frontend', check=True)
    print('安装完成。运行 python genescope.py，或双击 start_local.cmd。', flush=True)


def dependency_status():
    """只读检查必要运行包和精确冻结模型环境。"""
    installed, missing = {}, []
    for name in PACKAGES:
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    report = {'python': platform.python_version(), 'python_executable': sys.executable,
              'frontend_built': (ROOT / 'frontend/dist/index.html').is_file(), 'missing_packages': missing,
              'installed': installed, 'frozen_m1_available': False}
    if not missing:
        from deployment.model_loader import load_deployment_model, ModelArtifactError
        try:
            report['frozen_m1_version'] = load_deployment_model().metadata['model_version']
            report['frozen_m1_available'] = True
        except ModelArtifactError as error:
            report['frozen_m1_reason'] = str(error)
    return report


def runtime_python(current=False):
    """默认使用项目环境，显式--current-env才使用现有解释器。"""
    if current:
        return Path(sys.executable)
    target = environment_python()
    if not target.is_file():
        raise RuntimeError('本地环境不存在，请先执行 python genescope.py setup')
    return target


def open_when_ready(url, process):
    """服务真正响应后再打开浏览器，不用固定等待伪装启动成功。"""
    for _ in range(120):
        if process.poll() is not None:
            return
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url + '/api/v1/health', timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except (OSError, ValueError):
            pass
        time.sleep(.5)


def run(args):
    """只在127.0.0.1启动一个API进程，同时提供本地网页。"""
    if not args.current_env and not environment_python().is_file():
        setup(argparse.Namespace(wheelhouse=None, rebuild_frontend=False))
    from local_runtime.integrity import verify
    print(json.dumps(verify(ROOT), ensure_ascii=False), flush=True)
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise RuntimeError('前端未构建，请运行 python genescope.py setup --rebuild-frontend')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', args.port)) == 0:
            raise RuntimeError(f'端口{args.port}已被占用；请使用 python genescope.py --port 8788')
    python = runtime_python(args.current_env)
    env = os.environ.copy()
    env['GENESCOPE_ALLOWED_ORIGINS'] = f'http://127.0.0.1:{args.port},http://localhost:{args.port}'
    env['PYTHONUTF8'] = '1'
    url = f'http://127.0.0.1:{args.port}'
    print(f'GeneScope本地工作台：{url}\n按Ctrl+C退出；数据和任务保留在本地项目目录。', flush=True)
    process = subprocess.Popen([str(python), '-m', 'uvicorn', 'local_runtime.app:create_local_app', '--factory', '--host', '127.0.0.1', '--port', str(args.port), '--workers', '1'], cwd=ROOT, env=env)
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, process), daemon=True).start()
    try:
        return process.wait()
    except KeyboardInterrupt:
        try:
            return process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.terminate()
            return process.wait(timeout=8)


def main(argv=None):
    """统一处理默认启动、安装、诊断、校验和已有科研CLI。"""
    parser = argparse.ArgumentParser(description='GeneScope本地工作台，无需线上服务器')
    parser.add_argument('action', nargs='?', default='run', choices=['run', 'setup', 'doctor', 'verify', 'predict', 'data'])
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--current-env', action='store_true', help='高级：复用当前Python环境')
    parser.add_argument('--wheelhouse', type=Path)
    parser.add_argument('--rebuild-frontend', action='store_true')
    args, extra = parser.parse_known_args(argv)
    if args.action not in {'predict', 'data'} and extra:
        parser.error('无法识别参数：' + ' '.join(extra))
    if not 1024 <= args.port <= 65535:
        parser.error('端口必须为1024–65535')
    if args.action == 'setup':
        setup(args)
    elif args.action == 'run':
        return run(args)
    elif args.action == 'verify':
        from local_runtime.integrity import verify
        print(json.dumps(verify(ROOT), ensure_ascii=False, indent=2))
    elif args.action == 'doctor':
        target = runtime_python(args.current_env) if environment_python().is_file() or args.current_env else Path(sys.executable)
        if target.resolve() != Path(sys.executable).resolve():
            return subprocess.call([str(target), str(ROOT / 'genescope.py'), 'doctor', '--current-env'], cwd=ROOT)
        report = dependency_status()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(bool(report['missing_packages']) or not report['frontend_built'])
    else:
        target = runtime_python(args.current_env)
        command = [str(target), '-m', 'local_runtime.actions', *extra] if args.action == 'data' else [str(target), str(ROOT / 'deployment/predict.py'), *extra]
        return subprocess.call(command, cwd=ROOT)
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'GeneScope：{error}', file=sys.stderr)
        raise SystemExit(1)
