"""Remove the existing GeneScope website Basic Auth, retaining TLS and proxy rules.

Standalone, standard-library-only utility for the existing Caddy deployment.
The users file and certificate volumes are preserved for rollback.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

DEFAULT_GATEWAY = Path('/opt/genescope/gateway/20261102-ip-https')
AUTH_BLOCK = re.compile(r'^[ \t]*basic_auth[ \t]*\{\s*import[ \t]+/etc/genescope/users\.caddy[ \t]*\r?\n[ \t]*\}[ \t]*\r?\n?', re.MULTILINE)


def public_config(text):
    updated, count = AUTH_BLOCK.subn('', text)
    if count > 1 or re.search(r'^\s*(?:basic_auth|basicauth)\b', updated, re.MULTILINE) or 'users.caddy' in updated:
        raise ValueError('网关认证格式与现有部署不一致，停止自动修改')
    if 'https://47.243.232.201' not in updated or 'reverse_proxy 127.0.0.1:18080' not in updated:
        raise ValueError('不是现有 GeneScope 2 HTTPS 网关，停止自动修改')
    return updated


def run(args):
    return subprocess.run(args, check=True)


def gateway_files(directory):
    directory = Path(directory).resolve()
    for name in ('Caddyfile', 'compose.gateway.json'):
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'网关文件缺失或为符号链接：{name}')
    compose = json.loads((directory / 'compose.gateway.json').read_text(encoding='utf-8'))
    image = compose.get('services', {}).get('gateway', {}).get('image')
    if not isinstance(image, str) or not image.startswith('caddy:') or any(c.isspace() for c in image):
        raise ValueError('保留现有 Caddy 镜像；当前网关配置不符合预期')
    command = ['docker', 'compose', '-f', str(directory / 'compose.gateway.json'), 'up', '-d', '--no-deps', '--force-recreate', 'gateway']
    return directory, image, command


def configure(directory=DEFAULT_GATEWAY, apply=False):
    directory, image, command = gateway_files(directory)
    target = directory / 'Caddyfile'
    original = target.read_bytes()
    updated = public_config(original.decode('utf-8')).encode('utf-8')
    if updated == original:
        return {'public_access': True, 'changed': False, 'website_login_required': False}
    candidate = directory / ('Caddyfile.public-candidate-' + uuid.uuid4().hex[:8])
    candidate.write_bytes(updated)
    # Validate before replacing the live bind-mounted configuration. No password is required.
    run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--tmpfs', '/tmp:rw,size=16m',
         '-e', 'XDG_CONFIG_HOME=/tmp/config', '-e', 'XDG_DATA_HOME=/tmp/data',
         '-v', f'{candidate}:/etc/caddy/Caddyfile:ro', image, 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile'])
    if not apply:
        return {'dry_run': True, 'website_login_required_after_apply': False, 'candidate': str(candidate)}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = directory / ('Caddyfile.before-public-' + stamp)
    shutil.copy2(target, backup)
    record = {'public_access': True, 'changed': True, 'website_login_required': False,
              'previous_caddyfile': str(backup), 'previous_sha256': hashlib.sha256(original).hexdigest(),
              'tls_and_users_file_preserved': True}
    try:
        target.write_bytes(updated)
        run(command)
        # Validate HTTPS through the local gateway without supplying credentials or disabling TLS verification.
        run(['curl', '--noproxy', '*', '--connect-to', '47.243.232.201:443:127.0.0.1:443',
             '--retry', '8', '--retry-delay', '2', '--retry-connrefused', '--max-time', '20',
             '--fail', '--silent', '--show-error', '--output', '/dev/null', 'https://47.243.232.201/'])
        (directory / 'public_access_switch.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    except Exception:
        target.write_bytes(original)
        run(command)
        raise
    return record


def rollback(directory=DEFAULT_GATEWAY):
    directory, _, command = gateway_files(directory)
    record = json.loads((directory / 'public_access_switch.json').read_text(encoding='utf-8'))
    backup = Path(record['previous_caddyfile']).resolve()
    if backup.parent != directory or not backup.name.startswith('Caddyfile.before-public-') or not backup.is_file() or backup.is_symlink():
        raise ValueError('无效的网关回滚记录')
    original = backup.read_bytes()
    if hashlib.sha256(original).hexdigest() != record['previous_sha256']:
        raise ValueError('网关备份校验失败')
    (directory / 'Caddyfile').write_bytes(original)
    run(command)
    return {'restored_previous_gateway': True, 'backup': str(backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['check', 'apply', 'rollback'])
    parser.add_argument('--gateway-dir', type=Path, default=DEFAULT_GATEWAY)
    args = parser.parse_args()
    result = rollback(args.gateway_dir) if args.action == 'rollback' else configure(args.gateway_dir, args.action == 'apply')
    print(json.dumps(result, ensure_ascii=False, indent=2))
