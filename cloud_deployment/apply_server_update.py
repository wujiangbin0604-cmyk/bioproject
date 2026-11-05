"""Apply the verified dashboard build and then enable the existing site's public access."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from urllib.request import ProxyHandler, build_opener

if __package__:
    from .update_frontend import apply_update, rollback, checked, sha
    from .configure_public_access import configure, DEFAULT_GATEWAY
else:
    from update_frontend import apply_update, rollback, checked, sha
    from configure_public_access import configure, DEFAULT_GATEWAY


def run(args):
    subprocess.run(args, check=True)


def read_api(path):
    opener = build_opener(ProxyHandler({}))
    with opener.open('http://127.0.0.1:18080' + path, timeout=15) as response:
        return json.load(response)


def wait_ready():
    last_error = None
    for _ in range(60):
        try:
            health = read_api('/api/v1/health')
            if health.get('data', {}).get('api') == 'ok':
                return
        except Exception as error:
            last_error = error
        time.sleep(2)
    raise RuntimeError(f'更新后服务未就绪：{last_error}')


def install(payload, release, gateway_dir=DEFAULT_GATEWAY, apply=False):
    payload, release = Path(payload).resolve(), Path(release).resolve()
    metadata = json.loads(checked(payload, 'frontend_update.json').read_text(encoding='utf-8'))
    if metadata.get('website_access') != 'public':
        raise ValueError('此更新包未声明免登录访问')
    required = {'apply_server_update.py', 'configure_public_access.py', 'update_frontend.py', 'FRONTEND_UPDATE.md'}
    if set(metadata.get('tools', {})) != required:
        raise ValueError('更新工具清单不完整')
    for name, digest in metadata['tools'].items():
        if sha(checked(payload, name)) != digest:
            raise ValueError(f'更新工具校验失败：{name}')
    result = apply_update(payload, release)
    tasks = read_api('/api/v1/experiments').get('items', [])
    if any(task.get('status') not in {'completed', 'failed', 'cancelled'} for task in tasks):
        raise ValueError('当前有未结束实验，请等实验完成后再更新')
    configure(gateway_dir, apply=False)
    if not apply:
        return {**result, 'website_access_after_apply': 'public'}
    compose = ['docker', 'compose', '-f', str(release / 'compose.genescope2.yaml')]
    updated = apply_update(payload, release, apply=True)
    try:
        run([*compose, 'build', 'web'])
        run([*compose, 'up', '-d', '--no-deps', '--no-build', 'web'])
        wait_ready()
        access = configure(gateway_dir, apply=True)
    except Exception as error:
        rollback(release, updated['backup'])
        try:
            run([*compose, 'build', 'web'])
            run([*compose, 'up', '-d', '--no-deps', '--no-build', 'web'])
            wait_ready()
        except Exception as recovery_error:
            raise RuntimeError(f'已恢复旧前端文件，但容器恢复失败；保留备份 {updated["backup"]}。原错误：{error}；恢复错误：{recovery_error}') from recovery_error
        raise RuntimeError('本次更新失败，已恢复旧前端与服务；网关切换失败时会自行恢复原配置') from error
    return {**updated, 'gateway': access, 'url': 'https://47.243.232.201/', 'website_login_required': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', type=Path, default=Path('/opt/genescope/releases/20261103-genescope2-v3'))
    parser.add_argument('--payload', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--gateway-dir', type=Path, default=DEFAULT_GATEWAY)
    parser.add_argument('--apply', action='store_true', help='默认仅校验；指定后更新前端并取消网站登录验证')
    args = parser.parse_args()
    print(json.dumps(install(args.payload, args.release, args.gateway_dir, args.apply), ensure_ascii=False, indent=2))
